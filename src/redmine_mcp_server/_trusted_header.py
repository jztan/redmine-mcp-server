"""Trusted-header auth: run each request as the Redmine user that an
authenticating proxy names in a request header.

Active only when ``REDMINE_AUTH_MODE=trusted-header``. A proxy in front of
this server (for example an SSO gateway) has already authenticated the user
and names them in ``REDMINE_TRUSTED_HEADER_NAME`` (default
``X-Forwarded-User``): by Redmine login, or, with
``REDMINE_TRUSTED_HEADER_MATCH=mail``, by the email address of an active
Redmine user. Every Redmine call then uses one administrator API key plus
``X-Redmine-Switch-User: <login>``, so Redmine applies that user's own
permissions.

The server cannot tell a header the proxy set from one a client forged, so
that trust is operator-attested via ``REDMINE_TRUSTED_HEADER_TRUST_PROXY``
(enforced at startup, see ``assert_startup_requirements``): only the proxy
can reach this server, and it overwrites the header on every request. The
proxy also proves itself with ``REDMINE_TRUSTED_HEADER_SECRET`` in
``X-Trusted-Proxy-Secret``, which ``TrustedHeaderMiddleware`` checks.

Redmine honours ``X-Redmine-Switch-User`` only for an administrator's key and
silently ignores it for any other key, which would run every request as the
key's own account. The server therefore refuses to start unless Redmine
confirms that the key belongs to an administrator, and checks again before
every request, because the account can lose that role while the server runs.

The API key is NEVER logged.
"""

import logging
import os
import re
from typing import Optional

import requests
from starlette.responses import Response
from starlette.routing import get_route_path

from ._api_key_login import _constant_time_equal
from ._per_user import PerUserAuthError, _extract_header

logger = logging.getLogger("redmine_mcp_server")

DEFAULT_HEADER_NAME = "X-Forwarded-User"
DEFAULT_SECRET_HEADER_NAME = "X-Trusted-Proxy-Secret"
MATCH_MODES = ("login", "mail")

# Both set once by assert_startup_requirements: the secret because get_secret
# would read a _FILE again on every call, the key owner's id because no
# request ever runs as that account.
_TRUSTED_HEADER_SECRET: Optional[str] = None
_KEY_OWNER_ID: Optional[int] = None


def _allow_admin() -> bool:
    from ._env import _is_true_env

    return _is_true_env("REDMINE_TRUSTED_HEADER_ALLOW_ADMIN")


# Redmine's own login rule (User model: /\A[a-z0-9_\-@\.]*\z/i, at most
# LOGIN_LENGTH_LIMIT = 60 characters). Anything else cannot name a Redmine
# user, so it is rejected before it reaches Redmine.
_LOGIN_RE = re.compile(r"[a-z0-9_\-@.]{1,60}", re.IGNORECASE | re.ASCII)

# Redmine's own email rule (EmailAddress model: Ruby's
# URI::MailTo::EMAIL_REGEXP, at most User::MAIL_LENGTH_LIMIT = 254
# characters), applied for the same reason.
_MAIL_RE = re.compile(
    r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*"
)
_MAIL_MAX_LENGTH = 254

# The user lookup reads GET /users.json 100 users at a time, the most Redmine
# returns per page, and gives up after 10 pages (1,000 matching users).
_LOOKUP_PAGE_SIZE = 100
_LOOKUP_MAX_PAGES = 10


def _header_name() -> str:
    """Return the name of the header that names the user."""
    return os.getenv("REDMINE_TRUSTED_HEADER_NAME", "").strip() or DEFAULT_HEADER_NAME


def _match_mode() -> str:
    """Return how the header names the user: ``login`` or ``mail``."""
    return os.getenv("REDMINE_TRUSTED_HEADER_MATCH", "").strip().lower() or "login"


def _count_header_in_scope(scope: dict, name: str) -> int:
    """Count occurrences of header ``name`` in ASGI ``scope['headers']``,
    case-insensitive.
    """
    if not isinstance(scope, dict):
        return 0
    raw_headers = scope.get("headers")
    if not raw_headers:
        return 0
    target_bytes = name.lower().encode("latin-1")
    target_str = name.lower()
    count = 0
    for raw_k, _ in raw_headers:
        if isinstance(raw_k, (bytes, bytearray)):
            if raw_k.lower() == target_bytes:
                count += 1
        elif str(raw_k).lower() == target_str:
            count += 1
    return count


def _extract_header_from_scope(scope: dict, name: str) -> Optional[str]:
    """Extract first value of header ``name`` from ASGI ``scope['headers']``,
    case-insensitive.
    """
    if not isinstance(scope, dict):
        return None
    raw_headers = scope.get("headers")
    if not raw_headers:
        return None
    target_bytes = name.lower().encode("latin-1")
    target_str = name.lower()
    for raw_k, raw_v in raw_headers:
        matched = False
        if isinstance(raw_k, (bytes, bytearray)):
            if raw_k.lower() == target_bytes:
                matched = True
        elif str(raw_k).lower() == target_str:
            matched = True
        if matched:
            if isinstance(raw_v, (bytes, bytearray)):
                return raw_v.decode("latin-1")
            return str(raw_v)
    return None


class TrustedHeaderMiddleware:
    """Pure ASGI middleware verifying X-Trusted-Proxy-Secret on all HTTP routes
    except GET/HEAD /health.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        if method in ("GET", "HEAD") and get_route_path(scope) == "/health":
            await self.app(scope, receive, send)
            return

        if _count_header_in_scope(scope, DEFAULT_SECRET_HEADER_NAME) != 1:
            response = Response("Unauthorized", status_code=401)
            await response(scope, receive, send)
            return

        secret_val = _extract_header_from_scope(scope, DEFAULT_SECRET_HEADER_NAME)
        if secret_val is None:
            response = Response("Unauthorized", status_code=401)
            await response(scope, receive, send)
            return

        # No comma check, unlike the user header: the secret may contain a
        # comma, and a value merged from two headers can never equal it.
        expected_secret = _TRUSTED_HEADER_SECRET
        if not expected_secret or not _constant_time_equal(expected_secret, secret_val):
            response = Response("Unauthorized", status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def validate_trusted_request(request) -> tuple[str, str]:
    """Sync, no-I/O check of the proxy secret, header uniqueness, and user format.

    Returns ``(user_value, match_mode)``.
    Raises ``PerUserAuthError`` on any violation.
    """
    if request is None:
        raise PerUserAuthError(
            "Trusted-header auth requires an HTTP request context but none was found."
        )

    scope = getattr(request, "scope", None)
    if isinstance(request, dict) and "headers" in request:
        scope = request

    # Check secret header
    if scope is not None and "headers" in scope:
        secret_count = _count_header_in_scope(scope, DEFAULT_SECRET_HEADER_NAME)
        if secret_count > 1:
            raise PerUserAuthError(
                f"Trusted-header auth: repeated {DEFAULT_SECRET_HEADER_NAME} "
                "request header."
            )
        if secret_count < 1:
            raise PerUserAuthError(
                f"Trusted-header auth: missing {DEFAULT_SECRET_HEADER_NAME} "
                "request header."
            )

    secret_val = _extract_header(request, DEFAULT_SECRET_HEADER_NAME)
    if secret_val is None:
        raise PerUserAuthError(
            f"Trusted-header auth: missing {DEFAULT_SECRET_HEADER_NAME} "
            "request header."
        )

    # No comma check for the secret, as in TrustedHeaderMiddleware.
    expected_secret = _TRUSTED_HEADER_SECRET
    if not expected_secret or not _constant_time_equal(expected_secret, secret_val):
        raise PerUserAuthError("Trusted-header auth: invalid proxy secret.")

    # Check user header
    name = _header_name()
    if scope is not None and "headers" in scope:
        if _count_header_in_scope(scope, name) > 1:
            raise PerUserAuthError(
                f"Trusted-header auth: repeated {name} request header."
            )

    value = _extract_header(request, name)
    if value is None:
        raise PerUserAuthError(f"Trusted-header auth: missing {name} request header.")
    if "," in value:
        raise PerUserAuthError(f"Trusted-header auth: repeated {name} request header.")

    mode = _match_mode()
    if mode == "mail":
        if len(value) > _MAIL_MAX_LENGTH or not _MAIL_RE.fullmatch(value):
            raise PerUserAuthError(
                f"Trusted-header auth: the {name} header is not a valid email address."
            )
    elif not _LOGIN_RE.fullmatch(value):
        raise PerUserAuthError(
            f"Trusted-header auth: the {name} header is not a valid Redmine login."
        )

    return value, mode


def resolve_trusted_login(request) -> str:
    """Return the Redmine login of the user the proxy named, or raise
    PerUserAuthError.

    Validates proxy secret and headers, checks whether user exists, is active,
    is not administrator (unless REDMINE_TRUSTED_HEADER_ALLOW_ADMIN=true),
    and is not key owner.
    Resolved once per HTTP request; kept on request.state.trusted_header_login.
    """
    value, mode = validate_trusted_request(request)

    state = getattr(request, "state", None)
    if state is not None:
        login = getattr(state, "trusted_header_login", None)
        if login is not None:
            return login

    from . import _client

    login = _lookup_user(value, mode, _client.REDMINE_API_KEY)
    if state is not None:
        state.trusted_header_login = login

    logger.info("trusted-header request as login=%s", login)
    return login


def _redmine_get(path: str, key: str, params=None) -> requests.Response:
    """GET ``path`` on Redmine with ``key``.

    Same TLS/proxy settings and timeout as the Redmine client; redirects are
    not followed, so the key never leaves for another host. Transport errors
    propagate to the caller.
    """
    from . import _client
    from ._env import get_redmine_timeout

    url = _client.REDMINE_URL.rstrip("/") + path
    with requests.Session() as session:
        for name, value in _client._build_requests_config().items():
            setattr(session, name, value)
        return session.get(
            url,
            headers={"X-Redmine-API-Key": key},
            params=params,
            timeout=get_redmine_timeout(),
            allow_redirects=False,
        )


def _lookup_user(value: str, mode: str, api_key: str) -> str:
    """Query Redmine GET /users.json?name=<value>&status=1 with the admin key.

    Returns the matching user's login, or raises PerUserAuthError.
    """
    wanted = value.lower()
    users: list[dict] = []
    offset = 0

    for _ in range(_LOOKUP_MAX_PAGES):
        params = [
            ("name", value),
            ("status", "1"),
            ("limit", str(_LOOKUP_PAGE_SIZE)),
        ]
        if offset > 0:
            params.append(("offset", str(offset)))

        response = _redmine_get("/users.json", api_key, params=params)

        if response.status_code in (401, 403):
            raise PerUserAuthError(
                "Trusted-header auth: Redmine refused the user lookup. "
                "Listing users needs REDMINE_API_KEY to belong to an administrator."
            )
        if not 200 <= response.status_code < 300:
            raise PerUserAuthError(
                "Trusted-header auth: the user lookup returned HTTP "
                f"{response.status_code}."
            )

        try:
            data = response.json()
            page_users = data.get("users")
            total_count = data.get("total_count")
        except (ValueError, AttributeError):
            raise PerUserAuthError(
                "Trusted-header auth: the user lookup returned an unexpected response."
            )

        if not isinstance(page_users, list):
            raise PerUserAuthError(
                "Trusted-header auth: the user lookup returned an unexpected response."
            )

        users.extend(page_users)

        if total_count is not None and isinstance(total_count, int):
            if len(users) >= total_count:
                break
        elif len(page_users) < _LOOKUP_PAGE_SIZE:
            break

        offset += _LOOKUP_PAGE_SIZE
    else:
        raise PerUserAuthError(
            "Trusted-header auth: the user lookup exceeded maximum page limit "
            "(too many matching users)."
        )

    exact_matches: list[dict] = []
    for u in users:
        if not isinstance(u, dict):
            continue
        if mode == "mail":
            u_mail = u.get("mail")
            if isinstance(u_mail, str) and u_mail.lower() == wanted:
                exact_matches.append(u)
        else:
            u_login = u.get("login")
            if isinstance(u_login, str) and u_login.lower() == wanted:
                exact_matches.append(u)

    if not exact_matches:
        label = "email" if mode == "mail" else "login"
        raise PerUserAuthError(
            f"Trusted-header auth: no active Redmine user has the {label} {value}."
        )

    if len(exact_matches) > 1:
        label = "email" if mode == "mail" else "login"
        raise PerUserAuthError(
            "Trusted-header auth: several active Redmine users have the "
            f"{label} {value}."
        )

    matched = exact_matches[0]
    matched_id = matched.get("id")
    matched_login = matched.get("login")
    is_admin = matched.get("admin")

    # Redmine (4.0 and newer) sends all three; refuse rather than guess.
    if (
        not isinstance(matched_id, int)
        or not isinstance(matched_login, str)
        or not matched_login
        or not isinstance(is_admin, bool)
    ):
        raise PerUserAuthError(
            "Trusted-header auth: the user lookup returned an unexpected response."
        )

    if _KEY_OWNER_ID is None:
        # Recorded at startup; without it the key owner cannot be told apart.
        raise PerUserAuthError(
            "Trusted-header auth: the account that owns REDMINE_API_KEY is "
            "unknown, so no request can run."
        )
    if matched_id == _KEY_OWNER_ID:
        raise PerUserAuthError(
            "Trusted-header auth: refusing to run request as the account that "
            "owns REDMINE_API_KEY."
        )

    if is_admin and not _allow_admin():
        raise PerUserAuthError(
            "Trusted-header auth: refusing to run request as administrator "
            f"{matched_login!r} (REDMINE_TRUSTED_HEADER_ALLOW_ADMIN is false)."
        )

    return matched_login


def _probe_admin_key(key: str) -> tuple[int, Optional[bool], Optional[int]]:
    """GET /users/current.json with ``key``; return (status, admin, user_id).

    The flag is ``None`` unless Redmine answered 2xx with a boolean
    ``user.admin``, and the id ``None`` unless it answered with an integer
    ``user.id``. Transport errors propagate to the caller.
    """
    response = _redmine_get("/users/current.json", key)
    admin = None
    user_id = None
    if 200 <= response.status_code < 300:
        try:
            user_data = response.json().get("user", {})
            value = user_data.get("admin")
            uid = user_data.get("id")
        except (ValueError, AttributeError):
            value = None
            uid = None
        if isinstance(value, bool):
            admin = value
        if isinstance(uid, int):
            user_id = uid
    return response.status_code, admin, user_id


def _verify_admin_key(error: type[Exception] = RuntimeError) -> None:
    """Raise ``error`` unless Redmine confirms that REDMINE_API_KEY belongs
    to an administrator, and record that account's id in ``_KEY_OWNER_ID``.

    Transport errors from the probe propagate unchanged, so each caller
    decides how an unreachable Redmine is reported.
    """
    from . import _client

    status, admin, user_id = _probe_admin_key(_client.REDMINE_API_KEY)

    if status == 401:
        raise error(
            "REDMINE_AUTH_MODE=trusted-header: Redmine rejected REDMINE_API_KEY."
        )
    if not 200 <= status < 300:
        raise error(
            "REDMINE_AUTH_MODE=trusted-header: could not check REDMINE_API_KEY; "
            f"GET /users/current.json returned HTTP {status}."
        )
    if admin is not True:
        raise error(
            "REDMINE_AUTH_MODE=trusted-header requires REDMINE_API_KEY to "
            "belong to a Redmine administrator, and Redmine did not confirm "
            "that it does. Redmine ignores X-Redmine-Switch-User for any "
            "other key, so every request would run as the key's own account "
            "instead of the user named in the header."
        )
    if user_id is None:
        raise error(
            "REDMINE_AUTH_MODE=trusted-header: Redmine did not return the id of "
            "the account that owns REDMINE_API_KEY. The server needs it to make "
            "sure no request ever runs as that account."
        )
    global _KEY_OWNER_ID
    _KEY_OWNER_ID = user_id


def assert_startup_requirements() -> None:
    """Fail closed unless the mode is attested and its key can switch users.

    Called once at app build time when REDMINE_AUTH_MODE=trusted-header.
    """
    from . import _client
    from ._env import _is_true_env, get_required_secret

    if not _is_true_env("REDMINE_TRUSTED_HEADER_TRUST_PROXY"):
        raise RuntimeError(
            "REDMINE_AUTH_MODE=trusted-header requires "
            "REDMINE_TRUSTED_HEADER_TRUST_PROXY=true. This attests that only "
            "your authenticating proxy can reach this server and that the "
            f"proxy overwrites the {_header_name()} header on every request. "
            "The server cannot tell a forged header from a real one."
        )

    if _match_mode() not in MATCH_MODES:
        raise RuntimeError(
            "REDMINE_TRUSTED_HEADER_MATCH must be 'login' or 'mail', not "
            f"{_match_mode()!r}."
        )
    if not _client.REDMINE_URL:
        raise RuntimeError("REDMINE_AUTH_MODE=trusted-header requires REDMINE_URL.")
    if not _client.REDMINE_API_KEY:
        raise RuntimeError(
            "REDMINE_AUTH_MODE=trusted-header requires REDMINE_API_KEY, the "
            "API key of a Redmine administrator."
        )

    global _TRUSTED_HEADER_SECRET
    secret = get_required_secret(
        "REDMINE_TRUSTED_HEADER_SECRET",
        error_text="A 32+ character ASCII secret shared with the authenticating proxy.",
    )
    if len(secret) < 32:
        raise RuntimeError(
            "REDMINE_AUTH_MODE=trusted-header requires REDMINE_TRUSTED_HEADER_SECRET "
            "to be at least 32 characters."
        )
    if not all(0x21 <= ord(c) <= 0x7E for c in secret):
        raise RuntimeError(
            "REDMINE_AUTH_MODE=trusted-header requires REDMINE_TRUSTED_HEADER_SECRET "
            "to contain only printable ASCII characters without spaces."
        )
    _TRUSTED_HEADER_SECRET = secret
    try:
        _verify_admin_key()
    except requests.RequestException as exc:
        raise RuntimeError(
            "REDMINE_AUTH_MODE=trusted-header: could not reach Redmine to check "
            f"REDMINE_API_KEY ({type(exc).__name__})."
        ) from exc
    logger.warning(
        "trusted-header auth is ACTIVE: every request runs as the Redmine user "
        "whose %s is in the %s header, through an administrator API key. Only "
        "your authenticating proxy may reach this server, and it must "
        "overwrite that header on every request.",
        "email" if _match_mode() == "mail" else "login",
        _header_name(),
    )
