"""The browser step of ``api-key-login``: a page that collects an API key.

Two routes, registered on the FastMCP instance the way ``_http_routes`` does
it. They live inside the mounted MCP app, so under
``REDMINE_MCP_BASE_URL=https://host/redmine`` they answer at
``/redmine/login`` -- which is also why the browser-binding cookie carries the
mount prefix in its ``Path``. A bare ``/login`` would never be sent back.

The page is the one place a Redmine credential is typed, so it names who is
asking (the client's registered name and the host the code will be sent to)
and which Redmine the key travels to. The threat it cannot answer on its own
is an attacker who mints a transaction and hands over the unrendered URL: the
redirect allowlist is the guard there, and setting it to ``*`` removes it.
"""

import hashlib
import html
import logging
import secrets
import threading
import time
from typing import Optional
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from ._api_key_login import (
    ApiKeyLoginError,
    ApiKeyLoginProvider,
    RedmineUnavailable,
)
from ._env import _get_int_env, _is_true_env
from ._mount import mcp_mount_prefix
from ._per_user import _fingerprint
from .server import mcp

logger = logging.getLogger(__name__)

LOGIN_PATH = "/login"
DEFAULT_RATE_LIMIT_PER_MINUTE = 300

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    # No form-action: Chrome enforces it across the post-submit redirect chain
    # (Chromium issue 40923007) and the success response is a 302 to the
    # client's redirect URI on another origin. FastMCP's own consent page omits
    # it for the same reason.
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
        "frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class _RateLimiter:
    """A process-wide ceiling on login POSTs.

    Deliberately not the primary control: the per-transaction budget is, and
    stock Redmine keys are 40 hex characters, so guessing is impractical
    regardless. This only bounds runaway abuse and log noise, and the default
    is set high enough that one hostile caller cannot lock every legitimate
    user out -- /authorize is open, so anyone can mint transactions.
    """

    def __init__(self, per_minute: int):
        self._capacity = max(1, per_minute)
        self._tokens = float(self._capacity)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = time.monotonic()
            refill = (now - self._updated) * (self._capacity / 60.0)
            self._tokens = min(float(self._capacity), self._tokens + refill)
            self._updated = now
            if self._tokens < 1.0:
                return False
            self._tokens -= 1.0
            return True


_rate_limiter: Optional[_RateLimiter] = None


def _limiter() -> _RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = _RateLimiter(
            _get_int_env(
                "REDMINE_API_KEY_LOGIN_RATE_LIMIT", DEFAULT_RATE_LIMIT_PER_MINUTE
            )
        )
    return _rate_limiter


def _provider() -> Optional[ApiKeyLoginProvider]:
    """The active provider, or ``None`` when another auth mode is running."""
    from . import server

    provider = getattr(server, "AUTH_PROVIDER", None)
    return provider if isinstance(provider, ApiKeyLoginProvider) else None


def cookie_name(txn_id: str) -> str:
    """One cookie per transaction, so two logins in one browser coexist."""
    return "login_" + hashlib.sha256(txn_id.encode("utf-8")).hexdigest()[:16]


def cookie_path() -> str:
    prefix = mcp_mount_prefix().rstrip("/")
    return f"{prefix}{LOGIN_PATH}"


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect to Redmine</title>
<style>
 body {{ font-family: system-ui, sans-serif; max-width: 34rem; margin: 3rem auto;
        padding: 0 1rem; color: #222; line-height: 1.5; }}
 h1 {{ font-size: 1.4rem; }}
 .who {{ background: #f4f6f8; border: 1px solid #dde; border-radius: .4rem;
         padding: .75rem 1rem; margin: 1rem 0; }}
 .who b {{ font-weight: 600; }}
 label {{ display: block; margin-top: 1.25rem; font-weight: 600; }}
 input {{ width: 100%; padding: .5rem; margin-top: .3rem; font: inherit;
          border: 1px solid #999; border-radius: .25rem; box-sizing: border-box; }}
 button {{ margin-top: 1.5rem; padding: .55rem 1.2rem; font: inherit; color: #fff;
           background: #2563eb; border: 1px solid transparent;
           border-radius: .25rem; cursor: pointer; }}
 .err {{ margin-top: 1rem; padding: .6rem .75rem; border-radius: .25rem;
         background: #fee2e2; color: #991b1b; }}
 .scopes {{ font-size: .9rem; color: #555; }}
 .note {{ margin-top: 2rem; font-size: .85rem; color: #666;
          border-top: 1px solid #ddd; padding-top: 1rem; }}
</style></head><body>
<h1>Connect to Redmine</h1>
{error}
<div class="who">
  <p><b>{client_name}</b> is asking to act as you in Redmine.</p>
  <p>It will receive the result at <b>{redirect_host}</b>.</p>
  <p>Your key is sent to <b>{redmine_url}</b> and nowhere else.</p>
  <p class="scopes">Access requested: {scopes}</p>
</div>
<form method="post" action="{action}">
  <input type="hidden" name="txn" value="{txn}">
  <input type="hidden" name="csrf" value="{csrf}">
  <label>Redmine API access key
    <input name="api_key" type="password" autocomplete="off" autofocus required></label>
  <button type="submit">Connect</button>
</form>
<p class="note">Find your key in Redmine under <b>My account</b>, in the
<b>API access key</b> box on the right. This page never asks for your
password. If anything above is not what you expected, close this page.</p>
</body></html>
"""

_ERROR_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Connection failed</title>
<style>body {{ font-family: system-ui, sans-serif; max-width: 34rem;
 margin: 3rem auto; padding: 0 1rem; color: #222; }}</style></head>
<body><h1>Connection failed</h1><p>{message}</p>
<p>Start the connection again in your client.</p></body></html>
"""


def _error_page(message: str, status: int) -> HTMLResponse:
    return HTMLResponse(
        _ERROR_PAGE.format(message=html.escape(message)),
        status_code=status,
        headers=dict(_SECURITY_HEADERS),
    )


def _render(
    txn_id: str,
    transaction: dict,
    client_name: str,
    redmine_url: str,
    error: Optional[str] = None,
    status: int = 200,
) -> HTMLResponse:
    scopes = ", ".join(transaction.get("scopes") or []) or "no scopes requested"
    redirect_host = urlparse(str(transaction.get("redirect_uri", ""))).netloc or "?"
    body = _PAGE.format(
        error=f'<p class="err">{html.escape(error)}</p>' if error else "",
        client_name=html.escape(client_name),
        redirect_host=html.escape(redirect_host),
        redmine_url=html.escape(redmine_url),
        scopes=html.escape(scopes),
        action=html.escape(cookie_path()),
        txn=html.escape(txn_id),
        csrf=html.escape(str(transaction.get("csrf", ""))),
    )
    return HTMLResponse(body, status_code=status, headers=dict(_SECURITY_HEADERS))


def _set_binding_cookie(response: Response, txn_id: str, nonce: str) -> None:
    response.set_cookie(
        cookie_name(txn_id),
        nonce,
        httponly=True,
        samesite="lax",
        secure=not _is_true_env("REDMINE_API_KEY_LOGIN_ALLOW_HTTP"),
        path=cookie_path(),
        max_age=600,
    )


async def _client_name(provider: ApiKeyLoginProvider, client_id: str) -> str:
    client = await provider.get_client(client_id)
    name = getattr(client, "client_name", None) if client else None
    return name or client_id


async def login_page(request: Request) -> Response:
    """Render the consent page for a pending transaction."""
    provider = _provider()
    if provider is None:
        return _error_page("This server is not running the api-key-login mode.", 404)

    txn_id = request.query_params.get("txn", "")
    transaction = await provider.get_transaction(txn_id) if txn_id else None
    if transaction is None:
        # Never redirect from here: an unknown txn may be someone probing.
        return _error_page("This login link is unknown or has expired.", 400)

    response = _render(
        txn_id,
        transaction,
        await _client_name(provider, str(transaction["client_id"])),
        provider.redmine_url,
    )
    _set_binding_cookie(response, txn_id, str(transaction["browser_nonce"]))
    return response


async def login_submit(request: Request) -> Response:
    """Validate the pasted key and hand the code back to the client."""
    provider = _provider()
    if provider is None:
        return _error_page("This server is not running the api-key-login mode.", 404)

    if not _limiter().allow():
        # Before anything is loaded, so a flood cannot consume attempts.
        return _error_page("Too many login attempts right now. Try again shortly.", 429)

    form = await request.form()
    txn_id = str(form.get("txn") or "")
    csrf = str(form.get("csrf") or "")
    api_key = str(form.get("api_key") or "").strip()

    transaction = await provider.get_transaction(txn_id) if txn_id else None
    if transaction is None:
        return _error_page("This login link is unknown or has expired.", 400)

    cookie = request.cookies.get(cookie_name(txn_id))
    if not cookie or not secrets.compare_digest(
        cookie, str(transaction.get("browser_nonce", ""))
    ):
        await provider.drop_transaction(txn_id)
        return _error_page(
            "This page was opened in a different browser, or its cookie was "
            "blocked.",
            400,
        )

    client_name = await _client_name(provider, str(transaction["client_id"]))

    try:
        redirect = await provider.complete_login(
            txn_id, csrf, api_key, browser_nonce=cookie
        )
    except RedmineUnavailable as exc:
        # Redmine could not be asked, so the key's validity is unknown: the
        # transaction survives, no attempt is charged, and the user can retry.
        # The exception carries no key material, so it is safe to log.
        logger.warning("api-key-login: Redmine unavailable during login (%s)", exc)
        return _error_page("Redmine could not be reached. Please try again.", 502)
    except ApiKeyLoginError as exc:
        logger.info(
            "api-key-login: login refused (%s) for key %s",
            exc.message,
            _fingerprint(api_key),
        )
        refreshed = await provider.get_transaction(txn_id)
        if refreshed is None:
            return _error_page(exc.message, 400)
        return _render(
            txn_id,
            refreshed,
            client_name,
            provider.redmine_url,
            error=exc.message,
            status=400,
        )

    logger.info("api-key-login: bound key %s", _fingerprint(api_key))
    response = RedirectResponse(redirect, status_code=302)
    response.delete_cookie(cookie_name(txn_id), path=cookie_path())
    return response


mcp.custom_route(LOGIN_PATH, methods=["GET"])(login_page)
mcp.custom_route(LOGIN_PATH, methods=["POST"])(login_submit)
