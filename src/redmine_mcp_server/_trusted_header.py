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
can reach this server, and it overwrites the header on every request.

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

from ._per_user import PerUserAuthError, _extract_header

logger = logging.getLogger("redmine_mcp_server")

DEFAULT_HEADER_NAME = "X-Forwarded-User"
MATCH_MODES = ("login", "mail")

# Redmine's own login rule (User model: /\A[a-z0-9_\-@\.]*\z/i, at most
# LOGIN_LENGTH_LIMIT = 60 characters). Anything else cannot name a Redmine
# user, so it is rejected before it reaches Redmine.
_LOGIN_RE = re.compile(r"[a-z0-9_\-@.]{1,60}", re.IGNORECASE)

# Redmine's own email rule (EmailAddress model: Ruby's
# URI::MailTo::EMAIL_REGEXP, at most User::MAIL_LENGTH_LIMIT = 254
# characters), applied for the same reason.
_MAIL_RE = re.compile(
    r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*"
)
_MAIL_MAX_LENGTH = 254


def _header_name() -> str:
    """Return the name of the header that names the user."""
    return os.getenv("REDMINE_TRUSTED_HEADER_NAME", "").strip() or DEFAULT_HEADER_NAME


def _match_mode() -> str:
    """Return how the header names the user: ``login`` or ``mail``."""
    return os.getenv("REDMINE_TRUSTED_HEADER_MATCH", "").strip().lower() or "login"


def resolve_trusted_login(request) -> str:
    """Return the Redmine login of the user the proxy named, or raise
    PerUserAuthError.

    In ``mail`` mode the header carries an email address. It is resolved to
    a login once per HTTP request; the login is kept on ``request.state`` and
    discarded with the request.
    """
    if request is None:
        raise PerUserAuthError(
            "Trusted-header auth requires an HTTP request context but none "
            "was found."
        )
    name = _header_name()
    value = _extract_header(request, name)
    if value is None:
        raise PerUserAuthError(f"Trusted-header auth: missing {name} request header.")
    if _match_mode() == "mail":
        if len(value) > _MAIL_MAX_LENGTH or not _MAIL_RE.fullmatch(value):
            raise PerUserAuthError(
                f"Trusted-header auth: the {name} header is not a valid email "
                "address."
            )
        login = getattr(request.state, "trusted_header_login", None)
        if login is None:
            login = _login_for_mail(value)
            request.state.trusted_header_login = login
    elif _LOGIN_RE.fullmatch(value):
        login = value
    else:
        raise PerUserAuthError(
            f"Trusted-header auth: the {name} header is not a valid Redmine login."
        )
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


def _login_for_mail(email: str) -> str:
    """Return the login of the active Redmine user whose primary email is
    ``email``, ignoring case, or raise PerUserAuthError.

    Redmine's ``name`` search narrows the list: active users whose login,
    name or any email address contains ``email``, ignoring case. Every
    Redmine version supports it, unlike the user query filters added in 5.1.
    The exact comparison happens here, against the primary email only:
    additional addresses do not count, because the user list does not show
    them. Transport errors propagate to the caller.
    """
    from . import _client

    response = _redmine_get(
        "/users.json",
        _client.REDMINE_API_KEY,
        params=[("name", email), ("status", "1"), ("limit", "100")],
    )
    if response.status_code in (401, 403):
        raise PerUserAuthError(
            "Trusted-header auth: Redmine refused the user lookup by email. "
            "Listing users needs REDMINE_API_KEY to belong to an administrator."
        )
    if not 200 <= response.status_code < 300:
        raise PerUserAuthError(
            "Trusted-header auth: the user lookup by email returned HTTP "
            f"{response.status_code}."
        )
    try:
        users = response.json().get("users")
    except (ValueError, AttributeError):
        users = None
    if not isinstance(users, list):
        raise PerUserAuthError(
            "Trusted-header auth: the user lookup by email returned an "
            "unexpected response."
        )
    wanted = email.lower()
    logins = [
        user.get("login")
        for user in users
        if isinstance(user, dict)
        and isinstance(user.get("mail"), str)
        and user["mail"].lower() == wanted
    ]
    if not logins:
        raise PerUserAuthError(
            f"Trusted-header auth: no active Redmine user has the email {email}."
        )
    if len(logins) > 1:
        raise PerUserAuthError(
            "Trusted-header auth: several active Redmine users have the email "
            f"{email}."
        )
    login = logins[0]
    if not isinstance(login, str) or not login:
        raise PerUserAuthError(
            "Trusted-header auth: the user lookup by email returned an "
            "unexpected response."
        )
    return login


def _probe_admin_key(key: str) -> tuple[int, Optional[bool]]:
    """GET /users/current.json with ``key``; return the status and admin flag.

    The flag is ``None`` unless Redmine answered 2xx with a boolean
    ``user.admin``. Transport errors propagate to the caller.
    """
    response = _redmine_get("/users/current.json", key)
    admin = None
    if 200 <= response.status_code < 300:
        try:
            value = response.json().get("user", {}).get("admin")
        except (ValueError, AttributeError):
            value = None
        if isinstance(value, bool):
            admin = value
    return response.status_code, admin


def _verify_admin_key(error: type[Exception] = RuntimeError) -> None:
    """Raise ``error`` unless Redmine confirms that REDMINE_API_KEY belongs
    to an administrator.

    Transport errors from the probe propagate unchanged, so each caller
    decides how an unreachable Redmine is reported.
    """
    from . import _client

    status, admin = _probe_admin_key(_client.REDMINE_API_KEY)
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


def assert_startup_requirements() -> None:
    """Fail closed unless the mode is attested and its key can switch users.

    Called once at app build time when REDMINE_AUTH_MODE=trusted-header.
    """
    from . import _client
    from ._env import _is_true_env

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


def check_admin_key(request) -> None:
    """Raise PerUserAuthError unless REDMINE_API_KEY still belongs to an
    administrator.

    Checked once per HTTP request: a tool that builds several clients while
    serving one request reuses the first answer, which is kept on
    ``request.state`` and discarded with the request. A transport error
    propagates unchanged and is reported like any other failed Redmine call.
    """
    if getattr(request.state, "trusted_header_admin_checked", False):
        return
    _verify_admin_key(PerUserAuthError)
    request.state.trusted_header_admin_checked = True
