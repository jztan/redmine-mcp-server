"""Unit tests for the api-key-login provider and its store.

Redmine is mocked at ``fetch_redmine_identity`` or at the httpx transport, and
the store is an injected ``MemoryStore``; nothing here touches the network or
the filesystem except the two tests that exercise the real file store.
"""

import time
import urllib.parse
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import pytest
from key_value.aio.stores.memory import MemoryStore
from mcp.server.auth.provider import (
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from redmine_mcp_server import _api_key_login as m

REDMINE = "https://redmine.example.com"
BASE = "https://mcp.example.com"
SCOPES = ["view_issues", "edit_issues", "view_projects"]
LOOPBACK = ["http://localhost:*", "http://127.0.0.1:*"]
REDIRECT = "http://localhost:41999/callback"
KEY = "a" * 40


@pytest.fixture(autouse=True)
def _no_network(request):
    """Revalidation must never leave the process in a unit test.

    Refresh now revalidates the bound key, so an unmocked test would hit DNS.
    The default answer is "inconclusive", which keeps the session -- tests that
    care about revocation patch it themselves.
    """
    if "no_network_guard" in request.keywords:
        yield
        return
    with patch.object(
        m,
        "fetch_redmine_identity",
        AsyncMock(side_effect=m.RedmineUnavailable("no network in unit tests")),
    ):
        yield


def _identity(user_id: int = 7, login: str = "tester", admin: bool = False):
    return {"id": user_id, "login": login, "admin": admin}


def _provider(store: Optional[MemoryStore] = None, **kwargs) -> m.ApiKeyLoginProvider:
    kwargs.setdefault("scopes_supported", list(SCOPES))
    kwargs.setdefault("allowed_client_redirect_uris", list(LOOPBACK))
    return m.ApiKeyLoginProvider(
        base_url=BASE,
        redmine_url=REDMINE,
        store=store or MemoryStore(),
        **kwargs,
    )


def _client(
    client_id: str = "client-1",
    redirect: str = REDIRECT,
    scope: str = "view_issues",
) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        client_name="Test Client",
        redirect_uris=[AnyUrl(redirect)],
        scope=scope,
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )


def _params(scopes=None, state="state-1", explicit=True) -> AuthorizationParams:
    return AuthorizationParams(
        state=state,
        scopes=scopes,
        code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        redirect_uri=AnyUrl(REDIRECT),
        redirect_uri_provided_explicitly=explicit,
        resource=f"{BASE}/mcp",
    )


async def _registered(provider, client=None):
    client = client or _client()
    await provider.register_client(client)
    return client


async def _login(provider, client, api_key=KEY, identity=None, **kwargs):
    """Run authorize + complete_login, returning (redirect_url, txn_id)."""
    url = await provider.authorize(client, _params(**kwargs))
    txn_id = url.split("txn=", 1)[1]
    txn = await provider.get_transaction(txn_id)
    with patch.object(
        m, "fetch_redmine_identity", AsyncMock(return_value=identity or _identity())
    ):
        redirect = await provider.complete_login(
            txn_id, txn["csrf"], api_key, browser_nonce=txn["browser_nonce"]
        )
    return redirect, txn_id


# --- client registration -----------------------------------------------


async def test_register_client_rejects_a_redirect_outside_the_allowlist():
    provider = _provider()
    with pytest.raises(RegistrationError) as exc:
        await provider.register_client(_client(redirect="https://evil.example.com/cb"))
    # A ValueError here would surface as a 500 rather than an OAuth error.
    assert exc.value.error == "invalid_redirect_uri"


async def test_register_client_accepts_loopback_and_round_trips():
    provider = _provider()
    client = await _registered(provider)
    loaded = await provider.get_client(client.client_id)
    assert loaded is not None
    assert str(loaded.redirect_uris[0]) == REDIRECT


async def test_star_allowlist_accepts_anything():
    provider = _provider(allowed_client_redirect_uris=None)
    await provider.register_client(_client(redirect="https://anywhere.example.com/cb"))


async def test_unknown_client_is_none():
    assert await _provider().get_client("nope") is None


async def test_authorize_rewrites_the_client_record_with_a_full_ttl():
    """Registrations must not age out mid-session while a client is active.

    Asserted on the write rather than on the remaining TTL: patching the
    provider's clock does not move ``MemoryStore``'s, so comparing two
    readings of "600 minus a few microseconds" is a race, and it lost one in
    CI (599.999828 > 599.999842).
    """
    store = MemoryStore()
    provider = _provider(store, session_ttl=600)
    client = await _registered(provider)

    writes = []
    original_put = store.put

    async def recording_put(key, value, *, collection=None, ttl=None):
        writes.append((collection, key, ttl))
        return await original_put(key, value, collection=collection, ttl=ttl)

    with patch.object(store, "put", recording_put):
        await provider.authorize(client, _params())

    assert (m.COLLECTION_CLIENTS, client.client_id, 600) in writes


# --- authorize ----------------------------------------------------------


async def test_authorize_returns_the_login_url_and_stores_the_transaction():
    store = MemoryStore()
    provider = _provider(store)
    client = await _registered(provider)
    url = await provider.authorize(client, _params())
    assert url.startswith(f"{BASE}/login?txn=")
    txn_id = url.split("txn=", 1)[1]
    assert await store.get(txn_id, collection=m.COLLECTION_TRANSACTIONS) is None
    txn = await store.get(m._hash(txn_id), collection=m.COLLECTION_TRANSACTIONS)
    assert txn["client_id"] == client.client_id
    assert txn["csrf"] and txn["browser_nonce"]
    assert txn["redirect_uri_provided_explicitly"] is True


async def test_authorize_rejects_a_redirect_the_client_did_not_register():
    provider = _provider()
    client = await _registered(provider)
    params = _params()
    params.redirect_uri = AnyUrl("http://localhost:1234/other")
    with pytest.raises(AuthorizeError) as exc:
        await provider.authorize(client, params)
    assert exc.value.error == "invalid_request"


async def test_scopes_are_intersected_with_the_advertised_set():
    provider = _provider()
    client = await _registered(provider)
    url = await provider.authorize(
        client, _params(scopes=["view_issues", "not_advertised"])
    )
    txn = await provider.get_transaction(url.split("txn=", 1)[1])
    assert txn["scopes"] == ["view_issues"]


async def test_admin_scope_is_dropped():
    # admin is advertised here on purpose: otherwise the plain intersection
    # removes it and this test would still pass with the explicit drop gone.
    provider = _provider(scopes_supported=SCOPES + [m.ADMIN_SCOPE])
    client = await _registered(provider)
    url = await provider.authorize(client, _params(scopes=["view_issues", "admin"]))
    txn = await provider.get_transaction(url.split("txn=", 1)[1])
    assert "admin" not in txn["scopes"]


async def test_scopes_fall_back_to_the_registration_when_none_requested():
    provider = _provider()
    client = await _registered(provider, _client(scope="view_issues view_projects"))
    url = await provider.authorize(client, _params(scopes=None))
    txn = await provider.get_transaction(url.split("txn=", 1)[1])
    assert txn["scopes"] == ["view_issues", "view_projects"]


# --- the login step ------------------------------------------------------


async def test_complete_login_binds_the_key_and_redirects_with_code_and_state():
    provider = _provider()
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    assert redirect.startswith(REDIRECT)
    assert "code=" in redirect and "state=state-1" in redirect
    # RFC 9207: the issuer travels back so the client can detect a mix-up.
    assert "iss=" in redirect


async def test_a_wrong_key_costs_an_attempt_and_does_not_bind():
    provider = _provider()
    client = await _registered(provider)
    url = await provider.authorize(client, _params())
    txn_id = url.split("txn=", 1)[1]
    txn = await provider.get_transaction(txn_id)
    with patch.object(m, "fetch_redmine_identity", AsyncMock(return_value=None)):
        with pytest.raises(m.ApiKeyLoginError, match="rejected"):
            await provider.complete_login(
                txn_id, txn["csrf"], KEY, browser_nonce=txn["browser_nonce"]
            )
    assert (await provider.get_transaction(txn_id))["attempts"] == 1


async def test_the_transaction_is_dropped_after_three_failures():
    provider = _provider()
    client = await _registered(provider)
    url = await provider.authorize(client, _params())
    txn_id = url.split("txn=", 1)[1]
    with patch.object(m, "fetch_redmine_identity", AsyncMock(return_value=None)):
        for _ in range(m.MAX_LOGIN_ATTEMPTS):
            txn = await provider.get_transaction(txn_id)
            if txn is None:
                break
            with pytest.raises(m.ApiKeyLoginError):
                await provider.complete_login(
                    txn_id, txn["csrf"], KEY, browser_nonce=txn["browser_nonce"]
                )
    assert await provider.get_transaction(txn_id) is None


async def test_a_bad_csrf_drops_the_transaction():
    provider = _provider()
    client = await _registered(provider)
    url = await provider.authorize(client, _params())
    txn_id = url.split("txn=", 1)[1]
    txn = await provider.get_transaction(txn_id)
    with pytest.raises(m.ApiKeyLoginError):
        await provider.complete_login(
            txn_id, "wrong", KEY, browser_nonce=txn["browser_nonce"]
        )
    assert await provider.get_transaction(txn_id) is None


async def test_a_mismatched_browser_nonce_drops_the_transaction():
    provider = _provider()
    client = await _registered(provider)
    url = await provider.authorize(client, _params())
    txn_id = url.split("txn=", 1)[1]
    txn = await provider.get_transaction(txn_id)
    with pytest.raises(m.ApiKeyLoginError, match="different browser"):
        await provider.complete_login(
            txn_id, txn["csrf"], KEY, browser_nonce="somebody-else"
        )
    assert await provider.get_transaction(txn_id) is None


async def test_the_transaction_is_single_use():
    provider = _provider()
    client = await _registered(provider)
    url = await provider.authorize(client, _params())
    txn_id = url.split("txn=", 1)[1]
    txn = await provider.get_transaction(txn_id)
    with patch.object(m, "fetch_redmine_identity", AsyncMock(return_value=_identity())):
        await provider.complete_login(
            txn_id, txn["csrf"], KEY, browser_nonce=txn["browser_nonce"]
        )
        with pytest.raises(m.ApiKeyLoginError):
            await provider.complete_login(
                txn_id, txn["csrf"], KEY, browser_nonce=txn["browser_nonce"]
            )


async def test_an_expired_transaction_is_gone():
    provider = _provider(transaction_ttl=1)
    client = await _registered(provider)
    url = await provider.authorize(client, _params())
    txn_id = url.split("txn=", 1)[1]
    with patch.object(m, "_now", lambda: time.time() + 120):
        assert await provider.get_transaction(txn_id) is None


async def test_an_admin_key_is_refused_by_default():
    provider = _provider()
    client = await _registered(provider)
    with pytest.raises(m.ApiKeyLoginError, match="administrators"):
        await _login(provider, client, identity=_identity(admin=True))


async def test_an_admin_key_is_accepted_when_the_gate_is_open():
    provider = _provider(allow_admin=True)
    client = await _registered(provider)
    redirect, _ = await _login(provider, client, identity=_identity(admin=True))
    assert "code=" in redirect


# --- code exchange -------------------------------------------------------


async def _exchange(provider, client, redirect):
    code = redirect.split("code=", 1)[1].split("&", 1)[0]
    auth_code = await provider.load_authorization_code(client, code)
    assert auth_code is not None
    return auth_code, await provider.exchange_authorization_code(client, auth_code)


async def test_code_exchange_issues_a_bound_access_token():
    provider = _provider()
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    _, token = await _exchange(provider, client, redirect)

    access = await provider.load_access_token(token.access_token)
    assert access is not None
    assert access.claims["redmine_api_key"] == KEY
    assert access.claims["redmine_user_id"] == 7
    assert access.claims["redmine_login"] == "tester"
    assert access.claims["binding_id"]


async def test_redirect_uri_provided_explicitly_round_trips_to_the_code():
    provider = _provider()
    client = await _registered(provider)
    redirect, _ = await _login(provider, client, explicit=True)
    code = redirect.split("code=", 1)[1].split("&", 1)[0]
    auth_code = await provider.load_authorization_code(client, code)
    assert auth_code.redirect_uri_provided_explicitly is True


async def test_a_code_cannot_be_exchanged_twice():
    provider = _provider()
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    auth_code, _token = await _exchange(provider, client, redirect)
    with pytest.raises(TokenError) as exc:
        await provider.exchange_authorization_code(client, auth_code)
    assert exc.value.error == "invalid_grant"


async def test_a_code_belongs_to_one_client():
    provider = _provider()
    client = await _registered(provider)
    other = await _registered(provider, _client(client_id="client-2"))
    redirect, _ = await _login(provider, client)
    code = redirect.split("code=", 1)[1].split("&", 1)[0]
    assert await provider.load_authorization_code(other, code) is None


# --- tokens --------------------------------------------------------------


async def test_tokens_are_stored_by_hash_only():
    store = MemoryStore()
    provider = _provider(store)
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    _, token = await _exchange(provider, client, redirect)
    assert (
        await store.get(token.access_token, collection=m.COLLECTION_ACCESS_TOKENS)
        is None
    )
    assert (
        await store.get(
            m._hash(token.access_token), collection=m.COLLECTION_ACCESS_TOKENS
        )
        is not None
    )


async def test_an_expired_access_token_does_not_load():
    provider = _provider(access_token_ttl=1)
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    _, token = await _exchange(provider, client, redirect)
    with patch.object(m, "_now", lambda: time.time() + 60):
        assert await provider.load_access_token(token.access_token) is None


async def test_refresh_rotates_and_invalidates_the_old_token():
    provider = _provider()
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    _, token = await _exchange(provider, client, redirect)

    refresh = await provider.load_refresh_token(client, token.refresh_token)
    assert refresh is not None
    rotated = await provider.exchange_refresh_token(client, refresh, [])
    assert rotated.refresh_token != token.refresh_token
    assert await provider.load_access_token(rotated.access_token) is not None
    # The old one must be gone, not merely superseded.
    assert await provider.load_refresh_token(client, token.refresh_token) is None


async def test_refresh_cannot_widen_the_grant():
    provider = _provider()
    client = await _registered(provider)
    redirect, _ = await _login(provider, client, scopes=["view_issues"])
    _, token = await _exchange(provider, client, redirect)
    refresh = await provider.load_refresh_token(client, token.refresh_token)
    with pytest.raises(TokenError) as exc:
        await provider.exchange_refresh_token(client, refresh, ["edit_issues"])
    assert exc.value.error == "invalid_scope"


async def test_reusing_a_rotated_refresh_token_revokes_the_session():
    provider = _provider()
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    _, token = await _exchange(provider, client, redirect)
    refresh = await provider.load_refresh_token(client, token.refresh_token)
    rotated = await provider.exchange_refresh_token(client, refresh, [])

    # The old one comes back: RFC 6819 5.2.2.3 says the session is burnt.
    assert await provider.load_refresh_token(client, token.refresh_token) is None
    assert await provider.load_access_token(rotated.access_token) is None


async def test_the_absolute_session_bounds_the_access_token():
    provider = _provider(session_ttl=60, access_token_ttl=3600)
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    _, token = await _exchange(provider, client, redirect)
    assert token.expires_in <= 60


# --- revocation ----------------------------------------------------------


async def test_revoking_the_binding_invalidates_every_token_without_enumeration():
    provider = _provider()
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    _, token = await _exchange(provider, client, redirect)
    access = await provider.load_access_token(token.access_token)

    assert await provider.revoke_binding(access.claims["binding_id"]) is True
    assert await provider.load_access_token(token.access_token) is None
    assert await provider.load_refresh_token(client, token.refresh_token) is None


async def test_revoking_an_access_token_leaves_the_refresh_token_alive():
    provider = _provider()
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    _, token = await _exchange(provider, client, redirect)
    access = await provider.load_access_token(token.access_token)

    await provider.revoke_token(access)
    assert await provider.load_access_token(token.access_token) is None
    assert await provider.load_refresh_token(client, token.refresh_token) is not None


async def test_revoking_the_refresh_token_ends_the_session():
    provider = _provider()
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    _, token = await _exchange(provider, client, redirect)

    await provider.revoke_token(
        RefreshToken(
            token=token.refresh_token,
            client_id=client.client_id,
            scopes=["view_issues"],
            expires_at=int(time.time() + 600),
        )
    )
    assert await provider.load_access_token(token.access_token) is None


# --- key validation against Redmine --------------------------------------


def _transport(handler):
    import httpx

    return httpx.MockTransport(handler)


@pytest.mark.no_network_guard
async def test_fetch_redmine_identity_sends_the_key_in_the_header():
    import httpx

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["header"] = request.headers.get("X-Redmine-API-Key")
        return httpx.Response(
            200, json={"user": {"id": 7, "login": "tester", "admin": False}}
        )

    with patch.object(httpx, "AsyncClient", _client_factory(handler)):
        identity = await m.fetch_redmine_identity(REDMINE, KEY)

    assert identity == {"id": 7, "login": "tester", "admin": False}
    assert seen["header"] == KEY
    # Never in the query string, where Redmine's access log would keep it.
    assert "key=" not in seen["url"]


@pytest.mark.no_network_guard
async def test_fetch_redmine_identity_returns_none_on_401():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    with patch.object(httpx, "AsyncClient", _client_factory(handler)):
        assert await m.fetch_redmine_identity(REDMINE, KEY) is None


@pytest.mark.no_network_guard
async def test_fetch_redmine_identity_reports_a_transport_failure_as_unavailable():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with patch.object(httpx, "AsyncClient", _client_factory(handler)):
        with pytest.raises(m.RedmineUnavailable):
            await m.fetch_redmine_identity(REDMINE, KEY)


def _client_factory(handler):
    """Return an httpx.AsyncClient factory pinned to a mock transport."""
    import httpx

    real = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any):
        kwargs.pop("verify", None)
        kwargs.pop("cert", None)
        return real(*args, transport=_transport(handler), **kwargs)

    return factory


# --- binding protection --------------------------------------------------


def test_the_server_secret_scheme_is_a_pass_through():
    protection = m.ServerSecretBindingProtection()
    record, data_key = protection.seal({"api_key": KEY})
    assert data_key is None
    assert protection.wrap(data_key, "secret") == {}
    assert protection.unwrap({"anything": 1}, "secret") is None
    assert protection.unseal(record, None) == {"api_key": KEY}


async def test_an_unopenable_binding_invalidates_the_token():
    """The seam PR 4 needs: unseal returning None must not leak a token."""

    class _Broken(m.ServerSecretBindingProtection):
        def unseal(self, record, data_key):
            return None

    provider = _provider(protection=_Broken())
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    _, token = await _exchange(provider, client, redirect)
    assert await provider.load_access_token(token.access_token) is None


# --- store wiring and startup --------------------------------------------


def _env(**overrides):
    base = {
        "REDMINE_URL": REDMINE,
        "REDMINE_MCP_BASE_URL": BASE,
        "REDMINE_MCP_JWT_SIGNING_KEY": "a-long-enough-operator-secret",
    }
    base.update(overrides)
    return base


def test_build_requires_the_three_core_vars(monkeypatch, tmp_path):
    monkeypatch.setenv("FASTMCP_HOME", str(tmp_path))
    for missing in (
        "REDMINE_URL",
        "REDMINE_MCP_BASE_URL",
        "REDMINE_MCP_JWT_SIGNING_KEY",
    ):
        env = _env()
        env.pop(missing)
        with patch.dict("os.environ", env, clear=False):
            monkeypatch.delenv(missing, raising=False)
            with pytest.raises(RuntimeError, match=missing):
                m.build_api_key_login()


def test_build_refuses_an_http_base_url(monkeypatch, tmp_path):
    monkeypatch.setenv("FASTMCP_HOME", str(tmp_path))
    with patch.dict(
        "os.environ", _env(REDMINE_MCP_BASE_URL="http://mcp.local"), clear=False
    ):
        monkeypatch.delenv("REDMINE_API_KEY_LOGIN_ALLOW_HTTP", raising=False)
        with pytest.raises(RuntimeError, match="must be https"):
            m.build_api_key_login()


def test_build_honours_the_http_dev_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("FASTMCP_HOME", str(tmp_path))
    with patch.dict(
        "os.environ",
        _env(
            REDMINE_MCP_BASE_URL="http://mcp.local",
            REDMINE_API_KEY_LOGIN_ALLOW_HTTP="true",
        ),
        clear=False,
    ):
        provider = m.build_api_key_login()
    assert isinstance(provider, m.ApiKeyLoginProvider)


def test_the_session_length_is_configurable(monkeypatch, tmp_path):
    monkeypatch.setenv("FASTMCP_HOME", str(tmp_path))
    with patch.dict(
        "os.environ", _env(REDMINE_API_KEY_LOGIN_SESSION_DAYS="90"), clear=False
    ):
        provider = m.build_api_key_login()
    assert provider._session_ttl == 90 * 86400


def test_the_store_path_is_isolated_per_secret(monkeypatch, tmp_path):
    # ``settings`` is an instance, not a module, so the home is patched
    # directly rather than reloaded.
    monkeypatch.setattr(m.settings, "home", tmp_path)
    one = m.api_key_login_store_path("secret-one")
    two = m.api_key_login_store_path("secret-two")
    assert one != two
    assert one.parent == two.parent
    assert one.parent.name == m.STORE_SUBDIR


def test_the_store_path_is_logged_and_a_missing_home_warns(monkeypatch, caplog):
    monkeypatch.delenv("FASTMCP_HOME", raising=False)
    with caplog.at_level("INFO"):
        m.log_api_key_login_store_path("api-key-login")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "state directory" in text
    assert "FASTMCP_HOME is unset" in text


def test_nothing_is_logged_for_another_mode(caplog):
    with caplog.at_level("INFO"):
        m.log_api_key_login_store_path("legacy")
    assert caplog.records == []


async def test_the_file_store_round_trips_and_a_wrong_secret_reads_as_a_miss(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(m.settings, "home", tmp_path)
    store = m.build_store("the-operator-secret")
    await store.put("k", {"api_key": KEY}, collection=m.COLLECTION_BINDINGS)
    assert (await store.get("k", collection=m.COLLECTION_BINDINGS))["api_key"] == KEY

    # Nothing readable from the directory itself.
    blobs = [p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()]
    assert blobs and not any(KEY.encode() in b for b in blobs)

    # Pointed at the *same* directory, a wrong secret must fail to decrypt
    # rather than hand the record over. Reading a different directory would
    # prove nothing, so the isolation property is asserted separately.
    wrong = m.FernetEncryptionWrapper(
        key_value=m.FileTreeStore(
            data_directory=m.api_key_login_store_path("the-operator-secret")
        ),
        fernet=m.Fernet(key=m._storage_encryption_key("a-different-secret")),
        raise_on_decryption_error=False,
    )
    assert await wrong.get("k", collection=m.COLLECTION_BINDINGS) is None


# --- review #286: fixes, one test each -----------------------------------


@pytest.mark.parametrize(
    "base", ["https://mcp.example.com", "https://host.example.com/redmine"]
)
async def test_iss_matches_the_metadata_issuer_byte_for_byte(base):
    """RFC 9207 is an exact string match, and a root base URL gains a slash."""
    provider = m.ApiKeyLoginProvider(
        base_url=base,
        redmine_url=REDMINE,
        store=MemoryStore(),
        scopes_supported=list(SCOPES),
        allowed_client_redirect_uris=list(LOOPBACK),
    )
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)

    iss = urllib.parse.parse_qs(urllib.parse.urlparse(redirect).query)["iss"][0]
    assert iss == str(provider.issuer_url)


async def test_a_revoked_binding_is_an_oauth_error_not_a_500():
    provider = _provider()
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    code = redirect.split("code=", 1)[1].split("&", 1)[0]
    auth_code = await provider.load_authorization_code(client, code)

    # Revoked in the window between the code being minted and exchanged.
    await provider.revoke_binding(auth_code.code and await _binding_id(provider, code))
    with pytest.raises(TokenError) as exc:
        await provider.exchange_authorization_code(client, auth_code)
    assert exc.value.error == "invalid_grant"


async def _binding_id(provider, code):
    record = await provider._store.get(m._hash(code), collection=m.COLLECTION_CODES)
    return record["binding_id"]


async def test_a_registration_loses_redirect_uris_the_allowlist_no_longer_matches():
    """Registrations outlive the allowlist, so tightening it has to reach them."""
    provider = _provider()
    client = await _registered(provider)

    provider._allowed_client_redirect_uris = ["https://only-this.example.com/*"]
    loaded = await provider.get_client(client.client_id)
    assert loaded.redirect_uris == []


async def test_a_disallowed_redirect_is_refused_with_a_page_not_a_redirect():
    """RFC 6749 4.1.2.1: never bounce the error off the URI just rejected.

    Filtering in get_client is what makes this work. Raising in authorize
    instead would have the SDK deliver the error as a redirect to
    ``…/cb?error=invalid_request``, handing it to the very endpoint the
    allowlist had judged untrustworthy.
    """
    from fastmcp import FastMCP
    from httpx import ASGITransport, AsyncClient

    provider = _provider()
    client = await _registered(provider)
    provider._allowed_client_redirect_uris = ["https://only-this.example.com/*"]

    app = FastMCP("allowlist-test", auth=provider).http_app(stateless_http=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=BASE, follow_redirects=False
    ) as http:
        response = await http.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client.client_id,
                "redirect_uri": REDIRECT,
                "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                "code_challenge_method": "S256",
                "state": "s",
            },
        )

    assert response.status_code == 400
    assert "location" not in response.headers


async def test_a_pasted_key_with_a_newline_is_rejected_before_httpx_sees_it():
    provider = _provider()
    client = await _registered(provider)
    url = await provider.authorize(client, _params())
    txn_id = url.split("txn=", 1)[1]
    txn = await provider.get_transaction(txn_id)

    fetch = AsyncMock()
    with patch.object(m, "fetch_redmine_identity", fetch):
        with pytest.raises(m.ApiKeyLoginError, match="does not look like"):
            await provider.complete_login(
                txn_id, txn["csrf"], KEY + "\n", browser_nonce=txn["browser_nonce"]
            )

    # httpx would raise LocalProtocolError here, carrying the whole key in the
    # message and landing on the "Redmine unreachable" path.
    fetch.assert_not_awaited()
    assert (await provider.get_transaction(txn_id))["attempts"] == 1


@pytest.mark.no_network_guard
@pytest.mark.parametrize(
    "status,payload",
    [
        (200, {"user": {"login": "x", "admin": False}}),
        (200, {"user": {"id": 7, "login": "x"}}),
        (200, {"user": {"id": "7", "login": "x", "admin": False}}),
        (200, {"nothing": "useful"}),
        (302, {}),
        (500, {}),
    ],
)
async def test_an_unusable_answer_is_unavailable_not_a_non_admin_user(status, payload):
    """Reading a missing admin flag as False would walk an admin past the gate."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    with patch.object(httpx, "AsyncClient", _client_factory(handler)):
        with pytest.raises(m.RedmineUnavailable):
            await m.fetch_redmine_identity(REDMINE, KEY)


@pytest.mark.no_network_guard
async def test_a_non_json_body_is_unavailable():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>login page</html>")

    with patch.object(httpx, "AsyncClient", _client_factory(handler)):
        with pytest.raises(m.RedmineUnavailable):
            await m.fetch_redmine_identity(REDMINE, KEY)


@pytest.mark.no_network_guard
async def test_the_unavailable_error_never_carries_the_key():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed talking to {KEY}", request=request)

    with patch.object(httpx, "AsyncClient", _client_factory(handler)):
        with pytest.raises(m.RedmineUnavailable) as exc:
            await m.fetch_redmine_identity(REDMINE, KEY)
    assert KEY not in str(exc.value)


async def test_the_browser_nonce_is_required():
    provider = _provider()
    client = await _registered(provider)
    url = await provider.authorize(client, _params())
    txn_id = url.split("txn=", 1)[1]
    txn = await provider.get_transaction(txn_id)

    with pytest.raises(TypeError):
        await provider.complete_login(txn_id, txn["csrf"], KEY)


def test_secret_comparison_survives_non_ascii_and_wrong_types():
    # hmac.compare_digest raises TypeError on a str holding non-ASCII, and the
    # value comes straight from a form field.
    assert m._constant_time_equal("abc", "abc") is True
    assert m._constant_time_equal("abc", "abd") is False
    assert m._constant_time_equal("abc", "schlüssel") is False
    assert m._constant_time_equal(None, "abc") is False
    assert m._constant_time_equal("abc", None) is False


async def test_a_narrowed_refresh_does_not_shrink_the_session():
    """RFC 6749 section 6: it narrows the access token, not the grant."""
    provider = _provider()
    client = await _registered(provider, _client(scope="view_issues edit_issues"))
    redirect, _ = await _login(provider, client, scopes=["view_issues", "edit_issues"])
    _, token = await _exchange(provider, client, redirect)

    refresh = await provider.load_refresh_token(client, token.refresh_token)
    narrowed = await provider.exchange_refresh_token(client, refresh, ["view_issues"])
    assert narrowed.scope == "view_issues"

    # The new refresh token still carries the original grant, so the next
    # refresh can ask for the full set again.
    again = await provider.load_refresh_token(client, narrowed.refresh_token)
    assert set(again.scopes) == {"view_issues", "edit_issues"}
    widened = await provider.exchange_refresh_token(
        client, again, ["view_issues", "edit_issues"]
    )
    assert set(widened.scope.split()) == {"view_issues", "edit_issues"}


def test_a_session_length_of_zero_refuses_to_start(monkeypatch, tmp_path):
    monkeypatch.setattr(m.settings, "home", tmp_path)
    with patch.dict(
        "os.environ", _env(REDMINE_API_KEY_LOGIN_SESSION_DAYS="0"), clear=False
    ):
        with pytest.raises(RuntimeError, match="positive number of days"):
            m.build_api_key_login()


def test_variables_from_the_other_modes_are_called_out(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(m.settings, "home", tmp_path)
    with patch.dict(
        "os.environ",
        _env(REDMINE_OAUTH_DISCOVERY_AS="self", REDMINE_INTROSPECT_CLIENT_ID="x"),
        clear=False,
    ):
        with caplog.at_level("WARNING"):
            m.build_api_key_login()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "do not apply in api-key-login mode" in text
    assert "REDMINE_OAUTH_DISCOVERY_AS" in text
    assert "REDMINE_INTROSPECT_CLIENT_ID" in text


async def test_codes_are_keyed_by_hash_too():
    store = MemoryStore()
    provider = _provider(store)
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    code = redirect.split("code=", 1)[1].split("&", 1)[0]

    assert await store.get(code, collection=m.COLLECTION_CODES) is None
    assert await store.get(m._hash(code), collection=m.COLLECTION_CODES) is not None


# --- review #287: revalidation at refresh --------------------------------


async def _session(provider):
    """A logged-in session: returns (client, token)."""
    client = await _registered(provider)
    redirect, _ = await _login(provider, client)
    _, token = await _exchange(provider, client, redirect)
    return client, token


async def _refresh(provider, client, token, identity=None, error=None):
    refresh = await provider.load_refresh_token(client, token.refresh_token)
    mock = AsyncMock(side_effect=error) if error else AsyncMock(return_value=identity)
    with patch.object(m, "fetch_redmine_identity", mock):
        return await provider.exchange_refresh_token(client, refresh, [])


async def test_a_refresh_revalidates_the_bound_key():
    """Redmine serves an unknown key as anonymous, so nothing else would notice."""
    provider = _provider()
    client, token = await _session(provider)

    seen = AsyncMock(return_value=_identity())
    refresh = await provider.load_refresh_token(client, token.refresh_token)
    with patch.object(m, "fetch_redmine_identity", seen):
        await provider.exchange_refresh_token(client, refresh, [])

    seen.assert_awaited_once()
    assert seen.await_args.args[1] == KEY
    # Its own budget, not REDMINE_TIMEOUT: a client is waiting on this.
    assert seen.await_args.kwargs["timeout"].read == m.REVALIDATION_TIMEOUT_SECONDS


async def test_a_rejected_key_ends_the_session_at_refresh():
    provider = _provider()
    client, token = await _session(provider)
    access = token.access_token

    with pytest.raises(TokenError) as exc:
        await _refresh(provider, client, token, identity=None)

    assert exc.value.error == "invalid_grant"
    assert await provider.load_access_token(access) is None


async def test_a_key_that_now_answers_as_someone_else_ends_the_session():
    provider = _provider()
    client, token = await _session(provider)

    with pytest.raises(TokenError):
        await _refresh(provider, client, token, identity=_identity(user_id=99))

    assert await provider.load_access_token(token.access_token) is None


async def test_a_user_who_became_an_admin_ends_the_session():
    provider = _provider()
    client, token = await _session(provider)

    with pytest.raises(TokenError):
        await _refresh(provider, client, token, identity=_identity(admin=True))

    assert await provider.load_access_token(token.access_token) is None


async def test_a_new_admin_is_fine_when_the_gate_is_open():
    provider = _provider(allow_admin=True)
    client, token = await _session(provider)
    rotated = await _refresh(provider, client, token, identity=_identity(admin=True))
    assert rotated.access_token


@pytest.mark.parametrize(
    "error", [m.RedmineForbidden("403"), m.RedmineUnavailable("timeout")]
)
async def test_an_inconclusive_revalidation_keeps_the_session(error):
    """A lost permission or a bad minute says nothing about the key."""
    provider = _provider()
    client, token = await _session(provider)
    rotated = await _refresh(provider, client, token, error=error)
    assert await provider.load_access_token(rotated.access_token) is not None


@pytest.mark.no_network_guard
async def test_a_403_is_told_apart_from_a_401():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={})

    with patch.object(httpx, "AsyncClient", _client_factory(handler)):
        with pytest.raises(m.RedmineForbidden):
            await m.fetch_redmine_identity(REDMINE, KEY)


# --- review #287: claiming single-use records ----------------------------


async def test_only_one_concurrent_claim_wins_on_a_real_file_store(tmp_path):
    """FileTreeStore.delete is a stat-then-unlink, so the lock is load-bearing.

    Without it two concurrent claims both reported success (41 of 300 runs on
    macOS), or the loser raised FileNotFoundError -- either way a code or a
    refresh token could be spent twice.
    """
    import asyncio

    monkeyed = m.settings.home
    try:
        m.settings.home = tmp_path
        store = m.build_store("claim-test-secret")
        provider = _provider(store)

        wins = 0
        for round_number in range(25):
            key = f"record-{round_number}"
            await store.put(key, {"v": 1}, collection=m.COLLECTION_CODES)
            results = await asyncio.gather(
                *(provider._claim(key, collection=m.COLLECTION_CODES) for _ in range(6))
            )
            assert sum(1 for r in results if r) == 1, results
            wins += 1
        assert wins == 25
    finally:
        m.settings.home = monkeyed


async def test_a_claim_of_something_already_gone_is_a_loss_not_an_error():
    provider = _provider()
    assert (
        await provider._claim("never-existed", collection=m.COLLECTION_CODES) is False
    )
