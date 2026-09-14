"""The browser step, the bound-key client branch, and the revocation hook.

The routes are driven over ASGI with httpx so the cookie really round-trips;
the provider underneath is the real one with a MemoryStore, and only Redmine
is mocked.
"""

import json
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from key_value.aio.stores.memory import MemoryStore
from mcp.shared.auth import OAuthClientInformationFull
from mcp.server.auth.provider import AuthorizationParams
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.routing import Route

from redmine_mcp_server import _api_key_login as provider_mod
from redmine_mcp_server import _api_key_login_routes as routes

REDMINE = "https://redmine.example.com"
BASE = "https://mcp.example.com"
SCOPES = ["view_issues", "edit_issues"]
REDIRECT = "http://localhost:41999/callback"
KEY = "a" * 40


def _identity(admin: bool = False):
    return {"id": 7, "login": "tester", "admin": admin}


def _provider(**kwargs):
    kwargs.setdefault("scopes_supported", list(SCOPES))
    kwargs.setdefault("allowed_client_redirect_uris", ["http://localhost:*"])
    return provider_mod.ApiKeyLoginProvider(
        base_url=BASE, redmine_url=REDMINE, store=MemoryStore(), **kwargs
    )


def _client_info(client_id="client-1", name="Test Client"):
    return OAuthClientInformationFull(
        client_id=client_id,
        client_name=name,
        redirect_uris=[AnyUrl(REDIRECT)],
        scope="view_issues",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )


def _params():
    return AuthorizationParams(
        state="state-1",
        scopes=["view_issues"],
        code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        redirect_uri=AnyUrl(REDIRECT),
        redirect_uri_provided_explicitly=True,
        resource=f"{BASE}/mcp",
    )


def _app():
    return Starlette(
        routes=[
            Route("/login", routes.login_page, methods=["GET"]),
            Route("/login", routes.login_submit, methods=["POST"]),
        ]
    )


@pytest.fixture(autouse=True)
def _reset_rate_limiter(monkeypatch):
    monkeypatch.setattr(routes, "_rate_limiter", None)
    monkeypatch.delenv("REDMINE_API_KEY_LOGIN_RATE_LIMIT", raising=False)
    # The cookie must be readable over plain http in the test transport.
    monkeypatch.setenv("REDMINE_API_KEY_LOGIN_ALLOW_HTTP", "true")


async def _new_transaction(provider):
    client = _client_info()
    await provider.register_client(client)
    url = await provider.authorize(client, _params())
    return url.split("txn=", 1)[1]


async def _browse(provider, cookies=None):
    """Return an httpx client wired to the routes with this provider.

    Cookies go on the client rather than the request: httpx deprecated the
    per-request form, and a jar is closer to what a browser does anyway.
    """
    transport = ASGITransport(app=_app())
    return AsyncClient(transport=transport, base_url="http://test", cookies=cookies)


# --- GET /login ----------------------------------------------------------


async def test_the_page_names_the_client_the_redirect_host_and_redmine():
    provider = _provider()
    txn = await _new_transaction(provider)
    with patch.object(routes, "_provider", lambda: provider):
        async with await _browse(provider) as http:
            response = await http.get(f"/login?txn={txn}")

    assert response.status_code == 200
    body = response.text
    assert "Test Client" in body
    assert "localhost:41999" in body
    assert REDMINE in body
    assert "view_issues" in body
    assert 'type="password"' in body and 'autocomplete="off"' in body


async def test_the_page_sets_a_per_transaction_binding_cookie():
    provider = _provider()
    txn = await _new_transaction(provider)
    transaction = await provider.get_transaction(txn)
    with patch.object(routes, "_provider", lambda: provider):
        async with await _browse(provider) as http:
            response = await http.get(f"/login?txn={txn}")

    name = routes.cookie_name(txn)
    assert response.cookies.get(name) == transaction["browser_nonce"]
    header = response.headers["set-cookie"]
    assert "HttpOnly" in header and "SameSite=lax" in header.lower().replace(
        "samesite=lax", "SameSite=lax"
    )


async def test_the_csp_carries_no_form_action():
    """Chrome enforces form-action across the post-submit redirect chain."""
    provider = _provider()
    txn = await _new_transaction(provider)
    with patch.object(routes, "_provider", lambda: provider):
        async with await _browse(provider) as http:
            response = await http.get(f"/login?txn={txn}")

    csp = response.headers["content-security-policy"]
    assert "form-action" not in csp
    assert "frame-ancestors 'none'" in csp
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


async def test_an_unknown_transaction_is_a_static_page_not_a_redirect():
    provider = _provider()
    with patch.object(routes, "_provider", lambda: provider):
        async with await _browse(provider) as http:
            response = await http.get("/login?txn=does-not-exist")
    assert response.status_code == 400
    assert "location" not in response.headers


async def test_the_route_is_absent_in_another_mode():
    with patch.object(routes, "_provider", lambda: None):
        async with await _browse(None) as http:
            response = await http.get("/login?txn=x")
    assert response.status_code == 404


def test_the_cookie_path_carries_the_mount_prefix(monkeypatch):
    monkeypatch.setenv("REDMINE_MCP_BASE_URL", "https://host.example.com/redmine")
    assert routes.cookie_path() == "/redmine/login"
    monkeypatch.setenv("REDMINE_MCP_BASE_URL", "https://host.example.com")
    assert routes.cookie_path() == "/login"


def test_two_transactions_get_different_cookie_names():
    assert routes.cookie_name("one") != routes.cookie_name("two")


# --- POST /login ---------------------------------------------------------


async def _submit(provider, txn, *, key=KEY, cookie=True, csrf=None, identity=None):
    transaction = await provider.get_transaction(txn)
    cookies = {}
    if cookie is True:
        cookies[routes.cookie_name(txn)] = transaction["browser_nonce"]
    elif isinstance(cookie, str):
        cookies[routes.cookie_name(txn)] = cookie
    data = {
        "txn": txn,
        "csrf": csrf if csrf is not None else transaction["csrf"],
        "api_key": key,
    }
    fetch = AsyncMock(return_value=identity if identity is not None else _identity())
    with (
        patch.object(routes, "_provider", lambda: provider),
        patch.object(provider_mod, "fetch_redmine_identity", fetch),
    ):
        async with await _browse(provider, cookies) as http:
            return await http.post("/login", data=data)


async def test_a_good_key_redirects_to_the_client_with_a_code():
    provider = _provider()
    txn = await _new_transaction(provider)
    response = await _submit(provider, txn)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(REDIRECT)
    assert "code=" in location and "state=state-1" in location


async def test_a_missing_cookie_is_refused_and_drops_the_transaction():
    provider = _provider()
    txn = await _new_transaction(provider)
    response = await _submit(provider, txn, cookie=False)
    assert response.status_code == 400
    assert "different browser" in response.text or "cookie was" in response.text
    assert await provider.get_transaction(txn) is None


async def test_a_foreign_cookie_is_refused():
    provider = _provider()
    txn = await _new_transaction(provider)
    response = await _submit(provider, txn, cookie="somebody-elses-value")
    assert response.status_code == 400
    assert await provider.get_transaction(txn) is None


async def test_two_concurrent_logins_in_one_browser_both_complete():
    provider = _provider()
    first = await _new_transaction(provider)
    second = await _new_transaction(provider)

    t1 = await provider.get_transaction(first)
    t2 = await provider.get_transaction(second)
    # One cookie jar carrying both, which is the point of the per-txn name.
    cookies = {
        routes.cookie_name(first): t1["browser_nonce"],
        routes.cookie_name(second): t2["browser_nonce"],
    }
    fetch = AsyncMock(return_value=_identity())
    with (
        patch.object(routes, "_provider", lambda: provider),
        patch.object(provider_mod, "fetch_redmine_identity", fetch),
    ):
        async with await _browse(provider, cookies) as http:
            one = await http.post(
                "/login", data={"txn": first, "csrf": t1["csrf"], "api_key": KEY}
            )
            two = await http.post(
                "/login", data={"txn": second, "csrf": t2["csrf"], "api_key": KEY}
            )
    assert one.status_code == 302 and two.status_code == 302


async def test_a_malformed_key_re_renders_and_costs_an_attempt():
    provider = _provider()
    txn = await _new_transaction(provider)
    response = await _submit(provider, txn, key="short")
    assert response.status_code == 400
    assert "does not look like" in response.text
    assert (await provider.get_transaction(txn))["attempts"] == 1


async def test_a_rejected_key_re_renders_with_a_generic_error():
    provider = _provider()
    txn = await _new_transaction(provider)
    fetch = AsyncMock(return_value=None)
    transaction = await provider.get_transaction(txn)
    with (
        patch.object(routes, "_provider", lambda: provider),
        patch.object(provider_mod, "fetch_redmine_identity", fetch),
    ):
        async with await _browse(
            provider, {routes.cookie_name(txn): transaction["browser_nonce"]}
        ) as http:
            response = await http.post(
                "/login",
                data={"txn": txn, "csrf": transaction["csrf"], "api_key": KEY},
            )
    assert response.status_code == 400
    assert "rejected" in response.text
    assert KEY not in response.text


async def test_an_admin_key_is_refused_with_its_own_message():
    provider = _provider()
    txn = await _new_transaction(provider)
    response = await _submit(provider, txn, identity=_identity(admin=True))
    assert response.status_code == 400
    assert "administrators" in response.text


async def test_an_unreachable_redmine_is_502_and_keeps_the_transaction():
    provider = _provider()
    txn = await _new_transaction(provider)
    transaction = await provider.get_transaction(txn)
    boom = AsyncMock(side_effect=httpx.ConnectError("down"))
    with (
        patch.object(routes, "_provider", lambda: provider),
        patch.object(provider_mod, "fetch_redmine_identity", boom),
    ):
        async with await _browse(
            provider, {routes.cookie_name(txn): transaction["browser_nonce"]}
        ) as http:
            response = await http.post(
                "/login",
                data={"txn": txn, "csrf": transaction["csrf"], "api_key": KEY},
            )
    assert response.status_code == 502
    assert await provider.get_transaction(txn) is not None


async def test_the_rate_limit_answers_429_without_costing_an_attempt(monkeypatch):
    monkeypatch.setattr(routes, "_rate_limiter", routes._RateLimiter(1))
    provider = _provider()
    txn = await _new_transaction(provider)

    first = await _submit(provider, txn)
    assert first.status_code == 302

    second_txn = await _new_transaction(provider)
    blocked = await _submit(provider, second_txn)
    assert blocked.status_code == 429
    assert (await provider.get_transaction(second_txn))["attempts"] == 0


async def test_the_key_never_appears_in_a_log_line(caplog):
    provider = _provider()
    txn = await _new_transaction(provider)
    with caplog.at_level("DEBUG"):
        await _submit(provider, txn)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert KEY not in text
    assert "...aaaa" in text


# --- _client.py branch ----------------------------------------------------


def _token(claims):
    token = Mock()
    token.claims = claims
    token.token = "opaque"
    return token


def test_the_client_is_built_from_the_bound_key():
    from redmine_mcp_server import _client

    with (
        patch.object(_client, "REDMINE_URL", REDMINE),
        patch.object(_client, "REDMINE_AUTH_MODE", "api-key-login"),
        patch.object(_client, "redmine", None),
        patch.object(_client, "Redmine") as redmine,
        patch.object(_client, "_build_requests_config", return_value={}),
        patch.object(
            _client, "get_access_token", return_value=_token({"redmine_api_key": KEY})
        ),
    ):
        _client._get_redmine_client()

    redmine.assert_called_once_with(REDMINE, engine=_client.TimeoutSyncEngine, key=KEY)


def test_a_token_without_the_claim_is_a_server_bug_not_a_bearer_call():
    from redmine_mcp_server import _client
    from redmine_mcp_server._per_user import PerUserAuthError

    with (
        patch.object(_client, "REDMINE_URL", REDMINE),
        patch.object(_client, "REDMINE_AUTH_MODE", "api-key-login"),
        patch.object(_client, "redmine", None),
        patch.object(_client, "Redmine"),
        patch.object(_client, "get_access_token", return_value=_token({})),
    ):
        with pytest.raises(PerUserAuthError, match="no Redmine API key"):
            _client._get_redmine_client()


# --- error envelope and scrubbing -----------------------------------------


def test_a_401_is_reported_with_the_auth_failed_code():
    from redminelib.exceptions import AuthError

    from redmine_mcp_server import _client, _errors

    with patch.object(_client, "REDMINE_AUTH_MODE", "api-key-login"):
        payload = _errors._handle_redmine_error(AuthError(), "listing issues")
    assert payload["code"] == "AUTH_FAILED"
    assert "bound to this session" in payload["error"]


def test_a_403_stays_an_ordinary_permission_error():
    from redminelib.exceptions import ForbiddenError

    from redmine_mcp_server import _client, _errors

    with patch.object(_client, "REDMINE_AUTH_MODE", "api-key-login"):
        payload = _errors._handle_redmine_error(ForbiddenError(), "listing issues")
    assert "code" not in payload
    assert "Access denied" in payload["error"]


def test_the_bound_key_is_scrubbed_from_error_text():
    from redmine_mcp_server import _errors

    with patch.object(
        _errors,
        "_bound_api_keys",
        lambda: [KEY],
    ):
        scrubbed = _errors._scrub_error_message(f"boom while using {KEY} somewhere")
    assert KEY not in scrubbed
    assert "[redacted]" in scrubbed


def test_scrubbing_survives_a_missing_token_context():
    from redmine_mcp_server import _errors

    assert _errors._bound_api_keys() == []


# --- revocation middleware -------------------------------------------------


class _Result:
    def __init__(self, structured):
        self.structured_content = structured


async def _run_middleware(provider, structured, claims):
    middleware = provider_mod.BindingRevocationMiddleware(provider)

    async def call_next(_context):
        return _Result(structured)

    with patch(
        "fastmcp.server.dependencies.get_access_token",
        return_value=_token(claims),
    ):
        return await middleware.on_call_tool(Mock(), call_next)


async def test_an_auth_failed_result_revokes_the_binding():
    provider = _provider()
    revoke = AsyncMock(return_value=True)
    with patch.object(provider, "revoke_binding", revoke):
        result = await _run_middleware(
            provider,
            {"error": "no", "code": "AUTH_FAILED"},
            {"binding_id": "b-1", "redmine_user_id": 7},
        )
    revoke.assert_awaited_once_with("b-1")
    # The caller still gets its error untouched.
    assert result.structured_content["code"] == "AUTH_FAILED"


async def test_a_wrapped_result_is_unwrapped_before_matching():
    """Tools returning a non-dict type carry the envelope under "result"."""
    provider = _provider()
    revoke = AsyncMock(return_value=True)
    with patch.object(provider, "revoke_binding", revoke):
        await _run_middleware(
            provider,
            {"result": {"error": "no", "code": "AUTH_FAILED"}},
            {"binding_id": "b-2"},
        )
    revoke.assert_awaited_once_with("b-2")


async def test_another_error_code_does_not_revoke():
    provider = _provider()
    revoke = AsyncMock(return_value=True)
    with patch.object(provider, "revoke_binding", revoke):
        await _run_middleware(
            provider,
            {"error": "nope", "code": "INSUFFICIENT_SCOPE"},
            {"binding_id": "b-3"},
        )
    revoke.assert_not_awaited()


async def test_a_successful_result_does_not_revoke():
    provider = _provider()
    revoke = AsyncMock(return_value=True)
    with patch.object(provider, "revoke_binding", revoke):
        await _run_middleware(provider, {"issues": []}, {"binding_id": "b-4"})
    revoke.assert_not_awaited()


async def test_revocation_really_invalidates_the_session_end_to_end():
    """The guarantee: reset your key in Redmine and the next call signs you out."""
    provider = _provider()
    txn = await _new_transaction(provider)
    response = await _submit(provider, txn)
    code = response.headers["location"].split("code=", 1)[1].split("&", 1)[0]

    client = await provider.get_client("client-1")
    auth_code = await provider.load_authorization_code(client, code)
    token = await provider.exchange_authorization_code(client, auth_code)
    access = await provider.load_access_token(token.access_token)

    await _run_middleware(
        provider,
        {"error": "rejected", "code": "AUTH_FAILED"},
        dict(access.claims),
    )
    assert await provider.load_access_token(token.access_token) is None


def test_the_envelope_reader_ignores_a_non_dict_result():
    assert provider_mod.BindingRevocationMiddleware._envelope(_Result(None)) is None
    assert provider_mod.BindingRevocationMiddleware._envelope(Mock(spec=[])) is None


def test_json_envelope_shape_matches_what_the_middleware_expects():
    """Guards the contract between _handle_redmine_error and the middleware."""
    from redminelib.exceptions import AuthError

    from redmine_mcp_server import _client, _errors

    with patch.object(_client, "REDMINE_AUTH_MODE", "api-key-login"):
        payload = _errors._handle_redmine_error(AuthError(), "x")
    assert (
        provider_mod.BindingRevocationMiddleware._envelope(_Result(payload))["code"]
        == "AUTH_FAILED"
    )
    json.dumps(payload)


# --- the wired-up OAuth surface -------------------------------------------


async def _oauth_app(provider):
    """The provider mounted on a real FastMCP app, as main.py does."""
    from fastmcp import FastMCP

    app = FastMCP("api-key-login-test", auth=provider).http_app(stateless_http=True)
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:8000"
    )


async def _full_flow(provider, http):
    """register -> authorize -> login -> token, over HTTP."""
    import base64
    import hashlib
    import re
    import secrets

    def b64(raw):
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    registration = await http.post(
        "/register",
        json={
            "client_name": "probe",
            "redirect_uris": [REDIRECT],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    client_id = registration.json()["client_id"]
    verifier = b64(secrets.token_bytes(32))
    authorize = await http.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": b64(hashlib.sha256(verifier.encode()).digest()),
            "code_challenge_method": "S256",
            "state": "s",
        },
    )
    txn = authorize.headers["location"].split("txn=", 1)[1]
    transaction = await provider.get_transaction(txn)
    with patch.object(
        provider_mod, "fetch_redmine_identity", AsyncMock(return_value=_identity())
    ):
        redirect = await provider.complete_login(
            txn,
            transaction["csrf"],
            KEY,
            browser_nonce=transaction["browser_nonce"],
        )
    code = re.search(r"[?&]code=([^&]+)", redirect).group(1)
    token = await http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    return client_id, token


async def test_a_public_client_completes_the_flow_without_a_secret():
    provider = _provider(allowed_client_redirect_uris=["http://localhost:*"])
    async with await _oauth_app(provider) as http:
        client_id, token = await _full_flow(provider, http)

    assert token.status_code == 200
    payload = token.json()
    assert payload["token_type"] == "Bearer"
    assert payload["refresh_token"]
    bound = await provider.load_access_token(payload["access_token"])
    assert bound.claims["redmine_api_key"] == KEY


async def test_revoking_the_refresh_token_over_http_ends_the_session():
    provider = _provider(allowed_client_redirect_uris=["http://localhost:*"])
    async with await _oauth_app(provider) as http:
        client_id, token = await _full_flow(provider, http)
        payload = token.json()

        revoked = await http.post(
            "/revoke",
            data={
                "token": payload["refresh_token"],
                "token_type_hint": "refresh_token",
                "client_id": client_id,
                # The MCP SDK's RevocationRequest declares client_secret as
                # `str | None` with no default, so the field must be *present*
                # even for a public client that was never issued one --
                # omitting it is a 400 before authentication runs, unlike
                # TokenRequest which defaults it to None. Sending an empty
                # value is the client-side way through.
                "client_secret": "",
            },
        )

    assert revoked.status_code == 200
    assert await provider.load_access_token(payload["access_token"]) is None
