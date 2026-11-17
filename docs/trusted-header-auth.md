# trusted-header auth mode

## What it is

`REDMINE_AUTH_MODE=trusted-header` runs every request as the Redmine user that
an authenticating proxy in front of this server names in a request header. The
proxy, for example an SSO gateway or a reverse proxy that handles login, has
already authenticated the user. The server then calls Redmine with one
administrator API key plus `X-Redmine-Switch-User: <login>`, Redmine's built-in
user impersonation, so each request runs with that user's own permissions.

It needs no OAuth on Redmine and no API key from any user, and it works with
Redmine 4.0 or newer.

```mermaid
sequenceDiagram
    participant C as MCP client
    participant P as Authenticating proxy
    participant S as redmine-mcp-server
    participant R as Redmine

    C->>P: tool call
    P->>P: authenticate the user
    P->>S: tool call + X-Forwarded-User: jsmith + proxy secret
    S->>R: GET /users.json?name=jsmith (admin key), once per request
    R-->>S: 200 {users: [{login: jsmith, admin: false}]}
    S->>R: API calls with the admin key + X-Redmine-Switch-User: jsmith
    R-->>S: answers with jsmith's permissions
```

## When to use it

Use `trusted-header` when a proxy that already knows who the user is sits in
front of this server, for example a gateway that publishes several MCP servers
behind one login. Every user then gets the access they have in the Redmine web
interface, and nobody handles an API key.

If users connect to this server directly, use another mode: `oauth-proxy` on
Redmine 6.1 or newer, `api-key-login` otherwise.

## Configuration

Minimal `.env`:

```bash
REDMINE_AUTH_MODE=trusted-header
REDMINE_URL=https://redmine.example.com
REDMINE_API_KEY=<API key of a Redmine administrator>
REDMINE_TRUSTED_HEADER_TRUST_PROXY=true
REDMINE_TRUSTED_HEADER_SECRET=<32+ character random ASCII secret>
```

| Variable | Default | Notes |
|---|---|---|
| `REDMINE_AUTH_MODE=trusted-header` | `legacy` | activates the mode |
| `REDMINE_API_KEY` | required | the key of a Redmine administrator; see [The administrator key](#the-administrator-key) |
| `REDMINE_TRUSTED_HEADER_TRUST_PROXY` | `false` | required; operator attestation, see [Security requirements](#security-requirements) |
| `REDMINE_TRUSTED_HEADER_SECRET` | required | secret shared with the authenticating proxy: at least 32 printable ASCII characters, for example from `openssl rand -hex 32`; supports `_FILE` |
| `REDMINE_TRUSTED_HEADER_ALLOW_ADMIN` | `false` | allow requests targeting administrator accounts; see [The administrator key](#the-administrator-key) |
| `REDMINE_TRUSTED_HEADER_NAME` | `X-Forwarded-User` | the request header that names the user |
| `REDMINE_TRUSTED_HEADER_MATCH` | `login` | `login`: the header carries the Redmine login. `mail`: it carries an email address; see [Matching by email](#matching-by-email) |

The server refuses to start without `REDMINE_URL`, `REDMINE_API_KEY`, `REDMINE_TRUSTED_HEADER_SECRET`, or the
attestation flag, with an unknown `REDMINE_TRUSTED_HEADER_MATCH`, or unless
Redmine confirms at startup that the key belongs to an administrator. It does
not start while Redmine cannot be reached; with a container restart policy, it
comes up once Redmine answers.

Set `REDMINE_TEXT_FORMATTING` to the text formatting your Redmine uses.
Automatic detection does not run in this mode: it would call Redmine with the
administrator key and no user switch, which the server never does. Without the
setting, the model is told to write plain text.

## Security requirements

The server cannot tell a header the proxy set from one a client forged: anyone
who can send it a request can claim to be any Redmine user. Setting
`REDMINE_TRUSTED_HEADER_TRUST_PROXY=true` attests that:

- **only the proxy can reach the server.** Do not publish its port. Keep it on a
  network that only the proxy shares, or firewall it.
- **the proxy sets the header on every request**, overwriting any value a client
  sent on every route it forwards, including routes it doesn't authenticate.
- **the proxy sends the shared secret** in the `X-Trusted-Proxy-Secret` request
  header matching `REDMINE_TRUSTED_HEADER_SECRET`.
- **`PUBLIC_HOST` / `PUBLIC_PORT` must point at the proxy**, since `/files/` and
  `/uploads/` URLs now require the proxy secret as well.

A request without the header, or with a value that cannot be a Redmine login
(or an email address in `mail` mode), is refused. The server never runs a
request as the account that owns `REDMINE_API_KEY`.

## The administrator key

Redmine honours `X-Redmine-Switch-User` only when the API key belongs to an
administrator. For any other key it ignores the header without an error, and
the request runs as the key's own account. So:

- the server refuses to start unless Redmine confirms that the key belongs to
  an administrator;
- it looks up the target user with the administrator key once per request, so
  if the account loses that role while the server runs, requests fail instead
  of running with improper permissions.

The server **never** runs a request as the account that owns `REDMINE_API_KEY`,
whatever the flag says. It runs as other administrators only when
`REDMINE_TRUSTED_HEADER_ALLOW_ADMIN=true` is enabled.

Treat the key like a root password: whoever holds it can act as any Redmine
user. Use a dedicated administrator account for it: its owner can never use
the server, and Redmine's log lines `User switched by: <account>` then name the
server. The key is never logged.

## Matching by email

With `REDMINE_TRUSTED_HEADER_MATCH=mail`, the header carries an email address,
which is what most login proxies know. The once-per-request user lookup then
matches on it:

- the address must equal the **primary** email of an **active** Redmine user,
  ignoring case. Additional email addresses do not count;
- exactly one user must match, otherwise the request is refused.

This mode trusts the email addresses stored in Redmine. Redmine keeps them
unique, so nobody can claim an address another account already uses. But if
users can change their own email, someone could claim an address that is not in
Redmine yet, and requests from the person who owns it would run as that
account. Let administrators manage email addresses, or sync them from your
directory.

## Cutting off a user

- **In Redmine:** lock the account. Redmine refuses to switch to a locked user,
  so the user's requests fail at once.
- **At the proxy:** remove or disable the user in your identity provider, so the
  proxy stops forwarding their requests.

The server keeps no sessions or keys of its own, so it needs no action.

## Errors users may see

Each comes back with the code `PER_USER_AUTH`:

| Message | Cause |
|---|---|
| missing `<header>` request header | the request did not come through the proxy, or the proxy sets another header |
| repeated `<header>` request header | the proxy added its header instead of replacing the client's |
| the `<header>` header is not a valid Redmine login (or email address) | the value cannot name a Redmine user |
| no active Redmine user has the login ... (or email ...) | no active user matches the header |
| refusing to run request as administrator ... | the user is a Redmine administrator and `REDMINE_TRUSTED_HEADER_ALLOW_ADMIN` is off |
| refusing to run request as the account that owns REDMINE_API_KEY | the header names the key's own account |
| Redmine refused the user lookup ... | the key's account is no longer an administrator |
| that login does not exist in Redmine or the account is not active | Redmine refused the switch (HTTP 412), for example because the account was locked a moment earlier |

A request without the right proxy secret gets a bare `401 Unauthorized` before
any tool runs.

If Redmine cannot be reached, tools return the usual connection or timeout
error.

## Relationship to read-only mode

`REDMINE_MCP_READ_ONLY=true` works as in every mode: write tools are blocked for
everyone, whatever their Redmine permissions.

## Health check

`/health` checks the administrator key with `GET /users/current.json`, as in
legacy mode.

## Troubleshooting

See the [trusted-header section of the troubleshooting guide](troubleshooting.md#trusted-header).
