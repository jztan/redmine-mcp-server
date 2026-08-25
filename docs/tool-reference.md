# Tool Reference

Complete documentation for all available Redmine MCP Server tools.

## Security Best Practices

### SSL/TLS Configuration

The Redmine MCP Server supports comprehensive SSL/TLS configuration for secure connections to your Redmine instance.

**Recommended Practices:**

1. **Always Use HTTPS**
   ```bash
   # In .env file
   REDMINE_URL=https://redmine.company.com  # Use https://, not http://
   ```

2. **Enable SSL Verification (Default)**
   - SSL verification is enabled by default for security
   - Never disable in production environments
   - Only disable for development/testing when absolutely necessary

3. **Self-Signed Certificates**

   For Redmine servers with self-signed certificates or internal CA infrastructure:

   ```bash
   # In .env file
   REDMINE_SSL_CERT=/path/to/ca-certificate.crt
   ```

   **Security Considerations:**
   - Verify certificate authenticity before trusting
   - Obtain certificates from trusted administrators
   - Use absolute paths for certificate files
   - Ensure certificate files have appropriate permissions (644)

4. **Mutual TLS (Client Certificates)**

   For high-security environments requiring client certificate authentication:

   ```bash
   # In .env file
   REDMINE_SSL_CLIENT_CERT=/path/to/cert.pem,/path/to/key.pem
   ```

   **Security Considerations:**
   - Private keys MUST be unencrypted (Python requests library requirement)
   - Store private keys securely with restricted permissions (600)
   - Never commit certificates or keys to version control
   - Rotate client certificates regularly per security policy

5. **Development vs Production**

   ⚠️ **Development Only:**
   ```bash
   REDMINE_SSL_VERIFY=false  # WARNING: Only for development/testing!
   ```

   Disabling SSL verification makes your connection vulnerable to man-in-the-middle attacks. **Never use in production.**

### Authentication Best Practices

1. **API Key Authentication (Recommended)**

   Prefer API key authentication over username/password:

   ```bash
   # In .env file
   REDMINE_API_KEY=your_api_key_here
   ```

   **Benefits:**
   - More secure than password storage
   - Can be revoked without changing password
   - Granular access control
   - Better audit trail

2. **Username/Password Authentication**

   Only use when API key is not available:

   ```bash
   # In .env file
   REDMINE_USERNAME=your_username
   REDMINE_PASSWORD=your_password
   ```

   **Security Considerations:**
   - Never commit credentials to version control
   - Use strong, unique passwords
   - Rotate passwords regularly
   - Consider using API keys instead

3. **Credential Storage**

   - Store credentials in `.env` file (not in code)
   - Add `.env` to `.gitignore`
   - Use environment variables in production
   - Consider using secret management systems (e.g., HashiCorp Vault, AWS Secrets Manager)

### File Handling Security

The server implements multiple security layers for file operations:

1. **Server-Controlled Storage**
   - Attachment storage location controlled by server (`ATTACHMENTS_DIR`)
   - Clients cannot specify arbitrary file paths
   - Prevents directory traversal attacks

2. **UUID-Based File Storage**
   - Files stored with UUID-based names, not original filenames
   - Prevents path manipulation and collision attacks
   - Predictable cleanup and management

3. **Time-Limited Access**
   - Download URLs expire based on server configuration
   - Default expiry: 60 minutes (configurable via `ATTACHMENT_EXPIRES_MINUTES`)
   - Automatic cleanup of expired files

4. **Secure File Serving**
   - Metadata validation before file access
   - Expiry checks on every request
   - No directory listing or browsing

### Docker Deployment Security

When deploying with Docker, follow these additional practices:

1. **Certificate Management**
   ```yaml
   # In docker-compose.yml
   volumes:
     - ./certs:/certs:ro  # Read-only mount
   ```

2. **Environment Variable Security**
   - Use separate `.env.docker` file
   - Never include credentials in Dockerfile
   - Use Docker secrets for sensitive data in production

3. **Network Security**
   - Separate internal binding from external URLs
   - Use reverse proxy (nginx, traefik) for SSL termination
   - Restrict container network access

### Read-Only Mode

Block all write operations by setting the `REDMINE_MCP_READ_ONLY` environment variable:

```bash
# In .env file
REDMINE_MCP_READ_ONLY=true
```

When enabled, the following tools return an error instead of executing
(write actions only — read actions within the same tool still work):

**Fully blocked (all actions are writes):**
- `create_redmine_issue`
- `update_redmine_issue`
- `delete_redmine_issue`
- `copy_issue`
- `upload_file`
- `delete_file`
- `import_time_entries`
- `update_checklist_item` (also requires `REDMINE_CHECKLISTS_ENABLED=true`)
- `create_checklist_item` (also requires `REDMINE_CHECKLISTS_ENABLED=true`)
- `manage_project_member` — all actions
- `manage_issue_watcher` — all actions
- `manage_issue_note` — all actions
- `manage_time_entry` — all actions
- `manage_redmine_version` — all actions (`create`, `update`, `delete`)

**Partially blocked (read actions still work):**
- `manage_redmine_wiki_page` — `create`, `update`, `delete`, `rename` blocked; `list`, `get` allowed
- `manage_issue_category` — `create`, `update`, `delete` blocked; `list` allowed
- `manage_issue_relation` — `create`, `delete` blocked; `list` allowed
- `manage_product` — `create`, `update` blocked; `list`, `get` allowed (also requires `REDMINE_PRODUCTS_ENABLED=true`)
- `manage_contact` — `create`, `update`, `delete`, `assign_to_project`, `remove_from_project` blocked; `list`, `get` allowed (also requires `REDMINE_CRM_ENABLED=true`)
- `manage_deal` — `create`, `update`, `delete` blocked; `list`, `get` allowed (also requires `REDMINE_DEALS_ENABLED=true`)
- `manage_document` — `create`, `update` blocked; `list`, `get` allowed (also requires `REDMINE_DMSF_ENABLED=true`)

All read tools (`get_redmine_issue`, `list_redmine_issues`, `list_redmine_projects`, etc.) continue to work normally. The admin-gated `cleanup_attachment_files` tool (when registered via `REDMINE_MCP_EXPOSE_ADMIN_TOOLS=true`) is also unaffected — it performs local filesystem cleanup, not Redmine mutations.

### Prompt Injection Protection

All user-controlled content returned from Redmine (issue descriptions, journal notes, wiki page text, search excerpts, version descriptions) is automatically wrapped in unique boundary tags:

```
<insecure-content-a1b2c3d4e5f67890>
User-controlled content here...
</insecure-content-a1b2c3d4e5f67890>
```

This allows LLM consumers to distinguish trusted tool output from untrusted user data, preventing prompt injection attacks via Redmine content. Empty strings and non-string values are returned unchanged.

### Additional Resources

- [SSL Certificate Configuration](../README.md#ssl-certificate-configuration) - Detailed configuration examples
- [Troubleshooting Guide - SSL Errors](./troubleshooting.md#ssl-certificate-errors) - Common SSL issues and solutions
- [Environment Variables](../README.md#environment-variables) - Complete configuration reference

---

## Project Management

### `list_redmine_projects`

Lists accessible projects in the Redmine instance, optionally narrowed server-side.

**Returns only *active* projects unless `filters` says otherwise.** Redmine's `ProjectQuery` starts with a `status = 1` filter already set (`self.filters ||= {'status' => {:operator => "=", :values => ['1']}}`), so a call passing no `status` answers with active projects alone while looking like the whole list. Pass `filters={"status": "1|5"}` for closed projects alongside active ones. This tool keeps Redmine's own default deliberately rather than overriding it. Only `1` (active) and `5` (closed) are reachable: archived and scheduled-for-deletion come from `ProjectAdminQuery`, which this endpoint does not use, and `status` is a `:list` filter taking only `=` and `!`, so `"*"` is read as a literal value and matches nothing.

**Parameters:**
- `include_custom_fields` (boolean, optional): Add `custom_fields` to each project. Default: `false`
- `limit` (integer, optional): Maximum number of projects to return, `1`–`1000`. Omitted by default, which returns every visible project -- and at `offset=0` omitting it is also the cheapest way to do that. With no limit python-redmine reads the collection's `total_count` and stops there; a supplied limit is paged in full regardless of how many projects exist, so `limit=1000` against an instance holding seven costs ten requests and returns the same seven. Ask for a number you want, not a large one meaning "all"
- `offset` (integer, optional): Projects to skip before collecting results. Default: `0`. With no `limit`, a non-zero offset costs exactly what reading from zero costs: `bulk_request` resolves the missing limit to the collection's `total_count` and then pages that many rows *from* `offset` rather than up to the end, so the requests past the end are still issued and come back empty. Measured against 250 projects: `offset=240` is three requests to return ten rows, and `offset=300` is three requests to return none. Pair a large `offset` with a `limit`, which is one request
- `include_pagination_info` (boolean, optional): Return `{"projects": [...], "pagination": {...}}` instead of a bare array. Default: `false`. The same envelope and keys as [`list_redmine_issues`](#list_redmine_issues) -- `total`, `limit`, `offset`, `count`, `has_next`, `has_previous`, `next_offset`, `previous_offset`. `total` is read off the same response the rows came from, so it costs no extra request, and it is reported for every read Redmine measures: `@project_count` comes from `@query.result_count`, the same query as the rows, so a filter narrows the count along with the collection. One deployment shape defeats it: with API metadata suppressed (`nometa` or `X-Redmine-Nometa`) the response carries no `total_count`, python-redmine stops after one page and reports that page's length, so a truncated list arrives with a `total` that agrees with it and `has_next` false. A client cannot tell that from a genuinely small instance
- `filters` (object, optional): Redmine query filters to narrow the list, for the filters this signature does not name -- e.g. `{"cf_42": "Gold"}`. Accepted keys and value types are listed below

**Returns:** List of project dictionaries carrying `id`, `name`, `identifier`, `description`, `homepage`, `parent`, `status`, `is_public`, `inherit_members`, `created_on` and `updated_on` -- what Redmine's project index renders -- plus `custom_fields` when requested. With `include_pagination_info=true`, `{"projects": [...], "pagination": {...}}` instead.

`status` is Redmine's integer code (`1` active, `5` closed). `parent` is `{id, name}` or `null`; Redmine renders it only when the parent exists **and** is visible to the caller, so `null` means top-level **or** a parent this caller cannot see, and the two cannot be told apart. A key the payload did not carry is `null` rather than a substituted default -- for `is_public` and `inherit_members` especially, a `false` would read as a setting Redmine never sent.

**Example:**
```json
[
  {
    "id": 1,
    "name": "My Project",
    "identifier": "my-project",
    "description": "Project description",
    "homepage": "https://example.com",
    "parent": {"id": 7, "name": "Umbrella"},
    "status": 1,
    "is_public": true,
    "inherit_members": false,
    "created_on": "2025-01-15T10:30:00",
    "updated_on": "2025-03-20T09:15:00"
  }
]
```

**Example with `include_custom_fields=True`:** each entry also carries
```json
    "custom_fields": [
      {"id": 12, "name": "Size", "value": "S"}
    ]
```

**Example with `include_pagination_info=True`:**
```json
{
  "projects": [ ... ],
  "pagination": {
    "total": 250,
    "limit": 100,
    "offset": 0,
    "count": 100,
    "has_next": true,
    "has_previous": false,
    "next_offset": 100,
    "previous_offset": null
  }
}
```

With no `limit` there is no page size, so the envelope describes one complete read: `has_next` is `false`, `next_offset` is `null`, and `previous_offset` points back at the start of the collection rather than at the offset the caller is already on.

**Project custom field values:** Redmine renders them on `GET /projects.json`
unconditionally, so `include_custom_fields=True` adds them with no per-project
follow-up request. Requires only `view_project`. Each entry is
`{id, name, value}`, already limited by Redmine to the fields the caller may
see. This is the only tool that returns project custom field *values*. Project
custom fields and issue custom fields are separate in Redmine:
[`list_project_issue_custom_fields`](#list_project_issue_custom_fields) covers
the latter, and no tool exposes project custom field definitions.

**Narrowing the list (`filters`):** `GET /projects.json` runs the request
through Redmine's `ProjectQuery`, so a filter can be applied server-side
instead of fetching every project and filtering locally:

```python
list_redmine_projects(filters={"cf_42": "Gold"}, include_custom_fields=True)
```

**Accepted keys.** `filters` takes the filters `ProjectQuery` registers and
nothing else:

| Key | Notes |
| --- | --- |
| `status` | Only the `=` and `!` operators; `*` is not one of them |
| `id` | |
| `name` | |
| `description` | |
| `parent_id` | |
| `is_public` | `"1"` or `"0"` |
| `created_on` | |
| `updated_on` | Registered on 6.1; absent on some older versions |
| `cf_<id>` | A project custom field, visible to the caller and flagged **Used as a filter** |
| `cf_<id>.cf_<id>`, `cf_<id>.due_date`, `cf_<id>.status` | The chained filters Redmine registers for a custom field whose format targets another record |

Any other key is refused with an error naming that set, rather than being
forwarded. This is an allowlist because the two directions are not symmetric:
Redmine builds its query from the filter parameters it registers and ignores
every other one, so refusing an unregistered key costs a caller nothing it
could have used -- while a parameter that is not a filter at all can still be
read by another part of the same request instead of being ignored. `fields`,
`f` and `query_id` are called out separately in the error, since Redmine reads
the first two as the query's own filter definition and empties the filters
built from the rest of the request, and `query_id` selects a saved query
instead. `limit` and `offset` are refused inside `filters` too -- pass them as
the named parameters, which validate them.

**Accepted values.** Each value must be a single scalar: a string, integer,
float, `date` or `datetime`. Lists, dicts and `None` are refused, and so is a
Python `bool` -- it urlencodes as `True`, while a yes/no filter's values are
`"1"` and `"0"`, so it would be accepted and then match nothing. Write
`{"is_public": "1"}`. A filter's operator travels inside the value as a prefix
Redmine strips off, and alternatives are joined with `|`, so a scalar is all a
filter ever needs:

```python
list_redmine_projects(filters={"created_on": ">=2024-01-01", "name": "~api"})
```

Two more things to know before relying on `filters`:

- Redmine ignores an unregistered filter parameter without erroring, answering
  `200` with the unfiltered collection -- which looks identical to a filter that
  matched everything. Confirm a narrow filter actually narrowed. A project
  custom field that is not marked "Used as a filter" is exactly this case, and
  project custom fields are a different set from issue custom fields, so the id
  has to come from a project one.
- The query defaults to `status = 1` (active), so this tool returns **only
  active projects** unless `filters` says otherwise. Pass `{"status": "1|5"}`
  to get closed projects alongside active ones.

**Pagination:** omitting `limit` returns every visible project, unchanged from
before these parameters existed. `limit` is not capped at Redmine's 100-per-request
ceiling, because python-redmine pages past it internally; `limit=250` issues as
many requests as it needs.

---

### `list_project_issue_custom_fields`

List the ids and names of the issue custom fields enabled for a project.

**OAuth scopes:** `view_project`, for `projects#show`, and nothing beyond it. Every released Redmine renders the `issue_custom_fields` include gated on `include_in_api_response?` alone, with no permission check, so requiring anything further would refuse calls Redmine itself serves. `view_project` being a `:public => true` permission is not an exemption -- `Role#allowed_permissions` intersects the public permissions with the token's scopes too, so a token carrying no scopes is still refused.

**Parameters:**
- `project_id` (integer or string, required): Project ID (numeric) or identifier (string)
- `tracker_id` (integer, optional): Restrict output to fields applicable to the given tracker ID. Requires readable tracker bindings, which stock Redmine does not provide -- see below

**Returns:** List of custom field metadata dictionaries

**Example (stock Redmine):**
```json
[
  {
    "id": 6,
    "name": "Size",
    "field_format": null,
    "is_required": null,
    "multiple": null,
    "default_value": null,
    "possible_values": null,
    "trackers": null
  }
]
```

**⚠️ `null` means "not readable on this token", never a default.** This tool reads `GET /projects/{id}.json?include=issue_custom_fields`, which Redmine renders as exactly `id` and `name` per field (`app/helpers/projects_helper.rb`, the same two keys in 6.1, 7.0 and trunk). The definitions live on `GET /custom_fields.json`, which Redmine restricts to administrators (`before_action :require_admin`), so a non-admin token cannot read them at all. Under OAuth even an administrator's token cannot: `User#admin?` additionally requires the `admin` scope, which this server never requests. Redmine has four open requests to expose this metadata to non-admins ([#18875](https://www.redmine.org/issues/18875), [#41318](https://www.redmine.org/issues/41318), [#42581](https://www.redmine.org/issues/42581), [#43407](https://www.redmine.org/issues/43407)), none with a target version.

Read `null` as "unknown". It is not `false`, and it is not an empty list. `is_required: null` in particular does not mean the field is optional.

The keys are kept rather than dropped so the response shape is stable across deployments, and so they start carrying data for free if a future Redmine populates the include.

**Example with tracker filter:**
```python
list_project_issue_custom_fields(project_id="pipeline", tracker_id=5)
```

Against a stock Redmine this returns an `error` with `code: "TRACKER_BINDINGS_UNREADABLE"` and a `hint`, because tracker bindings are part of the admin-only definition and the filter cannot be applied. It previously returned every field in the project, which a caller had no way to distinguish from a filtered list. Omit `tracker_id` to list every field enabled for the project.

The `error` describes what this particular response carried rather than asserting what Redmine always does, since bindings *are* readable on a payload that includes them; the standing Redmine explanation is in the `hint`.

**⚠️ `is_required` caveat (#119):** even where the flag *is* readable it only reflects the custom field *definition*. Workflow rules, role-based field permissions, and tracker-bound required-field settings can still cause `create_redmine_issue` / `update_redmine_issue` to reject with `"<field> cannot be blank"` for a field that this tool returns with `is_required: false`. No general-purpose Redmine API exposes the "effective" required state.

When a create or update rejects with that error, the response envelope is augmented with `missing_required_fields` (parsed names) and a `hint` that lists the three recovery paths:

1. **Name-keyed shortcut** — pass the rejected field by name directly: `fields={"Department": "Engineering"}` on either `create_redmine_issue` or `update_redmine_issue`. The tool resolves the name to a `custom_fields` id automatically. Ambiguous names (two fields normalized identically) raise.
2. **Explicit id form** — `extra_fields={"custom_fields": [{"id": N, "value": "..."}]}` with `N` from this tool. Use when the name is ambiguous or the value type is awkward (multi-value, complex serializations).
3. **Autofill** -- set `REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS=true` to have the server retry once with values from each field's `default_value` or the `REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS` env map. Against a stock Redmine only the env map can supply a value: `default_value` is not in the include the server reads.

---

### `summarize_project_status`

Provide a comprehensive summary of project status based on issue activity over a specified time period.

**Parameters:**
- `project_id` (integer, required): The ID of the project to summarize
- `days` (integer, optional): Number of days to analyze. Default: `30`

**Returns:** Comprehensive project status summary including:
- Recent activity metrics (issues created/updated)
- Status, priority, and assignee breakdowns
- Project totals and overall statistics
- Activity insights and trends

**Example:**
```json
{
  "project_id": 1,
  "project_name": "My Project",
  "analysis_period_days": 30,
  "recent_activity": {
    "created_count": 15,
    "updated_count": 42
  },
  "status_breakdown": {
    "New": 5,
    "In Progress": 8,
    "Resolved": 12
  }
}
```

---

### `list_redmine_versions`

List versions (roadmap milestones) for a Redmine project. Useful for discovering target version IDs to use with `list_redmine_issues(fixed_version_id=...)`.

**Parameters:**
- `project_id` (integer or string, required): The project ID (numeric) or identifier (string)
- `status_filter` (string, optional): Filter by version status. Allowed values: `open`, `locked`, `closed`. Default: all versions

**Returns:** List of version dictionaries

**Example:**
```json
[
  {
    "id": 1,
    "name": "v1.0",
    "description": "First release",
    "status": "open",
    "due_date": "2026-03-01",
    "sharing": "none",
    "wiki_page_title": "",
    "project": {"id": 1, "name": "My Project"},
    "created_on": "2026-01-01T10:00:00",
    "updated_on": "2026-02-01T14:30:00"
  }
]
```

**Usage with issue filtering:**
```python
# First, find versions for a project
versions = list_redmine_versions(project_id="my-project", status_filter="open")
# Then, list issues assigned to that version
issues = list_redmine_issues(fixed_version_id=versions[0]["id"])
```

---

### `manage_redmine_version`

Create, update, or delete a Redmine version (roadmap milestone).

**Parameters:**
- `action` (string, required): Operation to perform. Allowed values: `create`, `update`, `delete`
- `project_id` (integer or string): Project ID or identifier. Required for `action="create"`
- `version_id` (integer): Version ID. Required for `action="update"` and `action="delete"`
- `name` (string): Version name. Required for `action="create"`, optional for `action="update"`
- `description` (string, optional): Version description
- `status` (string, optional): Version status. Allowed values: `open`, `locked`, `closed`. Defaults to `open` on create
- `due_date` (string, optional): Due date in `YYYY-MM-DD` format
- `sharing` (string, optional): Sharing scope. Allowed values: `none`, `descendants`, `hierarchy`, `tree`, `system`. Defaults to `none` on create
- `wiki_page_title` (string, optional): Associated wiki page title

**Returns:**
- `create`/`update`: full version dictionary (same shape as `list_redmine_versions` entries)
- `delete`: `{"success": true, "version_id": ..., "message": "Version deleted successfully."}`
- Error: `{"error": "..."}`

**Examples:**

```python
# Create a new version
manage_redmine_version(
    action="create",
    project_id="my-project",
    name="v2.0",
    description="Second major release",
    status="open",
    due_date="2026-09-01",
)

# Update version status to locked
manage_redmine_version(
    action="update",
    version_id=42,
    status="locked",
)

# Delete a version
manage_redmine_version(
    action="delete",
    version_id=42,
)
```

---

### `list_project_members`

List all members (users and groups) of a Redmine project along with their assigned roles.

**Parameters:**
- `project_id` (integer or string, required): Project ID (numeric) or identifier (string)

**Returns:** List of membership dictionaries containing user/group info and roles

**Example:**
```json
[
  {
    "id": 1,
    "user": {"id": 5, "name": "John Doe"},
    "group": null,
    "project": {"id": 10, "name": "My Project"},
    "roles": [{"id": 3, "name": "Developer"}]
  },
  {
    "id": 2,
    "user": null,
    "group": {"id": 15, "name": "Dev Team"},
    "project": {"id": 10, "name": "My Project"},
    "roles": [{"id": 4, "name": "Manager"}]
  }
]
```

**Usage:**
```python
# List members by project ID
members = list_project_members(project_id=10)

# List members by project identifier
members = list_project_members(project_id="my-project")

# Get all developers in a project
devs = [m for m in members if any(r["name"] == "Developer" for r in m["roles"])]
```

---

### `list_redmine_roles`

List all roles defined in the Redmine instance. Returns basic metadata (`id` and `name`) for each role.

**Parameters:** None.

**Returns:** List of role dictionaries with `id` and `name`.

**Example:**
```json
[
  {"id": 3, "name": "Manager"},
  {"id": 4, "name": "Developer"},
  {"id": 5, "name": "Reporter"}
]
```

**When to use:** Call this **before** `manage_project_member(action="add"|"update")` to discover the correct `role_ids`. Role IDs vary between Redmine instances and must not be guessed — calling `manage_project_member` with a non-existent role ID returns a validation error from Redmine.

---

### `get_project_modules`

Retrieve the list of enabled modules for a project (e.g., `issue_tracking`, `time_tracking`, `wiki`, `repository`).

**Parameters:**
- `project_id` (integer or string, required): Project identifier (numeric ID or string identifier).

**Returns:** Dictionary with `project_id`, `project_name`, and `enabled_modules` (list of module name strings).

**Example:**
```json
{
  "project_id": 1,
  "project_name": "My Project",
  "enabled_modules": ["issue_tracking", "time_tracking", "wiki"]
}
```

**Notes:**
- Common module names: `issue_tracking`, `time_tracking`, `news`, `documents`, `files`, `wiki`, `repository`, `boards`, `calendar`, `gantt`.
- Plugins (Agile, CRM, etc.) may register additional modules; any plugin-provided module names are returned as-is.

---

### `manage_project_member`

Add, update, or remove a Redmine project membership.

**Parameters:**
- `action` (string, required): Operation to perform. Allowed: `add`, `update`, `remove`
- `project_id` (integer or string): Project identifier. Required for `action="add"`
- `membership_id` (integer): Membership ID. Required for `action="update"` and `action="remove"`
- `user_id` (integer): ID of the user. Exactly one of `user_id` or `group_id` required for `action="add"`
- `group_id` (integer): ID of the group. Exactly one of `user_id` or `group_id` required for `action="add"`
- `role_ids` (array of integers): Non-empty list of role IDs. Required for `action="add"` and `action="update"`. Use `list_redmine_roles` to discover valid IDs

**Returns:**
- `add`/`update`: membership dictionary (with `id`, `user`/`group`, `project`, `roles`)
- `remove`: `{"success": true, "deleted_membership_id": <id>}`
- Error: `{"error": "..."}`

**Examples:**

```python
# Add a user as Developer
manage_project_member(action="add", project_id="my-project", user_id=5, role_ids=[3])

# Add a group with multiple roles
manage_project_member(action="add", project_id=10, group_id=20, role_ids=[3, 4])

# Update an existing membership's roles
manage_project_member(action="update", membership_id=42, role_ids=[3, 4])

# Remove a membership
manage_project_member(action="remove", membership_id=42)
```

**Notes:**
- All actions are write operations and respect `REDMINE_MCP_READ_ONLY`.
- Inherited memberships (from a parent project) cannot be removed directly — Redmine returns a 422. Remove them from the parent project instead.
- Redmine's API uses the `user_id` field for both users and groups; the tool routes `group_id` through that field automatically.

---

## Issue Operations

### `get_redmine_issue`

Retrieve detailed information about a specific Redmine issue.

**Parameters:**
- `issue_id` (integer, required): The ID of the issue to retrieve
- `include_journals` (boolean, optional): Include journals (comments) in result. Default: `true`
- `include_attachments` (boolean, optional): Include attachments metadata. Default: `true`
- `include_custom_fields` (boolean, optional): Include custom fields in result. Default: `true`
- `journal_limit` (integer, optional): Maximum number of journals to return. When set, enables journal pagination and adds `journal_pagination` metadata. Default: `null` (all journals)
- `journal_offset` (integer, optional): Number of journals to skip (used with `journal_limit`). Default: `0`
- `include_watchers` (boolean, optional): Include watcher list. Default: `false`
- `include_relations` (boolean, optional): Include issue relations. Default: `false`. Requires only `view_issues`. Each entry is `{id, issue_id, issue_to_id, relation_type, delay}`.
- `include_children` (boolean, optional): Include child issues. Default: `false`


**Returns:** Issue dictionary with details, journals, and attachments. Standard fields include `category`, `fixed_version` (target version), and `parent` (each `{id, ...}` or `None`), plus `start_date`, `due_date`, `closed_on` (ISO-8601 or `None`), `done_ratio`, `estimated_hours`, `spent_hours`, and `is_private`. Each is `None` when not set on the issue. When `REDMINE_AGILE_ENABLED=true`, also includes `story_points`, `agile_sprint_id`, and `agile_position` from the RedmineUP Agile plugin.

**Attachment URLs (#110, #118):** each entry under `attachments` carries the canonical shape `{id, filename, filesize, content_type, description, content_url, author, created_on}` — identical to what `manage_redmine_wiki_page(action="get", include_attachments=True)` returns. When `REDMINE_PUBLIC_URL` is set, any `content_url` whose scheme+host+port matches `REDMINE_URL`'s origin is rewritten to use the public origin (preserving path, query, fragment, and any reverse-proxy subpath). When unset, the raw URL Redmine echoes back is returned — callers can fall back to [`get_redmine_attachment`](#get_redmine_attachment) for a sandbox-safe download URL via the MCP server's proxy.

**Example:**
```json
{
  "id": 123,
  "subject": "Bug in login form",
  "description": "<insecure-content-...>\nUsers cannot login...\n</insecure-content-...>",
  "status": {"id": 1, "name": "New"},
  "priority": {"id": 2, "name": "Normal"},
  "category": {"id": 5, "name": "Backend"},
  "fixed_version": {"id": 6, "name": "v2.0"},
  "parent": {"id": 100},
  "start_date": "2026-01-10",
  "due_date": "2026-01-20",
  "closed_on": null,
  "done_ratio": 40,
  "estimated_hours": 8.0,
  "spent_hours": 3.5,
  "is_private": false,
  "custom_fields": [{"id": 6, "name": "Size", "value": "S"}],
  "journals": [...],
  "attachments": [...]
}
```

**With `REDMINE_AGILE_ENABLED=true`:**
```json
{
  "id": 123,
  "subject": "Bug in login form",
  "story_points": 5,
  "agile_sprint_id": null,
  "agile_position": 2,
  ...
}
```

**With `REDMINE_TAGS_ENABLED=true`:**
```json
{
  "id": 123,
  "subject": "Bug in login form",
  "tags": [{"id": 3, "name": "fast-track"}, {"id": null, "name": "backend"}],
  ...
}
```

**Journal pagination:**
```python
get_redmine_issue(123, journal_limit=5, journal_offset=10)
# Returns:
# {
#   ...
#   "journals": [...],  # 5 journals starting from position 10
#   "journal_pagination": {
#     "total": 42,
#     "offset": 10,
#     "limit": 5,
#     "count": 5,
#     "has_more": true
#   }
# }
```

**Include watchers, relations, and children:**
```python
get_redmine_issue(
    123,
    include_watchers=True,
    include_relations=True,
    include_children=True
)
# Returns:
# {
#   ...
#   "watchers": [{"id": 10, "name": "Alice"}, {"id": 11, "name": "Bob"}],
#   "relations": [{"id": 5, "issue_id": 123, "issue_to_id": 456, "relation_type": "relates"}],
#   "children": [{"id": 200, "subject": "Sub-task", "tracker": {"id": 1, "name": "Bug"}}]
# }
```

**Notes:**
- User-controlled content (`description`, journal `notes`) is wrapped in `<insecure-content-{boundary}>` boundary tags to prevent prompt injection
- Journal pagination metadata is only included when `journal_limit` is set
- Watchers, relations, and children default to `false` for backward compatibility

---

### `list_redmine_issues`

List Redmine issues with flexible filtering and pagination support. A general-purpose tool for listing issues from Redmine. Supports filtering by project, status, assignee, tracker, priority, and any other Redmine issue filter.

**Parameters:**
- `project_id` (integer or string, optional): Filter by project (numeric ID or string identifier)
- `status_id` (integer, optional): Filter by status ID
- `tracker_id` (integer, optional): Filter by tracker ID
- `assigned_to_id` (integer or string, optional): Filter by assignee. Use a numeric user ID or the special value `'me'` to retrieve issues assigned to the currently authenticated user. Note that `'me'` resolves to the owner of the configured `REDMINE_API_KEY`, which may be a shared or robot account rather than the human operator. If results come back unexpectedly empty, call [`get_mcp_server_info`](#get_mcp_server_info) to confirm who `'me'` maps to.
- `priority_id` (integer, optional): Filter by priority ID
- `fixed_version_id` (integer, optional): Filter by target version/milestone ID
- `sort` (string, optional): Sort order (e.g., `"updated_on:desc"`)
- `limit` (integer, optional): Maximum issues to return. Default: `25`, Max: `1000`
- `offset` (integer, optional): Number of issues to skip for pagination. Default: `0`
- `include_pagination_info` (boolean, optional): Return structured response with metadata. Default: `false`. `total` is Redmine's `total_count`, read off the same response the issues came from, so it costs no extra request, and `has_next` is measured from it (`offset + limit < total`) rather than inferred from a full page. When the response carries no usable total (API metadata suppressed via `nometa` or `X-Redmine-Nometa`), `total` is `null`, never an estimate, and `has_next` falls back to the full-page inference
- `include_custom_fields` (boolean, optional): Add `custom_fields` to each issue. Default: `false` — unlike `get_redmine_issue`, which defaults to `true`, because a list page multiplies the payload
- `include_relations` (boolean, optional): Add `relations` to each issue. Default: `false`. Each entry is `{id, issue_id, issue_to_id, relation_type, delay}`
- `fields` (array of strings, optional): List of field names to include in results. Default: all fields
  - Available fields: `id`, `subject`, `description`, `project`, `status`, `priority`, `tracker`, `author`, `assigned_to`, `category`, `fixed_version`, `parent`, `start_date`, `due_date`, `done_ratio`, `estimated_hours`, `spent_hours`, `is_private`, `closed_on`, `created_on`, `updated_on`, `custom_fields`, `relations` — `tracker` is returned by default
  - Special values: `["*"]` or `["all"]`, on their own, select every field except `custom_fields` and `relations`. Those two need their flag — naming one alongside `["*"]` narrows the result to just it, rather than adding it to the full set
  - Naming `custom_fields` or `relations` in a normal field list does the same as the matching flag. For `relations` that includes adding the include to the request, so the key cannot come back empty just because the flag was not also set. Setting a flag also adds its key to a narrowed `fields` list rather than dropping it.

**Returns:** List of issue dictionaries, or structured response with pagination metadata

**Notes on `custom_fields` and `relations`:**
- Both come from data Redmine already returns on the list endpoint, so a whole page costs one request either way. Custom field values are rendered unconditionally; relations are read from the `include=relations` payload, so `view_issues` is sufficient and no per-issue call is made.
- An `include` passed through `filters` is kept and merged. Passing `include=relations` that way alone does not add the key — use the flag or name the field.
- They are opt-in only to keep the default response small. The default output is unchanged.
- Custom field values are filtered per caller by Redmine (`Issue#visible_custom_field_values`). **Relations on the list endpoint are not:** Redmine applies the target-issue visibility filter on `GET /issues/{id}` but not on `GET /issues.json`, so `issue_to_id` may name an issue the caller cannot read. Resolve a target through `get_redmine_issue`, which does apply the filter, rather than inferring anything from the id alone.
- `search_redmine_issues` shares this serializer and can select `custom_fields` the same way, but not `relations` — it never requests the include, so the key could only ever be empty there.

```python
# One request, not one per issue.
list_redmine_issues(
    project_id="my-project",
    fields=["id", "subject", "custom_fields", "relations"],
    include_relations=True,
    limit=100,
)
```

**Examples:**

List all issues in a project:
```python
list_redmine_issues(project_id="my-project")
```

Filter by multiple criteria:
```python
list_redmine_issues(
    project_id=1,
    status_id=1,
    assigned_to_id="me",
    sort="updated_on:desc"
)
```

With pagination metadata:
```python
list_redmine_issues(
    project_id=1,
    limit=25,
    offset=50,
    include_pagination_info=True
)
# Returns:
# {
#   "issues": [...],
#   "pagination": {
#     "total": 150,
#     "limit": 25,
#     "offset": 50,
#     "has_next": true,
#     "has_previous": true,
#     "next_offset": 75,
#     "previous_offset": 25
#   }
# }
```

With field selection (reduces token usage):
```python
list_redmine_issues(
    project_id=1,
    fields=["id", "subject", "status"]
)
# Returns: [{"id": 1, "subject": "Bug fix", "status": {...}}, ...]
```

---

### `search_redmine_issues`

Search issues using text queries with support for pagination, field selection, and native Search API filters.

**Parameters:**
- `query` (string, required): Text to search for in issues
- `limit` (integer, optional): Maximum number of issues to return. Default: `25`, Max: `1000`
- `offset` (integer, optional): Number of issues to skip for pagination. Default: `0`
- `include_pagination_info` (boolean, optional): Return structured response with pagination metadata. Default: `false`. The Search API reports no `total_count`, so `total` is always `null` ("not reported") and `has_next` uses the full-page inference: `true` whenever the page came back full, which is only ever optimistic and costs one wasted request at worst
- `fields` (array of strings, optional): List of field names to include in results. Default: `null` (all fields)
  - Available fields: `id`, `subject`, `description`, `project`, `status`, `priority`, `tracker`, `author`, `assigned_to`, `created_on`, `updated_on`, `custom_fields` — `tracker` is returned by default. Naming `custom_fields` hydrates the results through the issues endpoint, which renders the values; there is no `relations` here, since this tool never requests that include
  - Special values: `["*"]` or `["all"]` for all fields
- `scope` (string, optional): Search scope. Default: `"all"`
  - Values: `"all"`, `"my_project"`, `"subprojects"`
- `open_issues` (boolean, optional): Search only open issues. Default: `false`

**Returns:**
- By default: List of issue dictionaries
- With `include_pagination_info=true`: Dictionary with `issues` and `pagination` keys

**When to Use:**
- **Use `search_redmine_issues()`** for text-based searches across issues
- **Use `list_redmine_issues()`** for advanced filtering by project_id, status_id, priority_id, etc.

**Search API Limitations:**
The Search API supports text search with `scope` and `open_issues` filters only. For advanced filtering by specific field values (project_id, status_id, priority_id, etc.), use `list_redmine_issues()` instead.

**Examples:**

Basic search:
```python
search_redmine_issues("bug fix")
```

With pagination:
```python
# First page
search_redmine_issues("performance", limit=10, offset=0)

# Second page
search_redmine_issues("performance", limit=10, offset=10)
```

With pagination metadata:
```python
search_redmine_issues(
    "security",
    limit=25,
    offset=0,
    include_pagination_info=True
)
# Returns:
# {
#   "issues": [...],
#   "pagination": {
#     "total": null,
#     "limit": 25,
#     "offset": 0,
#     "count": 25,
#     "has_next": true,
#     "has_previous": false,
#     "next_offset": 25,
#     "previous_offset": null
#   }
# }
```

With field selection (token reduction):
```python
# Minimal fields for better performance
search_redmine_issues("urgent", fields=["id", "subject", "status"])
```

With native filters:
```python
# Search only in my projects for open issues
search_redmine_issues(
    "bug",
    scope="my_project",
    open_issues=True
)
```

All features combined:
```python
search_redmine_issues(
    "critical",
    scope="my_project",
    open_issues=True,
    limit=10,
    offset=0,
    fields=["id", "subject", "priority", "status"],
    include_pagination_info=True
)
```

**Performance Tips:**
- Use pagination (default limit: 25) to prevent token overflow
- Use field selection to minimize data transfer and token usage
- Combine pagination + field selection for optimal performance
- Token reduction: ~95% fewer tokens with minimal fields vs all fields

---

### `create_redmine_issue`

Creates a new issue in the specified project. Blocked when `REDMINE_MCP_READ_ONLY=true`.

**Parameters:**
- `project_id` (integer, required): Target project ID
- `subject` (string, required): Issue subject/title
- `description` (string, optional): Issue description. Default: `""`
- `fields` (object|string, optional): Additional Redmine fields as:
  - an object (`{"priority_id": 3, "tracker_id": 1}`), or
  - a serialized JSON object string (for MCP clients that pass string payloads)
- `extra_fields` (object|string, optional): Additional Redmine fields as:
  - an object (`{"priority_id": 3, "tracker_id": 1}`), or
  - a serialized JSON object string
- `uploads` (list, optional): Files to attach to the issue. Maximum 10 items. Each item is an object with:
  - Exactly ONE source key:
    - `content_base64` (string): Raw file bytes encoded as base64. `filename` is required when using this source.
    - `source_url` (string): HTTP(S) URL the server fetches. Filename is derived from the URL or `Content-Disposition` if omitted.
    - `file_path` (string): Absolute path to a file already on the server. Must be inside `ATTACHMENTS_DIR` or a directory listed in `REDMINE_MCP_UPLOAD_FILE_ROOTS`. Filename is derived from the path if omitted.
  - `filename` (string, optional): Name the attachment will have in Redmine. Required for `content_base64`; derived for other sources when omitted.
  - `content_type` (string, optional): MIME type override (e.g. `"application/pdf"`).
  - `description` (string, optional): Human-readable description for the attachment.

**Returns:** Created issue dictionary. When `uploads` is provided and at least one attachment succeeds, the response includes:
- `attachments` (list): Metadata for each attached file (id, filename, filesize, content_url, etc.).
- `journal_id` (integer or null): ID of the journal entry the attachments were placed on, or null when no journal note accompanies the upload (i.e. when no `notes` is provided).

**Name-keyed custom fields (#123):** `fields` accepts custom-field *names* directly. The tool resolves the name to a `custom_fields` entry via `list_project_issue_custom_fields` and rewrites the payload before sending it to Redmine. Ambiguous names (two custom fields that normalize to the same name) raise with an explicit error pointing at the id form.

```python
# Name-keyed -- the tool resolves "Department" to its custom_field id
create_redmine_issue(
    project_id=1,
    subject="...",
    fields={"Department": "Engineering"},
)

# Explicit id form -- use when names collide or value types are awkward
create_redmine_issue(
    project_id=1,
    subject="...",
    extra_fields={"custom_fields": [{"id": 2, "value": "Engineering"}]},
)
```

**Validation-error envelope (#119):** when Redmine rejects with `"<field> cannot be blank"` / `"is not included in the list"` / `"is invalid"`, the returned envelope includes:

- `missing_required_fields` (list of parsed field names)
- `hint` — a tailored recovery message that branches on whether the missing fields look like standard Redmine fields (Subject / Priority / Tracker / etc.) or custom fields, calling out the `is_required` caveat for the latter (see [`list_project_issue_custom_fields`](#list_project_issue_custom_fields) for the underlying limitation).

**Tags (`REDMINE_TAGS_ENABLED=true`):** pass a `tag_list` in `fields` to tag the new issue via the AlphaNodes additional_tags plugin — a list of names (`["fast-track", "backend"]`) or a comma-separated string (`"fast-track, backend"`). It is extracted before custom-field resolution (so it never collides with a same-named custom field) and requires `create_issue_tags` (to mint new tag names) or `edit_issue_tags` (existing tags only). Silently ignored when the flag is off.

```python
# Requires REDMINE_TAGS_ENABLED=true
create_redmine_issue(
    project_id=1,
    subject="...",
    fields={"tag_list": ["fast-track", "backend"]},
)
```

**Autofill retry:** if `REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS=true` is set and Redmine returns relevant custom-field validation errors, the server fetches project custom fields, auto-fills missing/invalid required custom fields from Redmine `default_value` or `REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS`, and retries once. The `default_value` half is inert against a stock Redmine, which does not send it on the include the server reads.

**Examples:**
```python
# Create a bug report
create_redmine_issue(
    project_id=1,
    subject="Login button not working",
    description="The login button does not respond to clicks",
    fields={"priority_id": 3, "tracker_id": 1}
)

# Create an issue with a file attached (from a server-side path)
create_redmine_issue(
    project_id=1,
    subject="Performance report attached",
    uploads=[
        {
            "file_path": "/app/attachments/report.pdf",
            "content_type": "application/pdf",
            "description": "Q2 performance report"
        }
    ]
)

# Create an issue with a file attached (from base64 content)
create_redmine_issue(
    project_id=1,
    subject="Screenshot of error",
    uploads=[
        {
            "content_base64": "<base64-encoded-bytes>",
            "filename": "error-screenshot.png",
            "content_type": "image/png"
        }
    ]
)
```

---

### `update_redmine_issue`

Updates an existing issue with the provided fields. Blocked when `REDMINE_MCP_READ_ONLY=true`.

**Parameters:**
- `issue_id` (integer, required): ID of the issue to update
- `fields` (object, required): Dictionary of fields to update
- `uploads` (list, optional): Files to attach to the issue. Maximum 10 items. Each item is an object with:
  - Exactly ONE source key:
    - `content_base64` (string): Raw file bytes encoded as base64. `filename` is required when using this source.
    - `source_url` (string): HTTP(S) URL the server fetches. Filename is derived from the URL or `Content-Disposition` if omitted.
    - `file_path` (string): Absolute path to a file already on the server. Must be inside `ATTACHMENTS_DIR` or a directory listed in `REDMINE_MCP_UPLOAD_FILE_ROOTS`. Filename is derived from the path if omitted.
  - `filename` (string, optional): Name the attachment will have in Redmine. Required for `content_base64`; derived for other sources when omitted.
  - `content_type` (string, optional): MIME type override (e.g. `"application/pdf"`).
  - `description` (string, optional): Human-readable description for the attachment.

**Returns:** Updated issue dictionary. When `uploads` is provided and at least one attachment succeeds, the response includes:
- `attachments` (list): Metadata for each attached file (id, filename, filesize, content_url, etc.).
- `journal_id` (integer): ID of the journal entry the attachments were placed on.

**Note:** You can use either `status_id` or `status_name` in fields. When `status_name` is provided, the tool automatically resolves the corresponding status ID.
You can also update custom fields by name (for example `{"size": "S"}`) and the tool will resolve them to Redmine `custom_fields` entries using project custom-field metadata. You can still pass explicit `custom_fields` with field IDs.

When `REDMINE_AGILE_ENABLED=true`, you can also set RedmineUP Agile fields, written via the Agile plugin endpoint:

- `story_points` — non-negative integer, or `null` to clear.
- `agile_sprint_id` — the sprint (board) the issue belongs to; `0`/`null` removes it from its sprint.
- `position` — position within the sprint/backlog (read back as `agile_position`; accepted under either name).

Each may be given top-level in `fields` or nested under an `agile_data_attributes` dict (both forms are equivalent):

```python
# Move issue to sprint 117 (top-level or nested are equivalent)
update_redmine_issue(issue_id=123, fields={"agile_sprint_id": 117})
update_redmine_issue(issue_id=123, fields={"agile_data_attributes": {"agile_sprint_id": 117}})
# Remove from its sprint
update_redmine_issue(issue_id=123, fields={"agile_sprint_id": 0})
```

Updates are applied **in place**: the tool reads the current `agile_data` row and carries the existing values (and row id) forward, so changing one agile field (e.g. the sprint) does not clear the others. The updated issue is returned with the resulting `story_points`, `agile_sprint_id`, and `agile_position` so the change can be verified from the response. If the plugin is disabled, these agile keys are silently ignored.

An `agile_data_attributes` value that is not an object, or that carries a key outside the three writable fields above, returns an error listing what was accepted rather than being ignored. If the current `agile_data` row cannot be read (other than it not existing yet), the write is aborted instead of falling back to a payload that would replace the row.

**Note:** these agile keys are always intercepted before custom field resolution, regardless of the `REDMINE_AGILE_ENABLED` setting. If your Redmine instance has a custom field literally named `"story_points"` (or `"agile_sprint_id"`/`"position"`), it cannot be updated by name through this tool — use explicit `custom_fields` with its field ID instead (e.g. `{"custom_fields": [{"id": 42, "value": "8"}]}`).

When `REDMINE_TAGS_ENABLED=true`, you can pass `tag_list` to set the issue's AlphaNodes additional_tags tags — a list of names or a comma-separated string; `[]` clears all tags. It replaces the full tag set (it is not additive), is intercepted before custom-field resolution (so a custom field named `"tag_list"` must use the explicit `custom_fields` id form), and requires `create_issue_tags` (new tags) or `edit_issue_tags` (existing tags only). A `tag_list` change is recorded in the issue journal. Silently ignored when the flag is off.

```python
# Requires REDMINE_TAGS_ENABLED=true — replaces the issue's tags
update_redmine_issue(issue_id=123, fields={"tag_list": ["fast-track", "backend"]})
# Clear all tags
update_redmine_issue(issue_id=123, fields={"tag_list": []})
```

**Attaching files to a journal note:** pass a `notes` key inside `fields` alongside `uploads`. The attachments will be associated with that journal note in the issue history.

**Examples:**
```python
# Update issue status using status name
update_redmine_issue(
    issue_id=123,
    fields={
        "status_name": "Resolved",
        "notes": "Fixed the issue"
    }
)

# Or use status_id directly
update_redmine_issue(
    issue_id=123,
    fields={
        "status_id": 3,
        "assigned_to_id": 5
    }
)

# Update custom field by name
update_redmine_issue(
    issue_id=123,
    fields={
        "size": "S"
    }
)

# Set story points (requires REDMINE_AGILE_ENABLED=true)
update_redmine_issue(
    issue_id=123,
    fields={
        "story_points": 8
    }
)

# Attach a file from a URL and post a note referencing it
update_redmine_issue(
    issue_id=123,
    fields={
        "notes": "Attached the latest test report"
    },
    uploads=[
        {
            "source_url": "http://localhost:3012/attachments/report-uuid",
            "filename": "test-report.pdf",
            "content_type": "application/pdf"
        }
    ]
)

# Attach a server-side file (from ATTACHMENTS_DIR or REDMINE_MCP_UPLOAD_FILE_ROOTS)
update_redmine_issue(
    issue_id=123,
    fields={},
    uploads=[
        {
            "file_path": "/app/attachments/screenshot.png"
        }
    ]
)
```

---

### `delete_redmine_issue`

Hard-delete an issue via `DELETE /issues/{id}.json`. Blocked when `REDMINE_MCP_READ_ONLY=true`.

Issue deletion in Redmine is **irreversible** and cascades to subtasks, journals (comments), attachments, time entries, and inbound relations from issues that referenced this one. To prevent accidental destruction, the tool refuses unless `confirm_delete=True`, and refuses *again* when the issue has subtasks unless `confirm_delete_with_children=True` is also passed.

For other lifecycle operations, use [`create_redmine_issue`](#create_redmine_issue), [`update_redmine_issue`](#update_redmine_issue), [`copy_issue`](#copy_issue), or [`get_redmine_issue`](#get_redmine_issue).

**Parameters:**
- `issue_id` (integer, required): ID of the issue to delete. Must be a positive integer.
- `confirm_delete` (boolean, optional): When `False` (default), the tool refuses and returns an impact preview. Pass `True` to actually delete.
- `confirm_delete_with_children` (boolean, optional): When the issue has subtasks, `confirm_delete=True` alone refuses with code `CHILDREN_PRESENT`. Pass this flag too to opt in to cascade-deleting the subtasks.

**Refusal envelope (default):**
```json
{
    "error": "Refusing to delete issue 42 without explicit confirmation.",
    "code": "CONFIRMATION_REQUIRED",
    "hint": "Issue deletion in Redmine is irreversible ...",
    "impact": {
        "issue_id": 42,
        "subject": "...",
        "children_count": 0,
        "journals_count": 0,
        "attachments_count": 0,
        "relations_count": 0,
        "time_entries_count": 0
    }
}
```

`time_entries_count` is `null` when the count could not be read. Redmine has
no `time_entries` include for an issue, so it is the one count that needs its
own request, and that request needs `view_time_entries` — which permission to
read the issue does not imply. A caller lacking it sees `null` rather than
`0`, because `0` would understate an irreversible cascade. Any other failure
reading it returns a normal error envelope instead. The other four counts come
from the issue payload and cost no extra request, including `children`, which
is absent from the payload for a leaf issue and counts as zero.

**Success envelope:**
```json
{
    "success": true,
    "deleted_issue_id": 42,
    "cascade_deleted": {
        "issue_id": 42,
        "subject": "...",
        "children_count": 0,
        "journals_count": 0,
        "attachments_count": 0,
        "relations_count": 0,
        "time_entries_count": 0
    }
}
```

`cascade_deleted` carries the same shape as `impact` above, so
`time_entries_count` can be `null` there too.

**Error codes:** `CONFIRMATION_REQUIRED`, `CHILDREN_PRESENT`, `NOT_FOUND` (with `upstream_status: 404`).

**Examples:**
```python
# Preview what would be deleted
delete_redmine_issue(issue_id=42)
# -> {"code": "CONFIRMATION_REQUIRED", "impact": {...}, ...}

# Explicit delete
delete_redmine_issue(issue_id=42, confirm_delete=True)
# -> {"success": True, "deleted_issue_id": 42, ...}

# Subtasks present -> double-confirm
delete_redmine_issue(issue_id=42, confirm_delete=True)
# -> {"code": "CHILDREN_PRESENT", ...}
delete_redmine_issue(
    issue_id=42,
    confirm_delete=True,
    confirm_delete_with_children=True,
)
# -> {"success": True, "cascade_deleted": {"children_count": 3, ...}}
```

---

### `copy_issue`

Duplicate an existing issue using Redmine's native copy mechanism. Optionally overrides selected fields, recursively copies subtasks, and copies attachments.

**Parameters:**
- `issue_id` (integer, required): ID of the source issue to copy.
- `project_id` (integer or string, optional): Target project for the copy. Defaults to the source issue's project.
- `subject` (string, optional): New subject for the copy. Defaults to the source subject.
- `link_original` (boolean, optional): Create a `copied_to`/`copied_from` relation between the original and the copy. Default: `true`.
- `copy_subtasks` (boolean, optional): Recursively copy the source's subtasks. Default: `true`.
- `copy_attachments` (boolean, optional): Copy attachments to the new issue. Default: `true`.
- `field_overrides` (object or JSON string, optional): Field values to override on the copy (e.g., `{"assigned_to_id": 5, "description": "..."}`).

**Returns:** Dictionary containing the newly created issue. On failure, a dict with an `"error"` key.

**Example:**
```python
copy_issue(
    issue_id=123,
    subject="Copy of login bug",
    field_overrides={"assigned_to_id": 7}
)
```

**Notes:**
- Respects `REDMINE_MCP_READ_ONLY` — returns an error in read-only mode.
- The target user must have permission to create issues in the destination project.

---

### `manage_issue_relation`

List, create, or delete a Redmine issue relation.

**Parameters:**
- `action` (string, required): Operation to perform. Allowed: `list`, `create`, `delete`
- `issue_id` (integer): Source issue ID. Required for `action="list"` and `action="create"`
- `issue_to_id` (integer): Target issue ID. Required for `action="create"`
- `relation_id` (integer): Relation ID. Required for `action="delete"`
- `relation_type` (string, optional): One of `relates`, `duplicates`, `duplicated`, `blocks`, `blocked`, `precedes`, `follows`, `copied_to`, `copied_from`. Defaults to `relates` on create
- `delay` (integer, optional): Delay in days. Only meaningful for `precedes` / `follows`

**Returns:**
- `list`: array of relation dicts (`id`, `issue_id`, `issue_to_id`, `relation_type`, `delay`)
- `create`: relation dict
- `delete`: `{"success": true, "deleted_relation_id": <id>}`
- Error: `{"error": "..."}`

**Examples:**

```python
# List all relations on an issue
manage_issue_relation(action="list", issue_id=123)

# Create a "blocks" relation
manage_issue_relation(action="create", issue_id=123, issue_to_id=456, relation_type="blocks")

# Create a "precedes" relation with a 3-day delay
manage_issue_relation(action="create", issue_id=1, issue_to_id=2, relation_type="precedes", delay=3)

# Delete a relation by ID
manage_issue_relation(action="delete", relation_id=42)
```

**Notes:**
- `list` is allowed in read-only mode; `create` and `delete` are blocked when `REDMINE_MCP_READ_ONLY=true`.

---

### `list_subtasks`

List subtasks (child issues) of a given issue. Includes closed subtasks.

**Parameters:**
- `issue_id` (integer, required): ID of the parent issue.

**Returns:** List of child issue dictionaries.

**Notes:**
- To create a new subtask, use `create_redmine_issue` with the `parent_issue_id` field set:
  ```python
  create_redmine_issue(
      project_id=1,
      subject="Subtask",
      fields={"parent_issue_id": 123}
  )
  ```

---

### `manage_issue_watcher`

Add or remove a watcher on a Redmine issue. Requires Redmine 2.3.0+.

**Parameters:**
- `action` (string, required): Allowed: `add`, `remove`
- `issue_id` (integer, required): ID of the issue
- `user_id` (integer, required): ID of the user to add or remove

**Returns:** `{"success": true, "issue_id": ..., "user_id": ...}` on success; `{"error": "..."}` on failure.

**Examples:**

```python
manage_issue_watcher(action="add", issue_id=123, user_id=5)
manage_issue_watcher(action="remove", issue_id=123, user_id=5)
```

**Notes:**
- All actions are write operations and respect `REDMINE_MCP_READ_ONLY`.

---

### `manage_issue_note`

Edit text or toggle privacy of a Redmine journal entry (issue note). `get_private_notes` is a separate read tool.

**Parameters:**
- `action` (string, required): Allowed: `edit`, `set_private`
- `journal_id` (integer, required): ID of the journal entry (from `get_redmine_issue` with `include_journals=true`)
- `notes` (string): New notes text (may be empty to clear). Required for `action="edit"`
- `private_notes` (boolean, optional): Optionally toggle the private flag during `edit`
- `is_private` (boolean): Required for `action="set_private"` — `true` to mark private, `false` to make public

**Returns:**
- `edit`: `{"success": true, "journal_id": ..., "notes": ..., "private_notes": ...}`
- `set_private`: `{"success": true, "journal_id": ..., "private_notes": <bool>}`
- Error: `{"error": "..."}`

**Examples:**

```python
# Edit a note's text
manage_issue_note(action="edit", journal_id=42, notes="Updated text")

# Edit text and mark private at the same time
manage_issue_note(action="edit", journal_id=42, notes="Confidential", private_notes=True)

# Toggle privacy without changing the text
manage_issue_note(action="set_private", journal_id=42, is_private=True)
```

**Notes:**
- Only the `notes` text and `private_notes` flag can be edited. Journal `details` (field-change history) are immutable.
- If a journal has no `details` and its notes are cleared via `edit`, Redmine will delete the journal record.
- Both actions are writes and respect `REDMINE_MCP_READ_ONLY`.
- Requires `edit_issue_notes` / `edit_own_issue_notes` permission (server-enforced).

---

### `get_private_notes`

Retrieve only the private notes (journals with `private_notes=true`) of an issue. Requires the "View private notes" permission.

**Parameters:**
- `issue_id` (integer, required): ID of the issue.

**Returns:** List of journal dictionaries where `private_notes` is `true`. Journals with empty note bodies are omitted.

---

### `manage_issue_category`

List, create, update, or delete a Redmine issue category.

**Parameters:**
- `action` (string, required): Allowed: `list`, `create`, `update`, `delete`
- `project_id` (integer or string): Project identifier. Required for `action="list"` and `action="create"`
- `category_id` (integer): Category ID. Required for `action="update"` and `action="delete"`
- `name` (string): Category name. Required for `action="create"`, optional for `action="update"` (cannot be blank)
- `assigned_to_id` (integer, optional): Default assignee user ID. For `create` and `update`
- `reassign_to_id` (integer, optional): Reassign existing issues to this category ID on `delete`. If omitted, issues become uncategorised

**Returns:**
- `list`: array of category dicts (`id`, `name`, `project`, `assigned_to`)
- `create`/`update`: category dict
- `delete`: `{"success": true, "deleted_category_id": ..., "reassigned_to_id": ...}`
- Error: `{"error": "..."}`

**Examples:**

```python
# List all categories in a project
manage_issue_category(action="list", project_id="my-project")

# Create a new category with a default assignee
manage_issue_category(action="create", project_id=10, name="Backend", assigned_to_id=5)

# Rename a category
manage_issue_category(action="update", category_id=3, name="Renamed")

# Delete a category and reassign its issues to another one
manage_issue_category(action="delete", category_id=3, reassign_to_id=7)
```

**Notes:**
- `list` works in read-only mode; `create`, `update`, and `delete` are blocked when `REDMINE_MCP_READ_ONLY=true`.
- `update` requires at least one of `name` or `assigned_to_id`.

---

## MCP Apps (Interactive Tools)

### `show_triage_board`

Render an interactive Kanban board of a project's issues (MCP Apps). Columns
are issue statuses; cards show id, subject, assignee, and priority. Drag a
card to another status column to change the issue's status in Redmine (writes
back via `update_redmine_issue`; the move reverts with an explanation if
Redmine rejects the transition). Dragging is disabled when
`REDMINE_MCP_READ_ONLY=true`. Requires a client that supports MCP Apps
rendering.

**Parameters:**
- `project_id` (int | str, required): project to display.
- `filters` (dict, optional): extra Redmine filters, same as `list_redmine_issues`.

### `get_triage_board_data`

Backend data source for the Kanban board's Refresh action. Returns the same
payload as `show_triage_board` without a UI resource. Called by the board's
iframe, not normally invoked directly.

### `show_project_dashboard`

Render a live project dashboard (health snapshot) for a project (MCP Apps):
open vs closed counts, overdue and due-this-week issues, an open-by-priority
breakdown, and recent activity. Clicking a figure drills into the matching
issue list in-panel. Prefer `summarize_project_status` when the user wants a
written narrative summary, and `show_triage_board` when they want to work
issues in a board. Read-only. Requires a client that supports MCP Apps
rendering.

**Parameters:**
- `project_id` (int | str, required): project to display.
- `filters` (dict, optional): extra Redmine filters, same as `list_redmine_issues`.

### `get_project_dashboard_data`

Backend data source for the dashboard's Refresh action. Returns the same
payload as `show_project_dashboard` without a UI resource. App-only; called
by the dashboard's iframe, not normally invoked directly.

---

## Time Tracking

### `list_time_entries`

List time entries from Redmine with optional filtering and pagination.

**Parameters:**
- `project_id` (integer or string, optional): Filter by project (numeric ID or string identifier)
- `issue_id` (integer, optional): Filter by issue ID
- `user_id` (integer or string, optional): Filter by user ID. Use `"me"` for current user
- `from_date` (string, optional): Start date filter (YYYY-MM-DD format)
- `to_date` (string, optional): End date filter (YYYY-MM-DD format)
- `limit` (integer, optional): Maximum entries to return. Default: `25`, Max: `100`
- `offset` (integer, optional): Number of entries to skip for pagination. Default: `0`

**Returns:** List of time entry dictionaries

**Example:**
```json
[
  {
    "id": 1,
    "hours": 2.5,
    "comments": "Bug fix work",
    "spent_on": "2024-03-15",
    "user": {"id": 5, "name": "John Doe"},
    "project": {"id": 10, "name": "My Project"},
    "issue": {"id": 123},
    "activity": {"id": 9, "name": "Development"},
    "created_on": "2024-03-15T10:30:00",
    "updated_on": "2024-03-15T10:30:00"
  }
]
```

**Usage:**
```python
# List all time entries for a project
entries = list_time_entries(project_id="my-project")

# Filter by issue and date range
entries = list_time_entries(
    issue_id=123,
    from_date="2024-01-01",
    to_date="2024-03-31"
)

# Get current user's time entries
my_entries = list_time_entries(user_id="me")
```

---

### `manage_time_entry`

Create or update a Redmine time entry. Replaces `create_time_entry`, `update_time_entry`, and `log_time_for_user`.

**Parameters:**
- `action` (string, required): Allowed: `create`, `update`
- `hours` (float): Hours spent. Required for `action="create"`; optional for `update` (must be positive if provided)
- `project_id` (integer or string): Required for `action="create"` if `issue_id` is not provided
- `issue_id` (integer): Required for `action="create"` if `project_id` is not provided
- `user_id` (integer, optional): Log on behalf of this user (`create` only). Requires `log_time_for_other_users` permission
- `time_entry_id` (integer): Entry ID to update. Required for `action="update"`
- `activity_id` (integer, optional): Activity type (e.g., Development, Design)
- `comments` (string, optional): Description. Empty string clears the field on `update`
- `spent_on` (string, optional): Date in `YYYY-MM-DD` format

**Returns:**
- `create`/`update`: time entry dict (`id`, `hours`, `comments`, `spent_on`, `user`, `project`, `issue`, `activity`, etc.)
- Error: `{"error": "..."}`

**Examples:**

```python
# Log 2.5h against an issue
manage_time_entry(action="create", hours=2.5, issue_id=123, comments="Fixed login bug")

# Log 1.0h against a project with explicit activity and date
manage_time_entry(
    action="create",
    hours=1.0,
    project_id="my-project",
    activity_id=9,
    comments="Code review",
    spent_on="2026-04-15",
)

# Log time on behalf of another user (replaces log_time_for_user)
manage_time_entry(
    action="create",
    hours=2.0,
    issue_id=123,
    user_id=7,
    comments="Pair programming",
)

# Update an existing entry
manage_time_entry(action="update", time_entry_id=1, hours=3.0)
```

**Notes:**
- Both actions are write operations and respect `REDMINE_MCP_READ_ONLY`.
- For bulk imports of multiple entries (timesheets, weekly reports), prefer `import_time_entries` over calling `manage_time_entry(action="create")` in a loop.
- Some Redmine versions reject `user_id` when the authenticated admin is not a project member (Redmine defects #31587, #32774). The workaround is to add the admin as a project member.

---

### `list_time_entry_activities`

List available time entry activity types from Redmine.

Use this tool to discover valid `activity_id` values before calling `manage_time_entry`.

When logging time against a specific project, always call with `project_id` first — project-specific activity IDs differ from global ones and using the wrong ID causes `"Activity is not included in the list"` errors.

**Parameters:**
- `project_id` (string or integer, optional): Project identifier. When provided, returns project-specific activities via `GET /projects/:id.json?include=time_entry_activities` (Redmine 3.4.0+).

**Returns:**
- Without `project_id`: list of activity dicts with `id`, `name`, `active`, `is_default`
- With `project_id`: dict with `project_id` and `activities` (same structure). If the project has no custom activities, `activities` is empty and a `note` field advises falling back to the global list.

**Example (global):**
```json
[
  {"id": 4, "name": "Development", "active": true, "is_default": false},
  {"id": 5, "name": "Design", "active": true, "is_default": false},
  {"id": 6, "name": "Testing", "active": true, "is_default": false}
]
```

**Example (project-scoped):**
```json
{
  "project_id": "my-project",
  "activities": [
    {"id": 9, "name": "Development", "active": true, "is_default": false}
  ]
}
```

---

## Discovery / Enumeration Tools

These tools help LLMs discover valid IDs (trackers, statuses, priorities, users, saved queries) without guessing. Call these **before** create/update tools that require the corresponding ID.

### `list_redmine_trackers`

List all trackers (issue types like Bug, Feature, Support). Use to discover valid `tracker_id` values.

**Parameters:** None.

**Returns:** List of `{id, name, description}` dicts.

**Example:**
```json
[
  {"id": 1, "name": "Bug", "description": ""},
  {"id": 2, "name": "Feature", "description": "New feature requests"},
  {"id": 3, "name": "Support", "description": ""}
]
```

---

### `list_project_trackers`

List trackers enabled for a specific project. Use this instead of `list_redmine_trackers` when you need only the trackers applicable to a given project (project settings can restrict the instance-wide tracker list).

**Parameters:**
- `project_id` (integer or string, required): Project ID (numeric) or identifier (string)

**Returns:** List of `{id, name}` dicts for trackers enabled on the project.

**Example:**
```json
[
  {"id": 1, "name": "Bug"},
  {"id": 2, "name": "Feature"}
]
```

**Usage:**
```python
# Discover which trackers a project accepts before creating an issue
trackers = list_project_trackers(project_id="my-project")
# [{"id": 1, "name": "Bug"}, {"id": 2, "name": "Feature"}]

# Then create an issue with a valid tracker_id
create_redmine_issue(project_id="my-project", subject="...", fields={"tracker_id": 1})
```

**Notes:**
- Distinct from `list_redmine_trackers`, which returns all trackers configured instance-wide regardless of project membership. Use this tool when the project is known and you want to avoid passing a tracker ID that Redmine will reject.

---

### `list_redmine_issue_statuses`

List all issue statuses. Use to discover valid `status_id` values. `update_redmine_issue` also accepts a `status_name` field that internally resolves the ID.

**Parameters:** None.

**Returns:** List of `{id, name, is_closed}` dicts — `is_closed` flags statuses that count as "closed" for reporting purposes.

**Example:**
```json
[
  {"id": 1, "name": "New", "is_closed": false},
  {"id": 2, "name": "In Progress", "is_closed": false},
  {"id": 5, "name": "Closed", "is_closed": true}
]
```

---

### `list_redmine_issue_priorities`

List all priority levels. Use to discover valid `priority_id` values.

**Parameters:** None.

**Returns:** List of `{id, name, active, is_default}` dicts.

**Example:**
```json
[
  {"id": 1, "name": "Low", "active": true, "is_default": false},
  {"id": 2, "name": "Normal", "active": true, "is_default": true},
  {"id": 3, "name": "High", "active": true, "is_default": false}
]
```

---

### `list_redmine_users`

List Redmine users with optional filtering. **Requires admin permission** — non-admin users receive a 403 error. Use to discover user IDs for assignment, watchers, or time-entry authoring.

**Parameters:**
- `name` (string, optional): Case-insensitive substring filter (matches login, firstname, lastname, email).
- `group_id` (integer, optional): Filter users who belong to a specific group.
- `limit` (integer, optional): Maximum users to return (default 25, clamped to 1–100).
- `offset` (integer, optional): Pagination offset. Default 0.

**Returns:** List of `{id, login, firstname, lastname, mail, created_on}` dicts.

**Example:**
```python
list_redmine_users(name="alice")
# [{"id": 5, "login": "alice", "firstname": "Alice", "lastname": "A", ...}]
```

---

### `get_current_user`

Retrieve the currently authenticated user's profile. Resolves to `GET /users/current.json`, and works for any authenticated user (not admin-only) -- Redmine exempts the `show` action from its admin filter and resolves the `current` id behind a plain login check. Useful when a user asks the LLM to do something "for me" -- the LLM can call this to resolve the current user's ID.

With `include_memberships` it also answers "which projects am I a member of, and with which roles" in the same request. The alternative is `list_project_members` once per project.

**Parameters:**
- `include_memberships` (boolean, optional): Add `memberships` to the response. Default `false`. Costs no extra request -- the include rides the same call.

**Returns:** Dict with `id, login, firstname, lastname, mail, admin, created_on, last_login_on`. With `include_memberships`, also `memberships`: a list of `{id, project: {id, name}, roles: [{id, name}]}` entries. A role inherited from a group membership carries `inherited: true`; Redmine omits the key for a direct role, and so does this tool. Redmine limits the list to projects visible to the caller, which covers active and closed projects but not archived ones -- so an empty list means "holds none that are visible", not necessarily "holds none".

Groups are deliberately not offered as an include: Redmine gates that block on the caller being an admin, so a non-admin would get a success response with the key simply missing -- indistinguishable from "belongs to no groups".

**Example:**
```json
{
  "id": 5,
  "login": "alice",
  "firstname": "Alice",
  "lastname": "A",
  "mail": "alice@example.com",
  "admin": false,
  "created_on": "2025-01-15T10:00:00",
  "last_login_on": "2026-04-16T09:30:00"
}
```

**Example** (`include_memberships=True`):
```json
{
  "id": 5,
  "login": "alice",
  "admin": false,
  "memberships": [
    {
      "id": 12,
      "project": {"id": 1, "name": "Website"},
      "roles": [
        {"id": 3, "name": "Developer"},
        {"id": 4, "name": "Manager", "inherited": true}
      ]
    }
  ]
}
```

---

### `list_redmine_queries`

List all saved custom queries (saved issue filters) visible to the current user. Once discovered, the `id` can be passed as a `query_id` filter to `list_redmine_issues` to run the saved query.

**Parameters:** None.

**Returns:** List of `{id, name, is_public, project_id}` dicts. `project_id` is `null` for cross-project queries.

**Example:**
```json
[
  {"id": 1, "name": "Open bugs", "is_public": true, "project_id": 10},
  {"id": 2, "name": "My tasks", "is_public": false, "project_id": null}
]
```

**Notes:**
- **Read-only tool.** Redmine's REST API does not support creating, updating, or deleting saved queries — they can only be managed via the web UI.

---

### `import_time_entries`

Bulk-import multiple time entries via sequential API calls. Redmine has no native bulk-import endpoint, so each entry is POSTed individually. Per-entry errors are captured so a partial import still yields useful feedback.

**Parameters:**
- `entries` (array of objects, required): List of time entry dicts. Each entry accepts: `hours` (required), plus at least one of `project_id`/`issue_id`. Optional: `user_id` (log on behalf of a teammate), `activity_id`, `comments`, `spent_on`. Capped at 500 entries per call -- split larger imports into multiple invocations. (The JSON-string variant was dropped in #114; passing a string is rejected at the FastMCP boundary with the `INVALID_ARGUMENTS` envelope.)
- `stop_on_error` (boolean, optional): Abort on the first error. Default: `false` (continue past errors).

**Returns:** Dictionary with:
- `total` (integer): total entries attempted
- `succeeded` (integer): count of successful entries
- `failed` (integer): count of failed entries
- `created` (array): successfully-created time entry dicts
- `errors` (array): `{index, entry, error}` for each failed entry

**Example:**
```python
import_time_entries([
    {"hours": 2.0, "issue_id": 123, "comments": "Bug fix"},
    {"hours": 1.5, "project_id": "web", "activity_id": 9, "user_id": 7},
    {"hours": 3.0, "issue_id": 456},
])
# Returns:
# {
#   "total": 3,
#   "succeeded": 3,
#   "failed": 0,
#   "created": [...],
#   "errors": []
# }
```

**Partial failure example:**
```python
# One entry has invalid activity_id -> continues past it
import_time_entries([
    {"hours": 1.0, "issue_id": 1},
    {"hours": 2.0, "issue_id": 2, "activity_id": 999},  # bogus
    {"hours": 3.0, "issue_id": 3},
])
# Returns:
# {
#   "total": 3, "succeeded": 2, "failed": 1,
#   "created": [<entry 1>, <entry 3>],
#   "errors": [{"index": 1, "entry": {...}, "error": "Activity is invalid"}]
# }
```

**Notes:**
- Unknown fields in each entry are silently filtered out (whitelist: `hours`, `user_id`, `project_id`, `issue_id`, `activity_id`, `comments`, `spent_on`).
- Respects `REDMINE_MCP_READ_ONLY`.

---

## Search & Wiki

### `search_entire_redmine`

Search across issues and wiki pages in the Redmine instance. Requires Redmine 3.3.0 or higher.

**Parameters:**
- `query` (string, required): Text to search for
- `resources` (list, optional): Filter by resource types. Allowed: `["issues", "wiki_pages"]`. Default: both types
- `limit` (integer, optional): Maximum results to return (max 100). Default: 100
- `offset` (integer, optional): Pagination offset. Default: 0

**Returns:**
```json
{
    "results": [
        {
            "id": 123,
            "type": "issues",
            "title": "Bug in login page",
            "project": "Web App",
            "status": "Open",
            "updated_on": "2025-01-15T10:00:00Z",
            "excerpt": "First 200 characters of description..."
        },
        {
            "id": null,
            "type": "wiki_pages",
            "title": "Installation Guide",
            "project": "Documentation",
            "status": null,
            "updated_on": "2025-01-10T14:30:00Z",
            "excerpt": "First 200 characters of wiki text..."
        }
    ],
    "results_by_type": {
        "issues": 1,
        "wiki_pages": 1
    },
    "total_count": 2,
    "query": "installation"
}
```

**Example:**
```python
# Search all resource types
search_entire_redmine(query="installation guide")

# Search only wiki pages
search_entire_redmine(query="setup", resources=["wiki_pages"])

# With pagination
search_entire_redmine(query="bug", limit=25, offset=0)
```

**Notes:**
- Requires Redmine 3.3.0+ for search API support
- v1.4 scope limitation: Only `issues` and `wiki_pages` supported
- Invalid resource types are silently filtered out
- Search is case-sensitive/insensitive based on Redmine server DB config

---

### `manage_redmine_wiki_page`

List, get, create, update, delete, or rename a Redmine wiki page. Replaces `list_wiki_pages`, `get_redmine_wiki_page`, `create_redmine_wiki_page`, `update_redmine_wiki_page`, `delete_redmine_wiki_page`, and `rename_wiki_page`.

**Parameters:**
- `action` (string, required): Allowed: `list`, `get`, `create`, `update`, `delete`, `rename`
- `project_id` (integer or string, required): Project identifier (numeric ID or short name)
- `wiki_page_title` (string): Wiki page title. Required for all actions except `list`
- `version` (integer, optional): Specific version number for `get` (default: latest)
- `include_attachments` (boolean, optional): Include attachment metadata in `get` response. Default: `true`
- `text` (string): Page content. Required for `create`. Required for `update` unless `uploads` is provided, in which case the server reuses the page's current text
- `comments` (string, optional): Change log comment for `create` and `update`
- `new_title` (string): New title for `rename` (must differ from `wiki_page_title`)
- `redirect_existing_links` (boolean, optional): When `true` (default), `rename` creates a `WikiRedirect` from the old title to the new title
- `uploads` (list, optional): Files to attach to the page on `create` and `update`. Requires the `edit_wiki_pages` permission on the project. Maximum 10 items. Each item is an object with:
  - Exactly ONE source key:
    - `file_path` (string): Absolute path to a file already on the server. Must be inside `ATTACHMENTS_DIR` or a directory listed in `REDMINE_MCP_UPLOAD_FILE_ROOTS`. Filename is derived from the path if omitted.
    - `source_url` (string): HTTP(S) URL the server fetches. Filename is derived from the URL or `Content-Disposition` if omitted.
    - `content_base64` (string): Raw file bytes encoded as base64. `filename` is required when using this source. Prefer `file_path` or `source_url` where possible: base64 sends the entire file through the model, while a path or URL costs a few tokens regardless of file size.
  - `filename` (string, optional): Name the attachment will have in Redmine. Required for `content_base64`; derived for other sources when omitted.
  - `content_type` (string, optional): MIME type override (e.g. `"application/xml"`).
  - `description` (string, optional): Human-readable description for the attachment.

**Returns:**
- `list`: array of page metadata dicts (`title`, `version`, `parent_title` if present, `created_on`, `updated_on`) — no body text
- `get`/`create`/`update`: full wiki page dict (`title`, `text`, `version`, `created_on`, `updated_on`, `author`, `project`, `attachments` when applicable). `project` is only returned by Redmine 7.0+; earlier versions omit the key
- `delete`: `{"success": true, "title": ..., "message": ...}`
- `rename`: `{"success": true, ...}` plus the renamed page's metadata
- Error: `{"error": "..."}`

**Attachment-only updates:** Redmine rejects a wiki update with a blank body (`422 Text field cannot be blank`), so when `uploads` is given without `text` the server re-reads the page and sends its current text back unchanged. The body is never routed through the model, and because the text is identical Redmine does not create a new revision. The request carries the version read during that fetch, so a concurrent edit returns an edit-conflict error rather than silently reverting the other author's work.

**Examples:**

```python
# List all wiki pages in a project (metadata only)
manage_redmine_wiki_page(action="list", project_id="my-project")

# Get the latest version of a page (with attachments by default)
manage_redmine_wiki_page(action="get", project_id="my-project", wiki_page_title="Installation_Guide")

# Get a specific version, no attachments
manage_redmine_wiki_page(
    action="get",
    project_id=123,
    wiki_page_title="Installation_Guide",
    version=3,
    include_attachments=False,
)

# Create a new page
manage_redmine_wiki_page(
    action="create",
    project_id="my-project",
    wiki_page_title="Getting_Started",
    text="# Getting Started\n\nWelcome to the project!",
    comments="Initial creation",
)

# Update an existing page
manage_redmine_wiki_page(
    action="update",
    project_id="my-project",
    wiki_page_title="Installation_Guide",
    text="# Installation\n\nUpdated steps...",
    comments="Refreshed for 2026",
)

# Delete a page
manage_redmine_wiki_page(action="delete", project_id="my-project", wiki_page_title="Obsolete_Page")

# Rename a page (default: leaves a WikiRedirect)
manage_redmine_wiki_page(
    action="rename",
    project_id="my-project",
    wiki_page_title="Old_Title",
    new_title="New_Title",
)

# Attach a diagram and reference it with the draw.io macro in one call.
# The macro accepts png, svg, xml, and drawio attachments.
manage_redmine_wiki_page(
    action="update",
    project_id="my-project",
    wiki_page_title="Architecture",
    text="# Architecture\n\n{{drawio_attach(diagram.drawio)}}\n",
    uploads=[{"file_path": "/srv/attachments/diagram.drawio"}],
)
```

Note that the `redmine_drawio` plugin creates a new attachment every time a diagram is saved rather than replacing the previous one, so diagram attachments accumulate on the page and stale ones have to be deleted manually.

```python
# Attach a file without touching the page body.
manage_redmine_wiki_page(
    action="update",
    project_id="my-project",
    wiki_page_title="Architecture",
    uploads=[{"source_url": "https://example.com/spec.pdf"}],
)
```

**Notes:**
- `list` and `get` are allowed in read-only mode; `create`, `update`, `delete`, and `rename` are blocked when `REDMINE_MCP_READ_ONLY=true`.
- Wiki page titles typically use underscores instead of spaces.
- Content format (Textile/Markdown) depends on Redmine server configuration.
- Use `get_redmine_attachment` to download wiki attachments.
- `rename` requires the `rename_wiki_pages` permission. If the API user lacks it, Redmine **silently drops the title change** (the body still updates). The tool re-fetches the page at `new_title` after the update and returns an explicit error if the new title is unreachable.
- The `rename` action implements `PUT /projects/{id}/wiki/{old_title}.json` and fetches the existing text automatically since Redmine requires `text` on every wiki update.

---

## File Operations

### `list_files`

List all files uploaded to a Redmine project's **Files** section (not issue attachments).

**Parameters:**
- `project_id` (integer or string, required): Project identifier.

**Returns:** List of file metadata dictionaries (`id`, `filename`, `filesize`, `content_type`, `description`, `content_url`, `digest`, `downloads`, `author`, `version`, `created_on`).

**Example:**
```json
[
    {
        "id": 42,
        "filename": "spec.pdf",
        "filesize": 125678,
        "content_type": "application/pdf",
        "description": "Design spec v2",
        "content_url": "https://redmine.example.com/attachments/download/42/spec.pdf",
        "author": {"id": 5, "name": "Alice"},
        "version": {"id": 3, "name": "Release 1.0"},
        "created_on": "2026-04-10T10:30:00"
    }
]
```

**Notes:**
- Lists files from Redmine's core "Files" module (enabled per project via Settings > Modules > Files).
- Does NOT list issue attachments — use `get_redmine_issue` with `include_attachments=True` for those.
- Does NOT list DMSF documents (separate module, not covered by this tool).

---

### `upload_file`

Upload a file to a Redmine project's Files section. Uses Redmine's standard two-step upload (`POST /uploads.json` for the token, then `POST /projects/{id}/files.json`).

**Provide exactly ONE of `source_url`, `content_base64`, or `file_path`:**
- `source_url` (string) — the server downloads from an HTTP(S) URL. Use this when chaining from another MCP tool that returns a download URL (e.g., Google Drive MCP's `get_drive_file_download_url`), or when the file is served by a local MCP on `localhost`. **Preferred when a URL is available** — no need for the caller to download and re-encode.
- `content_base64` (string) — raw file bytes encoded as base64. Use this only when the caller already has the bytes in memory.
- `file_path` (string): absolute path to a file already on the server. The path must be inside `ATTACHMENTS_DIR` or a directory listed in `REDMINE_MCP_UPLOAD_FILE_ROOTS`. Filename is derived from the path if `filename` is omitted.

**Parameters:**
- `project_id` (integer or string, required): Project identifier.
- `filename` (string, optional): Name the file should have in Redmine.
  - Required when using `content_base64`.
  - Optional with `source_url` or `file_path`, inferred from the URL path, `Content-Disposition` header, or file path if omitted, but always prefer passing an explicit filename.
- `source_url` (string, conditional): HTTP(S) URL to download from.
- `content_base64` (string, conditional): File content as base64.
- `file_path` (string, conditional): Absolute path to a file on the server. Restricted to `ATTACHMENTS_DIR` and directories in `REDMINE_MCP_UPLOAD_FILE_ROOTS`.
- `description` (string, optional): Human-readable description.
- `version_id` (integer, optional): Version/release ID to attach the file to (use `list_redmine_versions` to discover valid IDs).

**Returns:** Dictionary containing the uploaded file's metadata, or `{"error": "..."}` on failure.

**Size limit:** 50 MiB per file. Larger files should be uploaded via Redmine's web UI.

**Examples:**
```python
# From a URL (chained from another MCP tool)
upload_file(
    project_id="web",
    source_url="http://localhost:3012/attachments/abc-123",
    filename="report.pdf",
    description="Q2 report"
)

# From base64 content
import base64
content = base64.b64encode(b"Hello world").decode("ascii")
upload_file(
    project_id="web",
    filename="hello.txt",
    content_base64=content
)

# From a server-side file (must be in ATTACHMENTS_DIR or REDMINE_MCP_UPLOAD_FILE_ROOTS)
upload_file(
    project_id="web",
    file_path="/app/attachments/export.csv",
    description="Latest data export"
)
```

**URL fetch details:**
- Only `http://` and `https://` schemes are supported.
- Follows redirects automatically.
- 30-second timeout on the download.
- Streams the response and aborts early if the size exceeds 50 MiB.

**Notes:**
- Respects `REDMINE_MCP_READ_ONLY`.
- After successful upload, the tool re-fetches full metadata (filename, size, author, etc.) via `GET /attachments/{id}.json`, since Redmine returns HTTP 204 on create with no body.
- `file_path` access is restricted by the server to prevent path traversal. Only paths inside `ATTACHMENTS_DIR` or explicitly allowed directories (`REDMINE_MCP_UPLOAD_FILE_ROOTS`) are permitted.

---

### `delete_file`

Delete a file from a Redmine project. Uses `DELETE /attachments/{id}.json` since files are stored as attachments in Redmine.

**Parameters:**
- `file_id` (integer, required): ID of the attachment to delete (from `list_files`).
- `confirm_delete_any_attachment` (boolean, optional): Bypass the project-scope check to delete issue/wiki/news attachments. Default: `false`.

**Returns:** `{"success": true, "deleted_file_id": <id>}` on success.

**Notes:**
- Redmine's `DELETE /attachments/{id}.json` removes ANY attachment, not just project files. To prevent accidental deletion of issue attachments, `delete_file` first fetches the target and checks its `container_type`. If it's not `Project` (e.g., it's an `Issue` or `WikiPage` attachment), the tool refuses and tells the caller how to bypass.
- To intentionally delete an issue/wiki/news attachment via this tool, pass `confirm_delete_any_attachment=True`.
- Respects `REDMINE_MCP_READ_ONLY`.

---

### `get_redmine_attachment`

Download a Redmine attachment and return a usable reference to it. Works in both HTTP and stdio deployments without any configuration from the caller.

**Parameters:**
- `attachment_id` (integer, required): The ID of the attachment to retrieve

**Returns (HTTP mode** — any explicit `PUBLIC_HOST`, or a non-loopback `SERVER_HOST`):
```json
{
    "uri": "http://my-server.example.com:8000/files/12345678-1234-5678-9abc-123456789012",
    "uri_type": "http",
    "filename": "document.pdf",
    "content_type": "application/pdf",
    "size": 1024,
    "expires_at": "2026-05-09T14:00:00Z",
    "attachment_id": 456
}
```

**Returns (stdio mode** — neither `PUBLIC_HOST` nor a non-loopback `SERVER_HOST` set):
```json
{
    "file_path": "/absolute/local/path/uuid/document.pdf",
    "uri_type": "file",
    "filename": "document.pdf",
    "content_type": "application/pdf",
    "size": 1024,
    "expires_at": "2026-05-09T14:00:00Z",
    "attachment_id": 456
}
```

Callers distinguish the two shapes via `uri_type`: `"http"` or `"file"`. Per the #109 wrap policy, `filename` is structured metadata and is returned verbatim (not wrapped in `<insecure-content>` tags).

**Mode detection (post-#105):**
- An **explicit `PUBLIC_HOST`** (any value, including `localhost` / `127.0.0.1`) selects HTTP mode. This is the correct behavior for Docker port-forwarded deployments where `localhost` on the host actually does reach the container's HTTP server.
- Otherwise, `SERVER_HOST` is consulted; non-loopback values promote to HTTP mode. Loopback values (`localhost`, `127.0.0.1`, `0.0.0.0`) keep stdio mode because `SERVER_HOST` is the bind address and `0.0.0.0` is not a reachable URL host.
- Otherwise stdio mode is used and `file_path` is returned.
- Port is resolved via `PUBLIC_PORT` → `SERVER_PORT` → `8000`.

**Note (#110):** this tool returns its own MCP-proxy URL (HTTP mode) or local file path (stdio), so it is NOT affected by `REDMINE_PUBLIC_URL`. That env var rewrites `content_url` values returned by other tools (`get_redmine_issue.attachments[*].content_url`, `list_files`, etc.) from the internal Redmine origin to the configured public origin — see [`get_redmine_issue`](#get_redmine_issue).

**Security features:**
- Downloads capped at `ATTACHMENT_MAX_DOWNLOAD_BYTES` (default 200 MB). Exceeding the cap aborts the download and deletes the partial file.
- Streaming download with byte counter — cap is enforced even when Redmine's reported file size is missing or understated.
- Filename sanitized to basename before writing to disk (path traversal protection).
- UUID-based storage directories prevent filename collisions and enumeration.
- `file_path` is always an absolute path (resolved via `Path.resolve()`).
- Files are cleaned up automatically by the background cleanup manager on the same schedule as other attachments.

**Examples:**
```python
# stdio mode (no PUBLIC_HOST set) -- pass file_path to another tool
result = get_redmine_attachment(attachment_id=456)
if result["uri_type"] == "file":
    # Pass directly to Claude Code's Read tool or pdf-mcp
    content = read_file(result["file_path"])
else:
    download_url = result["uri"]

# HTTP mode -- uri is a time-limited HTTP URL
result = get_redmine_attachment(attachment_id=456)
if result["uri_type"] == "http":
    print(f"Download from: {result['uri']}")
    print(f"Expires at: {result['expires_at']}")
```

---

---

### `cleanup_attachment_files`

**Operator tool, gated by `REDMINE_MCP_EXPOSE_ADMIN_TOOLS=true` (#115).** Not registered on the default MCP surface — the background cleanup task already runs on the `CLEANUP_INTERVAL_MINUTES` schedule (default 10 min), so an LLM agent should almost never need to invoke this directly. Operators driving cleanup through the MCP surface set the flag to opt in; the underlying background cleanup runs regardless.

Removes expired attachment files and provides cleanup statistics.

**Parameters:** None

**Returns:** Cleanup statistics:
- `cleaned_files`: Number of files removed
- `cleaned_bytes`: Total bytes cleaned up
- `cleaned_mb`: Total megabytes cleaned up (rounded)

**Example:**
```json
{
    "cleaned_files": 12,
    "cleaned_bytes": 15728640,
    "cleaned_mb": 15
}
```

**Note:** Automatic cleanup runs in the background based on server configuration. This tool allows manual cleanup on demand.

---

## Checklist Tools

These tools require the **RedmineUP Checklists Pro** plugin installed on your Redmine instance and `REDMINE_CHECKLISTS_ENABLED=true`.

### `get_checklist`

Retrieve all checklist items for a Redmine issue.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_id` | int | Yes | The ID of the issue whose checklist to retrieve |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| `issue_id` | int | The issue ID |
| `total_count` | int | Number of checklist items |
| `items` | list | Array of checklist item objects |
| `items[].id` | int | Checklist item ID |
| `items[].subject` | string | Item text (wrapped in `<insecure-content>` tags) |
| `items[].is_done` | bool | Whether the item is completed |
| `items[].is_section` | bool | Whether the item is a section header (not a checkable item) |
| `items[].position` | int | Position/order of the item |
| `items[].created_at` | string | ISO timestamp of creation |
| `items[].updated_at` | string | ISO timestamp of last update |

**Error cases:**
- Plugin disabled: returns `{"error": "Checklist support is disabled. Set REDMINE_CHECKLISTS_ENABLED=true..."}`
- Invalid `issue_id`: returns `{"error": "issue_id must be a positive integer."}`
- Issue not found / permission denied: returns Redmine API error

---

### `update_checklist_item`

Update a checklist item's text, done state, or position. This is a **write operation** and is blocked in read-only mode.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `checklist_item_id` | int | Yes | The ID of the checklist item to update |
| `subject` | string | No | New text for the checklist item |
| `is_done` | bool | No | New done state |
| `position` | int | No | New position/order |

At least one optional parameter must be provided.

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | `true` on success |
| `checklist_item_id` | int | The updated item's ID |
| `updated_fields` | list | Names of fields that were updated |

**Error cases:**
- Read-only mode: returns read-only error
- Plugin disabled: returns plugin-disabled error
- No fields provided: returns `{"error": "No fields to update..."}`
- Invalid `is_done` type: returns `{"error": "is_done must be a boolean."}`
- Invalid `position`: returns `{"error": "position must be a positive integer."}`

---

### `create_checklist_item`

Add a new checklist item (or section header) to a Redmine issue's checklist. This is a **write operation** and is blocked in read-only mode. Requires the **RedmineUP Checklists Pro** plugin and `REDMINE_CHECKLISTS_ENABLED=true`.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `issue_id` | int | Yes | — | The ID of the issue to add the checklist item to |
| `subject` | string | Yes | — | Text of the new checklist item or section header |
| `is_section` | bool | No | `false` | When `true`, creates a section header rather than a checkable item |
| `is_done` | bool | No | `false` | Initial done state for checkable items (ignored when `is_section=true`) |
| `position` | int | No | `null` | 1-based position in the checklist. Omit to append at the end |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| `checklist_item_id` | int | ID of the newly created checklist item |
| `issue_id` | int | The issue ID |
| `subject` | string | Item text as stored |
| `is_done` | bool | Done state |
| `is_section` | bool | Whether the item is a section header |
| `position` | int or null | Position in the checklist |

**Error cases:**
- Read-only mode: returns read-only error
- Plugin disabled: returns `{"error": "Checklist support is disabled. Set REDMINE_CHECKLISTS_ENABLED=true..."}`
- Invalid `issue_id`: returns `{"error": "issue_id must be a positive integer."}`
- Blank `subject`: returns `{"error": "subject is required and cannot be blank."}`

**Examples:**
```python
# Append a checkable item
create_checklist_item(issue_id=123, subject="Write unit tests")

# Append a section header (organises items visually)
create_checklist_item(issue_id=123, subject="QA Phase", is_section=True)

# Insert a pre-completed item at position 2
create_checklist_item(issue_id=123, subject="Review spec", is_done=True, position=2)
```

---

## Gantt Chart

### `get_gantt_chart`

Retrieve project timeline (Gantt) data: issues with start/due dates, progress, dependencies, and milestones. **No plugin required** — uses core Redmine REST API (`GET /issues.json` with `include=relations` + `GET /projects/{id}/versions.json`).

Use cases: "What's the current timeline for project X?", "Which issues are overdue?", "Show me the dependency chain on this project". Returns structured data, not an image.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `project_id` | int or string | Yes | – | Project identifier |
| `start_date_after` | string | No | – | `YYYY-MM-DD` filter (issues with `start_date >= this`) |
| `due_date_before` | string | No | – | `YYYY-MM-DD` filter (issues with `due_date <= this`) |
| `include_closed` | bool | No | `false` | Include closed issues. Default `false` keeps response size and pagination cost low on long-lived projects; set to `true` for full historical timelines. |
| `limit` | int | No | `250` | Max issues (1–500) |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| `project_id` | int/str | Echo of input |
| `total_count` | int | Number of issues returned |
| `issues` | list | Each item has `id`, `subject`, `tracker`, `status`, `assigned_to`, `start_date`, `due_date`, `done_ratio`, `estimated_hours`, `parent_id`, `relations` (only `precedes`/`blocks`) |
| `versions` | list | Milestones: `id`, `name`, `due_date`, `status` |

**Note:** If the API user lacks permission to view versions, the `versions` list falls back to empty rather than failing the entire call.

**Performance:** Redmine paginates issues at 25 per HTTP call by default, so a `limit=500` request can trigger ~20 underlying API calls. Expect a few seconds of latency on large projects.

---

## Products (RedmineUP Products plugin)

These tools require the **RedmineUP Products** plugin and `REDMINE_PRODUCTS_ENABLED=true`.

### `manage_product`

List, get, create, or update RedmineUP products. Replaces `list_products`, `get_product`, `add_product`, and `edit_product`.

Requires the **RedmineUP Products** plugin and `REDMINE_PRODUCTS_ENABLED=true`.

**Parameters:**
- `action` (string, required): Allowed: `list`, `get`, `create`, `update`
- `project_id` (integer or string, optional): For `list`, filters products by project (omitted = all accessible). For `create`, optionally associates the new product with a project
- `limit` (integer, optional): For `list`, max results per call (default `100`). Redmine caps `limit` at 100 server-side; values above are clamped
- `product_id` (integer): Required for `get` and `update`
- `name` (string): Required for `create`
- `status_id` (integer, optional): For `create`. Must be `1` (Active, default) or `2` (Inactive)
- `description`, `code` (string, optional): For `create`
- `price` (float, optional): For `create`
- `currency` (string, optional): For `create` (e.g., `"USD"`)
- `category_id` (integer, optional): For `create`
- `tag_list` (string, optional): For `create`, comma-separated tags
- `custom_fields` (list, optional): For `create`, list of `{"id": N, "value": ...}` dicts
- `fields` (dict): For `update`, fields to update. Allowed keys: `name`, `description`, `price`, `currency`, `status_id`, `code`, `project_id`, `category_id`, `tag_list`, `custom_fields`. Unknown keys are silently filtered

**Returns:**
- `list`: array of product dicts
- `get`/`create`: product dict
- `update`: `{"success": true, "product_id": N, "updated_fields": [...]}`
- Error: `{"error": "..."}`

**Examples:**

```python
# List products in a project
manage_product(action="list", project_id="catalog", limit=50)

# Fetch a specific product
manage_product(action="get", product_id=42)

# Create a new product
manage_product(
    action="create",
    name="Widget Pro",
    status_id=1,
    project_id="catalog",
    price=49.99,
    currency="USD",
    code="WP-001",
)

# Update a product's price
manage_product(action="update", product_id=42, fields={"price": 39.99})
```

**Notes:**
- `list` and `get` are allowed in read-only mode; `create` and `update` are blocked when `REDMINE_MCP_READ_ONLY=true`.
- The plugin does not expose a delete endpoint, so `manage_product` has no `delete` action.

---

## Contacts and Deals / CRM (RedmineUP CRM plugin)

These tools require the **RedmineUP CRM** plugin. `manage_contact` needs `REDMINE_CRM_ENABLED=true`; `manage_deal` and `list_deal_statuses` need `REDMINE_DEALS_ENABLED=true`.

The two flags are deliberately separate. Contacts and deals are separate Redmine *project modules* (`contacts` and `deals` in the plugin's `init.rb`), each with its own permission set, so a project reachable by `manage_contact` is not necessarily reachable by `manage_deal`. More importantly, the plugin's **Light** edition ships no deals at all — no `project_module :deals`, and therefore none of the `*_deals` permissions. Redmine derives its OAuth scope list from `Redmine::AccessControl.permissions` and applies `enforce_configured_scopes`, so on a Light install a deal scope cannot be held by the OAuth application and a client requesting it fails consent with `invalid_scope`. Advertising deals under `REDMINE_CRM_ENABLED` would therefore break contacts for Light deployments; a separate flag leaves them untouched.

**Security note:** Contact PII (email, phone, address) is returned as-is to the caller but is never logged via this module's logger.

### `manage_contact`

List, get, create, update, delete, or change project association for RedmineUP CRM contacts. Replaces `list_contacts`, `get_contact`, `create_contact`, `edit_contact`, `delete_contact`, `assign_contact_to_project`, and `remove_contact_from_project`.

Requires the **RedmineUP CRM** plugin and `REDMINE_CRM_ENABLED=true`. Visibility scoping is enforced server-side by Redmine. In OAuth mode the token must also carry the CRM permissions (`view_contacts`, `view_private_contacts`, and `add_contacts` / `edit_contacts` / `delete_contacts` for writes); enabling the flag advertises them as scopes, and the OAuth application has to grant them.

**Parameters:**
- `action` (string, required): Allowed: `list`, `get`, `create`, `update`, `delete`, `assign_to_project`, `remove_from_project`
- `project_id` (integer or string): For `list`, optional project filter. For `create`, required (project to associate the new contact with). For `assign_to_project` / `remove_from_project`, the project to attach to or detach from
- `search` (string, optional): For `list`, free-text search (matches name/company/email). Redmine applies it to the page it returns without narrowing the reported total, so paging through a search is unreliable beyond the first page
- `tags` (string, optional): For `list`, comma-separated tag filter
- `assigned_to_id` (integer, optional): For `list`, filter by assignee user ID
- `limit` (integer, optional): For `list`, max results per call (default `100`, capped at 100 by Redmine)
- `offset` (integer, optional): For `list`, contacts to skip — needed to page past the first 100
- `include_pagination_info` (boolean, optional): For `list`, return `{"contacts": [...], "pagination": {...}}` instead of a bare array. Default: `false`. The same envelope and the same keys as [`list_redmine_issues`](#list_redmine_issues) -- `total`, `limit`, `offset`, `count`, `has_next`, `has_previous`, `next_offset`, `previous_offset`
- `contact_id` (integer): Required for all actions except `list` and `create`
- `include` (string, optional): For `get`, comma-separated includes (`notes`, `deals`, `contacts`)
- `first_name` (string): Required for `create`. Filters a `list` where `REDMINE_CRM_EDITION=pro`
- `last_name`, `middle_name`, `company`, `job_title`, `email`, `phone` (string, optional): For `create`, attributes of the new contact. On `list` they filter server-side, but only the CRM plugin's Pro build registers them as query filters — so they are refused unless `REDMINE_CRM_EDITION=pro`, because Redmine ignores an unregistered filter parameter silently and would answer with the whole collection rather than an error
- `author_id` (integer, optional): For `list`, filter by the ID of the user who created the contact. Also needs `REDMINE_CRM_EDITION=pro`
- `filters` (dict, optional): For `list`, additional Redmine query parameters, for filters this signature does not name — most usefully `{"cf_42": "value"}` to filter on a contact custom field. Unlike the named parameters this is not gated on `REDMINE_CRM_EDITION`, so it forwards the key without promising Redmine honours it: confirm a narrow filter actually narrowed. A contact custom field needs its **Used as a filter** setting on, and on the Light build no contact custom field is ever a registered filter. Keys this signature already names are refused — pass them as the named parameter so they are validated — as are `fields`, `f` and `query_id`, which Redmine reads as the query's own definition and which discard every filter built from the rest of the request
- `is_company` (boolean, optional): For `create`. `true` to mark as a company entity (default `false`). **Not a list filter** — the plugin's own `is_company` filter returns the same wrong set for every value, so filter the `is_company` key on the returned contacts instead
- `visibility` (integer, optional): For `create`. `0`=Project (default), `1`=Public, `2`=Private
- `fields` (dict): For `update`, fields to update. Allowed keys: `first_name`, `last_name`, `middle_name`, `company`, `job_title`, `phone`, `email`, `website`, `skype_name`, `birthday`, `background`, `address_attributes`, `tag_list`, `is_company`, `assigned_to_id`, `custom_fields`, `visibility`, `project_id`. For `create`, additional fields beyond the named parameters

**Returns:**
- `list`: array of contact dicts -- or, with `include_pagination_info=true`, `{"contacts": [...], "pagination": {...}}`
- `get`/`create`: contact dict
- `update`: `{"success": true, "contact_id": N, "updated_fields": [...]}`
- `delete`: `{"success": true, "contact_id": N, "message": ...}`
- `assign_to_project` / `remove_from_project`: `{"success": true, "contact_id": N, "project_id": ...}`
- Error: `{"error": "..."}`

A contact dict carries `custom_fields` (id/name/value), `author`, `assigned_to`, `tags`, the `emails` and `phones` arrays the CRM API renders — with `email` and `phone` holding the first entry of each — and the `address` sub-document as the plugin names it. `projects` is present only when the API sent it, which it does for a single contact and not for a collection, so an absent key means "not returned" rather than "none".

**Examples:**

```python
# List contacts in a project, filtering by tag and assignee
manage_contact(
    action="list",
    project_id="sales",
    tags="lead",
    assigned_to_id=5,
    limit=50,
)

# Page a large CRM, and see from the response how much is left
manage_contact(
    action="list",
    limit=100,
    offset=0,
    include_pagination_info=True,
)
# Returns:
# {
#   "contacts": [...],
#   "pagination": {
#     "total": 250,
#     "limit": 100,
#     "offset": 0,
#     "count": 100,
#     "has_next": true,
#     "has_previous": false,
#     "next_offset": 100,
#     "previous_offset": null
#   }
# }

# Fetch a single contact with related notes and deals
manage_contact(action="get", contact_id=42, include="notes,deals")

# Create a new contact
manage_contact(
    action="create",
    project_id="sales",
    first_name="Alice",
    last_name="Smith",
    company="ACME",
    email="alice@example.com",
    visibility=0,
)

# Update a contact's job title
manage_contact(action="update", contact_id=42, fields={"job_title": "Director"})

# Delete a contact
manage_contact(action="delete", contact_id=42)

# Add a contact to an additional project (without creating a new record)
manage_contact(action="assign_to_project", contact_id=42, project_id="support")

# Remove a contact from a project (does not delete the contact)
manage_contact(action="remove_from_project", contact_id=42, project_id="support")
```

**Notes:**
- `list` and `get` are allowed in read-only mode; `create`, `update`, `delete`, `assign_to_project`, and `remove_from_project` are blocked when `REDMINE_MCP_READ_ONLY=true`.
- **Pagination metadata.** `total` is the `total_count` the contacts response carries alongside the collection itself, so it costs no extra request and a truncated read is visible without paging until an empty page comes back. The CRM plugin renders it: `app/views/contacts/index.api.rsb` wraps the array in `api_meta(:total_count => @contacts_count, :offset => @offset, :limit => @limit)` (confirmed on 4.4.5 Pro).
- **`has_next` is measured, not guessed.** A further page exists when `offset + limit` is below the total, rather than when "the page came back full", so a collection whose size is an exact multiple of the page size is not reported as having one more page than it has. `list_redmine_issues` still infers `has_next` from a full page and can be wrong on that boundary.
- **`total` is `null` when no reported total measures the collection being paged.** Read it as "not reported", never as a number. Two cases produce it. A build that renders no `total_count` at all is one. The other is `search`: `ContactsController#index` counts with `@query.object_count`, which applies the query filters but *not* `params[:search]` -- `ContactQuery` registers no `search` filter -- while the rows come from `results_scope(:search => ...)`. The reported total therefore describes the collection before the search, so it is not offered as this page's total. Every other narrowing parameter this tool sends (`project_id`, `tags`, `assigned_to_id`, `author_id` and the Pro attribute filters) *is* a registered filter, so those narrow the count too and `total` stays exact. Whenever `total` is `null`, `has_next` falls back to the full-page inference rather than going `null` too, because a `null` is falsy and a caller testing it would stop mid-collection.
- **What the other keys mean.** `count` is the contacts actually returned in this response. `limit` and `offset` are the window Redmine reports having applied, falling back to the requested values when it reports none, so `next_offset` lands on a real page boundary even if a build serves a smaller page than was asked for. `has_previous` and `previous_offset` follow `offset` alone and never depend on the total.
- **PII handling:** contact `email`, `phone`, `address`, `birthday`, `website` are returned as-is to the caller; the module never logs them. Error messages reference only `contact_id`.
- **Prompt-injection wrapping:** `background` is free text and is wrapped in `<insecure-content>` boundary tags. Display fields (`first_name`, `last_name`, `middle_name`, `company`, `job_title`, `assigned_to.name`), and the `address` sub-document are returned verbatim, matching the policy set in #109 for short label-shaped values elsewhere in the server. Custom field values are returned verbatim too, consistent with issue custom fields — but note a `text`-format field holds free text rather than a short label, so treat those as untrusted.

### `manage_deal`

List, get, create, update, or delete RedmineUP CRM deals.

Requires the **RedmineUP CRM** plugin in its **Pro** edition, `REDMINE_DEALS_ENABLED=true`, and the `deals` project module enabled on the project. Visibility scoping is enforced server-side by Redmine. In OAuth mode the token must also carry the deal permissions (`view_deals`, plus `add_deals` / `edit_deals` / `delete_deals` for writes); enabling the flag advertises them as scopes, and the OAuth application has to grant them.

**Parameters:**
- `action` (string, required): Allowed: `list`, `get`, `create`, `update`, `delete`
- `project_id` (integer or string): For `list`, optional project filter. For `create`, required (project to create the deal in)
- `search` (string, optional): For `list`, free-text search (matches the deal name)
- `status_id` (integer or string, optional): For `list`, filter by deal status. A numeric id, or one of `"o"` (open, the default Redmine applies anyway), `"c"` (won/lost), `"*"` (any status). For `create`, the status to open the deal in (numeric id only)
- `assigned_to_id` (integer, optional): For `list`, filter by assignee user ID
- `limit` (integer, optional): For `list`, max results per call (default `100`, capped at 100 by Redmine)
- `deal_id` (integer): Required for `get`, `update`, and `delete`
- `include` (string, optional): For `get`, comma-separated includes (`notes`)
- `name` (string): Required for `create`
- `contact_id` (integer, optional): For `create`, the contact the deal belongs to
- `assigned_to_id` (integer, optional): For `list`, filter by assignee. For `create`, the user to assign the new deal to
- `price` (number or string, optional), `currency` (string, optional), `due_date` (string, optional): For `create`
- `fields` (dict): For `update`, fields to update. Allowed keys: `name`, `background`, `currency`, `price`, `price_type`, `duration`, `project_id`, `author_id`, `assigned_to_id`, `status_id`, `contact_id`, `category_id`, `probability`, `due_date`, `custom_field_values`, `custom_fields`, `watcher_user_ids`. For `create`, additional fields beyond the named parameters

**Returns:**
- `list`: array of deal dicts
- `get`/`create`: deal dict with `id`, `name`, `price`, `currency`, `price_type`, `duration`, `probability`, `due_date`, `background`, `project`, `status`, `category`, `author`, `contact`, `assigned_to`, `related_contacts`, `created_on`, `updated_on`. A `notes` key is added only when `include="notes"` was requested and the plugin returned notes, so its absence means "not requested" rather than "none". `custom_fields` is accepted on writes but not returned, matching `manage_contact`, `manage_product` and `manage_document`
- `update`: `{"success": true, "deal_id": N, "updated_fields": [...]}`
- `delete`: `{"success": true, "deal_id": N, "message": ...}`
- Error: `{"error": "..."}`

**Examples:**

```python
# List open deals in a project for one assignee (open is Redmine's default)
manage_deal(action="list", project_id="sales", assigned_to_id=5, limit=50)

# Every deal regardless of status, including won and lost
manage_deal(action="list", project_id="sales", status_id="*")

# Fetch a single deal with its notes
manage_deal(action="get", deal_id=9, include="notes")

# Create a deal against a contact
manage_deal(
    action="create",
    project_id="sales",
    name="ACME renewal",
    contact_id=42,
    price="1500",
    currency="USD",
    due_date="2026-12-01",
)

# Move a deal to another status
manage_deal(action="update", deal_id=9, fields={"status_id": 3})

# Delete a deal
manage_deal(action="delete", deal_id=9)
```

**Notes:**
- `list` and `get` are allowed in read-only mode; `create`, `update`, and `delete` are blocked when `REDMINE_MCP_READ_ONLY=true`.
- **`list` returns only OPEN deals unless you ask for more.** `DealQuery` seeds itself with a `status_id` filter on operator `o`, the same default `/issues.json` applies, so won and lost deals are absent from an unfiltered call. Pass `status_id="*"` for all statuses, `"c"` for won and lost, or a numeric id for one status — `status_id` is a `:list_status` filter, so Redmine accepts those operators alongside a plain id.
- **All five actions require `view_deals`.** `deals#index` is excluded from `before_action :authorize` but then runs `find_optional_project`, whose Redmine implementation calls `authorize_global`, so it is authorized too — a caller without the permission gets a permission error, not an empty list. `Deal.visible` narrows what a permitted caller sees; it does not substitute for the check.
- **`price` is sent as a string.** The plugin parses it with `String#gsub!` against the instance's configured thousands and decimal separators, so a JSON number raises `NoMethodError` server-side. Pass an unformatted value such as `"1500.5"`; pre-formatted input is reinterpreted per those settings.
- **`status_id` and `category_id` are not discoverable through this server.** The plugin's `GET /deal_statuses.json` is `require_admin`, so a non-admin token cannot list statuses; deal categories are per-project. Read the IDs off an existing deal's `status` and `category` refs instead.
- `background` is wrapped in `<insecure-content>` boundary tags so downstream LLMs treat it as untrusted data. `name` and the `id`/`name` refs are short label-shaped fields and are returned verbatim, matching `subject` on issues.

---

### `list_deal_statuses`

List RedmineUP CRM deal statuses and, for a given project, its deal categories. Call it before `manage_deal(action="create")`, which needs a numeric `status_id`.

Requires `REDMINE_DEALS_ENABLED=true` and the CRM plugin's **Pro** edition. Read-only (`readOnlyHint=true`).

**Parameters:**
- `project_id` (integer or string, optional): when given, the project's deal categories are included.

**Returns:**
- `statuses`: list of `{id, name, position, is_default, status_type, status_type_id, color}` ordered by position; `status_type` is `open`, `won` or `lost`.
- `categories`: list of `{id, name}`; present only when `project_id` was given.
- `project_id`: echoed back when given.

**Admin-only statuses:** the plugin's `DealStatusesController#index` is restricted to Redmine administrators (`require_admin`), which no permission or OAuth scope can grant. For a non-admin user `statuses` is `null` and `statuses_error` explains why, while `categories` is still returned. Status ids can then be read off existing deals via `manage_deal(action="list", status_id="*")`.

**Example:**
```json
{"statuses": [{"id": 1, "name": "New", "position": 1, "is_default": true, "status_type": "open", "status_type_id": 0, "color": "FFFFFF"}],
 "categories": [{"id": 3, "name": "Enterprise"}],
 "project_id": "sales"}
```

### `manage_crm_note`

Get, create, update, or delete RedmineUP CRM notes, the activity log attached to contacts and deals.

Available when `REDMINE_CRM_ENABLED=true` or `REDMINE_DEALS_ENABLED=true`. A note on a deal additionally requires deals enabled; a note on a contact requires CRM enabled. `get`, `update` and `delete` look the note up first and apply the same rule to its actual source, so a bare `note_id` cannot reach a disabled family. There is no list action: read a parent's notes with `manage_deal(action="get", include="notes")`.

**Parameters:**
- `action` (string, required): `get`, `create`, `update`, `delete`
- `note_id` (integer): required for `get`, `update`, `delete`
- `source_type` (string): `create` only, required: `contact` or `deal`
- `source_id` (integer): `create` only, required
- `project_id` (integer or string): `create` only, required. The plugin resolves the note's project from it and answers 404 without it
- `content` (string): required on `create`, optional on `update`
- `subject` (string, optional)
- `type_id` (integer, optional): `0` email, `1` call, `2` meeting

**Returns:** `get`/`create` a note dict `{id, source {id, name, type}, subject, content, type_id, note_type, author, created_on, updated_on}` (`content` is wrapped in `<insecure-content>` boundary tags, timestamps are ISO-8601); `update` `{success, note_id, updated_fields}`; `delete` `{success, note_id, message}`.

**Permissions:** the plugin checks `delete_notes` (or `delete_own_notes` for the author) for both editing and deleting. In OAuth mode enabling either CRM flag advertises `add_notes`, `delete_notes` and `delete_own_notes` as scopes.

**Example:**
```json
{"action": "create", "source_type": "deal", "source_id": 12, "project_id": "sales", "content": "Called, they want a revised quote by Friday.", "type_id": 1}
```

## Documents (DMSF plugin)

This section requires the **`redmine_dmsf`** plugin (GPL v2, open-source) installed on the Redmine server, and `REDMINE_DMSF_ENABLED=true`. DMSF *replaces* Redmine's built-in (web-UI-only) Documents module with a full document-management system that exposes a REST API.

### `manage_document`

Combined DMSF CRUD tool. **Action-dispatched** — pass `action="list"|"get"|"create"|"update"`.

**Parameters (per action):**

| Action | Required | Optional |
|---|---|---|
| `list` | `project_id` | `folder_id`, `limit` (1–100) |
| `get` | `document_id` | – |
| `create` | `project_id`, `filename`, `content_base64` | `title`, `description`, `comment`, `folder_id`, `version`, `custom_fields` |
| `update` | `document_id`, `fields` | – |

**Common parameter types:**

- `project_id`: `int` or `string` (Redmine project identifier).
- `folder_id`, `document_id`: positive `int`.
- `filename`: `string`. Used as the initial filename on `create`; can be changed later by passing `name` in `update`'s `fields` (DMSF renames the parent file when a revision's `name` differs). **Sent to DMSF as the `name` key** inside `attachments.uploaded_file` — the upload helper reads `committed_file[:name]`, not `[:filename]`.
- `content_base64`: `string` (raw file bytes encoded as base64). Decoded payload is capped at **50 MiB**.
- `version` (for `create`): semantic version string for the new revision, e.g. `"1.0"` or `"1.2.3"`. Accepts `"X"`, `"X.Y"`, or `"X.Y.Z"`; missing parts are padded with `"0"`. Each part must be a non-negative integer. DMSF stores `major_version` / `minor_version` / `patch_version` as separate integer columns; the tool splits on `.` before sending.
- `custom_fields`: list of `{"id": N, "value": ...}` dicts. Sent to DMSF as `custom_field_values` (the API's internal key).
- `fields` (for `update`): dict with any subset of the writable keys: `title`, `name` (rename), `description`, `comment`, `custom_fields`. Unknown keys are silently filtered out.

**Returns:**

- `list`: list of node dicts. Each node has `id`, `type` (`file` / `folder` / `file-link` / `folder-link`), `filename`, `title`, `name`, `description`, `version`, `size`, `content_type`, `folder_id`, `project_id`, `author` (`{id, name}`), `created_on`, `updated_on`.
- `get`: a single node dict with the same shape. Most metadata (`description`, `size`, `version`, `mime_type`, `user_id`, timestamps) is pulled from the latest entry of `dmsf_file_revisions[]` — see the design notes below.
- `create`: a **sparse** dict containing only `id` + `name` (plus a `note` pointing at `action="get"` for full metadata). DMSF's commit endpoint deliberately returns id + name only; call `get` if you need description/size/version/timestamps. Returns `{"success": True}` if the response is unexpectedly empty.
- `update`: `{"success": True, "document_id": N, "updated_fields": [...], "note": "DMSF created a new revision; previous revisions remain accessible via the document's revision history."}`.
- Any failure: `{"error": "..."}`.

**Examples:**

```python
# List documents in a project
manage_document(action="list", project_id="docs", limit=50)

# List documents inside a specific DMSF folder
manage_document(action="list", project_id="docs", folder_id=12)

# Get metadata for one document
manage_document(action="get", document_id=42)

# Upload a new document with an explicit initial version
import base64
content_b64 = base64.b64encode(open("spec.pdf", "rb").read()).decode()
manage_document(
    action="create",
    project_id="docs",
    filename="spec.pdf",       # sent to DMSF as `name` (the helper reads :name)
    content_base64=content_b64,
    title="Specification",
    description="Initial draft",
    comment="Created from CLI",
    version="0.1",             # split into version_major / version_minor / version_patch
)

# Update metadata (creates a new revision — DMSF is versioned)
manage_document(
    action="update",
    document_id=42,
    fields={"title": "Specification v2", "description": "Updated draft"},
)

# Rename a document (DMSF assigns the revision's `name` back to the parent file)
manage_document(
    action="update",
    document_id=42,
    fields={"name": "spec-v2.pdf"},
)
```

**DMSF design notes:**

- **Every update creates a new revision.** DMSF is a versioned document system — there is no in-place mutation. Previous revisions remain accessible via the document's revision history in the Redmine UI.
- **Required-field auto-population on `update`.** DMSF's revision-create controller crashes (`NoMethodError` on `nil.scrub`) if either `title` or `name` is missing. To make `update` ergonomic when the caller only wants to change `description`, the tool pre-fetches the current document via `GET /dmsf_files/{id}.json` and uses the existing `title`/`name` as defaults. The caller's overrides take precedence.
- **Renaming.** Set `fields["name"]` on `update` to rename the document; DMSF propagates the new name to the parent file. The list-shape `filename` field cannot be used in `update` — only the canonical `name` key.
- **Sparse `create` response.** The commit endpoint intentionally returns only `id` + `name` (plus a `total_count`). For full metadata, follow up with `action="get"` using the returned `id`.
- **Two response shapes for the same document.** `list` returns flat nodes; `get` nests most metadata under `dmsf_file_revisions[]`. The serializer merges both into one stable representation.
- **Version on `create`, not on `update`.** Pass a semantic `version` string (e.g. `"1.2.3"`) on `create` to set the initial revision's version. The tool splits the string into `version_major` / `version_minor` / `version_patch` and nests them inside `attachments.uploaded_file` (where DMSF's commit helper reads them). `update` does **not** expose version control — DMSF auto-increments the patch version when a new revision is created via `dmsf_files#create_revision`. Use the Redmine web UI if you need explicit semantic version control on existing documents. (Why the asymmetry? DMSF's two endpoints read the version fields from different places: `commit` reads them nested inside `uploaded_file`, while `create_revision` reads them from top-level `params`. The MCP tool covers the more common case — version-at-upload-time.)
- **DMSF replaces the built-in Documents module** rather than complementing it. If your Redmine instance has existing native documents, the server admin must run `rake redmine:dmsf_convert_documents` to migrate them before they're accessible here.
- **HTTP endpoint paths used** (visible in raw error messages):
  - `GET /projects/{id}/dmsf.json` — list
  - `GET /dmsf_files/{id}.json` — get (legacy path is preserved for show)
  - `POST /uploads.json` then `POST /projects/{id}/dmsf/commit.json` — create
  - `POST /dmsf/files/{id}/revision/create.json` — update (note slash, not underscore: `dmsf/files`, not `dmsf_files`)
- If you see a 404 on these endpoints, the `redmine_dmsf` plugin is not installed (or is too old to expose the REST API); double-check the server with `bundle exec rake redmine:plugins:migrate RAILS_ENV=production` after installation.

**Notes:**
- `list` and `get` are allowed in read-only mode; `create` and `update` are blocked when `REDMINE_MCP_READ_ONLY=true`.
- Per the #109 wrap policy, `description` is free-text and is wrapped in `<insecure-content>` boundary tags; `filename`, `name`, `title`, and `author.name` are structured metadata and are returned verbatim.

---

## Meta

### `get_mcp_server_info`

Return the MCP server's version, enabled-feature flags, and the identity of the authenticated Redmine user. Use this tool to detect deployment lag (the running server may be behind a recently-shipped patch) before relying on a fix that landed on `develop` (compare `server_version` against the release / commit you expect), and to confirm who `assigned_to_id="me"` resolves to.

**Parameters:** None

**Returns:**
- `server_version` (string): the deployed package version (from `importlib.metadata`). The literal `"0.0.0+unknown"` when the package metadata is unavailable (rare; source-tree runs without an editable install).
- `read_only_mode` (boolean): whether `REDMINE_MCP_READ_ONLY` is enabled. When `True`, all write tools refuse with the standard read-only error.
- `auth_mode` (string): `"oauth"` or `"legacy"`.
- `current_user` (dict or null): `{id, login, name}` for the authenticated Redmine user behind the configured API key. `null` when the server cannot reach Redmine (check `/health` for connectivity status). Use this to confirm who `assigned_to_id="me"` resolves to, which matters when a shared or robot API key is in use.
- `plugin_flags` (dict): which plugin-gated tool families are enabled. Keys: `agile`, `checklists`, `products`, `crm`, `deals`, `dmsf`, `tags`. `True` means the family's tools are listed and routable and will reach the underlying plugin endpoints (for `tags`, that `get_redmine_issue` returns a `tags` array); `False` means they are hidden from `tools/list` (calling them by name returns "Unknown tool"), except for `agile` and `tags`, which only add fields to core tools and are never hidden (for `tags`, the field is simply omitted).

The response intentionally excludes credentials, internal hostnames, file-system paths, and any other operator config that a caller doesn't need to know to choose its call shape. Only flags that change *call shape* are surfaced.

**Example:**
```json
{
    "server_version": "1.3.0",
    "read_only_mode": false,
    "auth_mode": "legacy",
    "current_user": {"id": 5, "login": "jdoe", "name": "Jane Doe"},
    "plugin_flags": {
        "agile": false,
        "checklists": false,
        "products": false,
        "crm": false,
        "dmsf": true,
        "tags": false
    }
}
```

**When to call:**
- Before re-probing a recently-shipped fix to confirm the deployment has caught up.
- Before relying on a plugin-gated tool (`manage_contact`, `manage_product`, `manage_document`, `get_checklist`, etc.) — `plugin_flags` tells you whether the call will succeed or return "feature disabled".
- Before adapting to `auth_mode` if your caller has different code paths for OAuth vs legacy.
- When `list_redmine_issues(assigned_to_id="me")` returns unexpectedly empty results: `current_user` shows the identity behind the configured API key, which may be a shared or robot account rather than the human operator.
