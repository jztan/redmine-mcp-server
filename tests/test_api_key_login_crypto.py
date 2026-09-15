"""``token-derived`` binding protection: the scheme and the guarantee it makes.

The guarantee is one sentence: whoever holds the store *and*
``REDMINE_MCP_JWT_SIGNING_KEY`` still cannot read a stored Redmine API key,
because the key that opens a binding exists only inside the tokens the clients
hold. Most of what follows exists to keep that sentence true -- the flow tests
matter more than the primitive tests, since an unwrapped data key left in a
record would pass every round-trip test in this file and void the guarantee.
"""

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from key_value.aio.stores.memory import MemoryStore
from mcp.server.auth.provider import TokenError
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
def _no_network():
    """Refresh revalidates the bound key; unit tests must not leave the process."""
    with patch.object(
        m,
        "fetch_redmine_identity",
        AsyncMock(side_effect=m.RedmineUnavailable("no network in unit tests")),
    ):
        yield


def _payload(**overrides) -> dict[str, Any]:
    payload = {
        "api_key": KEY,
        "redmine_user_id": 7,
        "redmine_login": "tester",
        "client_id": "client-1",
        "scopes": ["view_issues"],
        "created_at": 1000.0,
        "session_expires_at": 2000.0,
    }
    payload.update(overrides)
    return payload


# --- the primitive ------------------------------------------------------


def test_the_sealed_record_carries_no_trace_of_the_key():
    record, data_key = m.TokenDerivedBindingProtection().seal(_payload())

    assert KEY not in json.dumps(record)
    assert "tester" not in json.dumps(record)
    assert data_key is not None and len(data_key) == 32
    assert record["crypto"] == m.TOKEN_DERIVED_VERSION


def test_sealing_the_same_payload_twice_gives_two_different_records():
    """A fresh data key and nonce each time; equal ciphertext would leak equality."""
    protection = m.TokenDerivedBindingProtection()
    first, first_key = protection.seal(_payload())
    second, second_key = protection.seal(_payload())

    assert first["ciphertext"] != second["ciphertext"]
    assert first["nonce"] != second["nonce"]
    assert first_key != second_key


def test_a_data_key_round_trips_through_the_capability_that_carries_it():
    protection = m.TokenDerivedBindingProtection()
    record, data_key = protection.seal(_payload())
    carrier = protection.wrap(data_key, "the-authorization-code")

    assert protection.unwrap(carrier, "the-authorization-code") == data_key
    assert protection.unseal(record, data_key) == _payload()


def test_the_wrapped_key_is_useless_without_the_capability():
    protection = m.TokenDerivedBindingProtection()
    _, data_key = protection.seal(_payload())
    carrier = protection.wrap(data_key, "the-real-token")

    assert m._b64d(carrier["wrapped_key"]) != data_key
    assert protection.unwrap(carrier, "a-different-token") is None


def test_wrapping_the_same_key_twice_gives_two_different_carriers():
    """Each token gets its own salt and nonce, so two records never match."""
    protection = m.TokenDerivedBindingProtection()
    _, data_key = protection.seal(_payload())

    first = protection.wrap(data_key, "token-one")
    second = protection.wrap(data_key, "token-two")

    assert first["wrapped_key"] != second["wrapped_key"]
    assert first["wrap_salt"] != second["wrap_salt"]


@pytest.mark.parametrize("field", ["wrapped_key", "wrap_nonce", "wrap_salt"])
def test_a_tampered_carrier_does_not_yield_a_key(field):
    """GCM authenticates; a flipped byte must fail, not decrypt to garbage."""
    protection = m.TokenDerivedBindingProtection()
    _, data_key = protection.seal(_payload())
    carrier = dict(protection.wrap(data_key, "tok"))
    raw = bytearray(m._b64d(carrier[field]))
    raw[0] ^= 0x01
    carrier[field] = m._b64e(bytes(raw))

    assert protection.unwrap(carrier, "tok") is None


@pytest.mark.parametrize("field", ["ciphertext", "nonce"])
def test_a_tampered_binding_does_not_open(field):
    protection = m.TokenDerivedBindingProtection()
    record, data_key = protection.seal(_payload())
    record = dict(record)
    raw = bytearray(m._b64d(record[field]))
    raw[0] ^= 0x01
    record[field] = m._b64e(bytes(raw))

    assert protection.unseal(record, data_key) is None


def test_the_wrong_data_key_does_not_open_a_binding():
    protection = m.TokenDerivedBindingProtection()
    record, _ = protection.seal(_payload())
    _, other_key = protection.seal(_payload())

    assert protection.unseal(record, other_key) is None
    assert protection.unseal(record, None) is None


@pytest.mark.parametrize(
    "carrier",
    [
        {},
        {"crypto": "something-else", "wrapped_key": "x", "wrap_nonce": "y"},
        {"crypto": m.TOKEN_DERIVED_VERSION},
        {"crypto": m.TOKEN_DERIVED_VERSION, "wrapped_key": 7, "wrap_nonce": None},
        {
            "crypto": m.TOKEN_DERIVED_VERSION,
            "wrapped_key": "not base64!",
            "wrap_nonce": "n",
            "wrap_salt": "s",
        },
    ],
)
def test_a_malformed_carrier_is_answered_with_none_not_an_exception(carrier):
    """These reach the code from disk, so a raise here would be a 500 at /token."""
    assert m.TokenDerivedBindingProtection().unwrap(carrier, "tok") is None


def test_a_record_that_is_not_a_json_object_is_refused():
    """Defence in depth: a payload must be a mapping, whatever decrypted."""
    protection = m.TokenDerivedBindingProtection()
    record, data_key = protection.seal(_payload())
    stray = m.AESGCM(data_key).encrypt(
        m._b64d(record["nonce"]), json.dumps(["not", "a", "dict"]).encode(), None
    )
    record = dict(record, ciphertext=m._b64e(stray))

    assert protection.unseal(record, data_key) is None


def test_neither_scheme_can_read_the_other_scheme_s_records():
    """Flipping the variable on a live deployment must fail closed, both ways."""
    token_derived = m.TokenDerivedBindingProtection()
    server_secret = m.ServerSecretBindingProtection()

    sealed_by_token, data_key = token_derived.seal(_payload())
    sealed_by_secret, _ = server_secret.seal(_payload())

    # The old scheme hands back the ciphertext record as-is; it holds no
    # api_key, which is what every caller checks before using it.
    assert "api_key" not in server_secret.unseal(sealed_by_token, None)
    # The new scheme refuses a record it did not write.
    assert token_derived.unseal(sealed_by_secret, data_key) is None


def test_a_failure_to_open_says_so_without_naming_the_secret(caplog):
    protection = m.TokenDerivedBindingProtection()
    _, data_key = protection.seal(_payload())
    carrier = protection.wrap(data_key, "the-real-token")

    with caplog.at_level("DEBUG"):
        assert protection.unwrap(carrier, "the-wrong-token") is None

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "unwrap" in text
    assert "the-wrong-token" not in text
    assert "the-real-token" not in text


# --- the flow -----------------------------------------------------------


class _Recording:
    """A MemoryStore that keeps a copy of everything ever written to it.

    Stands in for the attacker's copy of the volume: whatever passes through
    ``put`` is what a stolen backup contains, decrypted past the store's own
    Fernet wrapper, which the operator secret opens.
    """

    def __init__(self):
        self._inner = MemoryStore()
        self.writes: list[tuple[str, str, dict]] = []

    async def get(self, key, *, collection=None):
        return await self._inner.get(key, collection=collection)

    async def put(self, key, value, *, collection=None, ttl=None):
        self.writes.append((collection or "", key, dict(value)))
        return await self._inner.put(key, value, collection=collection, ttl=ttl)

    async def ttl(self, key, *, collection=None):
        return await self._inner.ttl(key, collection=collection)

    async def delete(self, key, *, collection=None):
        return await self._inner.delete(key, collection=collection)

    def dump(self) -> str:
        return json.dumps(self.writes, default=str)


def _provider(store=None, protection=None, **kwargs) -> m.ApiKeyLoginProvider:
    kwargs.setdefault("scopes_supported", list(SCOPES))
    kwargs.setdefault("allowed_client_redirect_uris", list(LOOPBACK))
    return m.ApiKeyLoginProvider(
        base_url=BASE,
        redmine_url=REDMINE,
        store=store if store is not None else MemoryStore(),
        protection=protection or m.TokenDerivedBindingProtection(),
        **kwargs,
    )


def _client(client_id: str = "client-1") -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        client_name="Test Client",
        redirect_uris=[AnyUrl(REDIRECT)],
        scope="view_issues",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )


def _params():
    from mcp.server.auth.provider import AuthorizationParams

    return AuthorizationParams(
        state="state-1",
        scopes=None,
        code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        redirect_uri=AnyUrl(REDIRECT),
        redirect_uri_provided_explicitly=True,
        resource=f"{BASE}/mcp",
    )


def _identity(user_id: int = 7, login: str = "tester", admin: bool = False):
    return {"id": user_id, "login": login, "admin": admin}


async def _session(provider, api_key=KEY, return_code=False):
    """Register, log in and exchange the code: returns (client, token)."""
    client = _client()
    await provider.register_client(client)
    url = await provider.authorize(client, _params())
    txn_id = url.split("txn=", 1)[1]
    txn = await provider.get_transaction(txn_id)
    with patch.object(m, "fetch_redmine_identity", AsyncMock(return_value=_identity())):
        redirect = await provider.complete_login(
            txn_id, txn["csrf"], api_key, browser_nonce=txn["browser_nonce"]
        )
    code = redirect.split("code=", 1)[1].split("&", 1)[0]
    auth_code = await provider.load_authorization_code(client, code)
    issued = await provider.exchange_authorization_code(client, auth_code)
    if return_code:
        return client, issued, code
    return client, issued


async def _refresh(provider, client, token, identity=None):
    refresh = await provider.load_refresh_token(client, token.refresh_token)
    with patch.object(
        m,
        "fetch_redmine_identity",
        AsyncMock(return_value=identity or _identity()),
    ):
        return await provider.exchange_refresh_token(client, refresh, [])


async def test_the_whole_flow_works_under_token_derived():
    provider = _provider()
    client, token = await _session(provider)

    access = await provider.load_access_token(token.access_token)
    assert access is not None
    assert access.claims["redmine_api_key"] == KEY
    assert access.claims["redmine_user_id"] == 7
    assert access.claims["redmine_login"] == "tester"


async def test_nothing_the_store_ever_held_contains_the_key():
    """The guarantee. A stolen volume plus the operator secret yields this dump."""
    store = _Recording()
    provider = _provider(store)
    client, token, code = await _session(provider, return_code=True)
    rotated = await _refresh(provider, client, token)
    await _refresh(provider, client, rotated)

    dump = store.dump()
    assert KEY not in dump
    assert "tester" not in dump
    # Not the capabilities either: each is stored by hash, and that is what
    # makes the data key wrapped under it unopenable from the dump alone. The
    # authorization code belongs in this list -- it used to be written into
    # its own record in the clear, next to the data key wrapped under it.
    for value in (code, token.access_token, token.refresh_token, rotated.access_token):
        assert value not in dump


async def test_a_record_never_carries_the_secret_that_opens_it():
    """The general form of the bug the code field was.

    Any record holding a wrapped data key must not also hold the value that
    derives its key-encryption key. Rather than naming the fields, this tries
    every string in every record against the wrap and insists none of them
    works.
    """
    store = _Recording()
    provider = _provider(store)
    client, token = await _session(provider)
    await _refresh(provider, client, token)

    protection = m.TokenDerivedBindingProtection()
    checked = 0
    for collection, _key, record in store.writes:
        if "wrapped_key" not in record:
            continue
        checked += 1
        for field, value in record.items():
            if not isinstance(value, str):
                continue
            assert (
                protection.unwrap(record, value) is None
            ), f"{collection}.{field} opens its own wrapped data key"
    assert checked >= 3, checked


async def test_the_data_key_is_never_written_in_the_clear():
    """The one mistake that would pass every round-trip test in this file.

    Recovers the session's real data key the only legitimate way -- by
    presenting the access token -- and then looks for it in everything the
    store was ever handed.
    """
    store = _Recording()
    provider = _provider(store)
    _, token = await _session(provider)

    access_record = await store.get(
        m._hash(token.access_token), collection=m.COLLECTION_ACCESS_TOKENS
    )
    data_key = m.TokenDerivedBindingProtection().unwrap(
        access_record, token.access_token
    )
    assert data_key is not None

    dump = store.dump()
    assert m._b64e(data_key) not in dump
    assert data_key.hex() not in dump

    # Three records carry it, each wrapped under its own capability, and the
    # binding itself carries ciphertext rather than a key.
    carriers = {w[0] for w in store.writes if "wrapped_key" in w[2]}
    assert carriers == {
        m.COLLECTION_CODES,
        m.COLLECTION_ACCESS_TOKENS,
        m.COLLECTION_REFRESH_TOKENS,
    }
    binding = [w for w in store.writes if w[0] == m.COLLECTION_BINDINGS]
    assert len(binding) == 1 and "wrapped_key" not in binding[0][2]


async def test_a_rotation_carries_the_data_key_to_the_new_tokens():
    provider = _provider()
    client, token = await _session(provider)

    first = await _refresh(provider, client, token)
    second = await _refresh(provider, client, first)

    access = await provider.load_access_token(second.access_token)
    assert access is not None and access.claims["redmine_api_key"] == KEY
    # And the superseded ones are gone, as in the default scheme.
    assert await provider.load_access_token(token.access_token) is not None
    assert await provider.load_refresh_token(client, token.refresh_token) is None


async def test_the_refresh_revalidation_still_sees_the_key():
    """The reason revalidation was built to run with the token in hand."""
    provider = _provider()
    client, token = await _session(provider)

    seen = AsyncMock(return_value=_identity())
    refresh = await provider.load_refresh_token(client, token.refresh_token)
    with patch.object(m, "fetch_redmine_identity", seen):
        await provider.exchange_refresh_token(client, refresh, [])

    seen.assert_awaited_once()
    assert seen.await_args.args[1] == KEY


async def test_revocation_still_needs_no_read():
    """``revoke_binding`` is a delete; nothing about it depends on the scheme."""
    provider = _provider()
    client, token = await _session(provider)
    binding_id = (await provider.load_access_token(token.access_token)).claims[
        "binding_id"
    ]

    assert await provider.revoke_binding(binding_id) is True
    assert await provider.load_access_token(token.access_token) is None


async def test_a_revoked_key_still_ends_the_session_at_the_next_refresh():
    provider = _provider()
    client, token = await _session(provider)

    refresh = await provider.load_refresh_token(client, token.refresh_token)
    with patch.object(m, "fetch_redmine_identity", AsyncMock(return_value=None)):
        with pytest.raises(TokenError):
            await provider.exchange_refresh_token(client, refresh, [])

    assert await provider.load_access_token(token.access_token) is None


async def test_a_binding_from_the_other_scheme_ends_the_session():
    """What an operator gets for flipping the variable: everyone logs in again."""
    store = MemoryStore()
    provider = _provider(store, protection=m.ServerSecretBindingProtection())
    client, token = await _session(provider)

    # Same store, same records, the other scheme -- as after a restart.
    switched = _provider(store, protection=m.TokenDerivedBindingProtection())
    assert await switched.load_access_token(token.access_token) is None

    refresh = await switched.load_refresh_token(client, token.refresh_token)
    with pytest.raises(TokenError, match="no longer be read"):
        await switched.exchange_refresh_token(client, refresh, [])


async def test_flipping_back_also_fails_closed():
    store = MemoryStore()
    provider = _provider(store)
    client, token = await _session(provider)

    switched = _provider(store, protection=m.ServerSecretBindingProtection())
    assert await switched.load_access_token(token.access_token) is None


async def test_the_key_never_reaches_the_log_under_this_scheme(caplog):
    provider = _provider()

    with caplog.at_level("DEBUG"):
        client, token = await _session(provider)
        await provider.load_access_token(token.access_token)
        await _refresh(provider, client, token)

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert KEY not in text


# --- selecting the scheme ------------------------------------------------


def _env(**overrides):
    base = {
        "REDMINE_URL": REDMINE,
        "REDMINE_MCP_BASE_URL": BASE,
        "REDMINE_MCP_JWT_SIGNING_KEY": "a-long-enough-operator-secret",
    }
    base.update(overrides)
    return base


def test_the_default_is_the_framework_scheme(monkeypatch):
    monkeypatch.delenv("REDMINE_API_KEY_LOGIN_BINDING_CRYPTO", raising=False)
    assert isinstance(m.build_binding_protection(), m.ServerSecretBindingProtection)


@pytest.mark.parametrize(
    "value", ["token-derived", "TOKEN-DERIVED", "  token-derived "]
)
def test_the_variable_selects_the_token_derived_scheme(monkeypatch, value):
    monkeypatch.setenv("REDMINE_API_KEY_LOGIN_BINDING_CRYPTO", value)
    assert isinstance(m.build_binding_protection(), m.TokenDerivedBindingProtection)


@pytest.mark.parametrize("value", ["token_derived", "tokenderived", "on", ""])
def test_a_value_that_is_not_a_scheme_stops_the_server(monkeypatch, value):
    """Never fall back to the weaker default: the operator asked for the stronger."""
    monkeypatch.setenv("REDMINE_API_KEY_LOGIN_BINDING_CRYPTO", value)
    with pytest.raises(RuntimeError, match="BINDING_CRYPTO"):
        m.build_binding_protection()


def test_build_wires_the_selected_scheme_into_the_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("FASTMCP_HOME", str(tmp_path))
    with patch.dict(
        "os.environ",
        _env(REDMINE_API_KEY_LOGIN_BINDING_CRYPTO="token-derived"),
        clear=False,
    ):
        provider = m.build_api_key_login()

    assert isinstance(provider._protection, m.TokenDerivedBindingProtection)


def test_the_startup_warning_states_the_guarantee_that_is_in_force(
    monkeypatch, tmp_path, caplog
):
    """An operator reading the log must not be told the wrong threat model."""
    monkeypatch.setenv("FASTMCP_HOME", str(tmp_path))
    with patch.dict(
        "os.environ",
        _env(REDMINE_API_KEY_LOGIN_BINDING_CRYPTO="token-derived"),
        clear=False,
    ):
        with caplog.at_level("WARNING"):
            m.build_api_key_login()

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "token-derived" in text
    assert "do not open them" in text
    assert "can read them" not in text


def test_the_default_startup_warning_still_names_its_cost(
    monkeypatch, tmp_path, caplog
):
    monkeypatch.setenv("FASTMCP_HOME", str(tmp_path))
    monkeypatch.delenv("REDMINE_API_KEY_LOGIN_BINDING_CRYPTO", raising=False)
    with patch.dict("os.environ", _env(), clear=False):
        with caplog.at_level("WARNING"):
            m.build_api_key_login()

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "can read them" in text
    assert "token-derived" in text  # points at the way out


def test_each_scheme_states_its_own_guarantee():
    server = m.ServerSecretBindingProtection().storage_warning
    token = m.TokenDerivedBindingProtection().storage_warning

    assert "can read them" in server
    assert "do not open them" in token
    assert server != token


def test_a_scheme_that_states_no_guarantee_cannot_be_built():
    """The warning is part of the interface, so a third scheme cannot omit it."""

    class Incomplete(m.BindingProtection):
        def seal(self, payload):
            return {}, None

        def wrap(self, data_key, secret):
            return {}

        def unwrap(self, carrier, secret):
            return None

        def unseal(self, record, data_key):
            return None

    with pytest.raises(TypeError, match="storage_warning"):
        Incomplete()


# --- the root-access simulation -----------------------------------------


async def _login_only(provider):
    """Log in and stop at the redirect, leaving an unexchanged code on disk."""
    client = _client()
    await provider.register_client(client)
    url = await provider.authorize(client, _params())
    txn_id = url.split("txn=", 1)[1]
    txn = await provider.get_transaction(txn_id)
    with patch.object(m, "fetch_redmine_identity", AsyncMock(return_value=_identity())):
        redirect = await provider.complete_login(
            txn_id, txn["csrf"], KEY, browser_nonce=txn["browser_nonce"]
        )
    return client, redirect.split("code=", 1)[1].split("&", 1)[0]


async def _attacker_walk(home, secret):
    """Everything the store holds, opened the way the operator secret opens it."""
    reader = m.FernetEncryptionWrapper(
        key_value=m.FileTreeStore(data_directory=m.api_key_login_store_path(secret)),
        fernet=m.Fernet(key=m._storage_encryption_key(secret)),
        raise_on_decryption_error=False,
    )
    opened = []
    for collection in (
        m.COLLECTION_BINDINGS,
        m.COLLECTION_CODES,
        m.COLLECTION_ACCESS_TOKENS,
        m.COLLECTION_REFRESH_TOKENS,
        m.COLLECTION_ROTATED_REFRESH,
        m.COLLECTION_TRANSACTIONS,
    ):
        for path in (home / m.STORE_SUBDIR).glob(f"*/{collection}/*.json"):
            if path.name.endswith("-info.json"):
                continue
            record = await reader.get(path.stem, collection=collection)
            if record is not None:
                opened.append(record)
    return opened


def _key_recovered_from(opened):
    """Try to reach the API key using only what the walk turned up.

    Every string in every record is tried as the secret for every wrapped data
    key, and every data key so recovered against every sealed binding. This is
    the exploit rather than a field-name check: the ``code`` field passed a
    ``"api_key" not in dump`` assertion while handing the key over.
    """
    protection = m.TokenDerivedBindingProtection()
    strings = [v for r in opened for v in r.values() if isinstance(v, str)]
    data_keys = [
        key
        for record in opened
        if "wrapped_key" in record
        for secret in strings
        if (key := protection.unwrap(record, secret)) is not None
    ]
    for record in opened:
        for data_key in data_keys:
            payload = protection.unseal(record, data_key)
            if payload and payload.get("api_key"):
                return payload["api_key"]
    return None


async def test_the_operator_secret_does_not_open_a_real_store_on_disk(
    tmp_path, monkeypatch
):
    """The requirement, against the real file store rather than a fake.

    Plays the attacker who has the volume *and* REDMINE_MCP_JWT_SIGNING_KEY:
    peels the store's own Fernet layer off every file with the operator secret,
    exactly as the server would, and then tries to reach the key with what is
    there. Taken twice -- once while an unexchanged authorization code is still
    on disk, which is the window the plaintext ``code`` field used to open, and
    once after the exchange. Under ``server-secret`` this is where the key
    appears, which is the point of the contrast at the end.
    """
    secret = "the-operator-secret"
    monkeypatch.setattr(m.settings, "home", tmp_path)
    provider = _provider(m.build_store(secret))

    # --- snapshot 1: logged in, code minted, not yet exchanged ---
    client, code = await _login_only(provider)
    before = await _attacker_walk(tmp_path, secret)
    assert any(
        "wrapped_key" in r for r in before
    ), "no code record on disk, so this snapshot proves nothing"
    assert KEY not in json.dumps(before, default=str)
    assert code not in json.dumps(before, default=str)
    assert _key_recovered_from(before) is None

    # --- snapshot 2: after the exchange, with a live session ---
    auth_code = await provider.load_authorization_code(client, code)
    assert auth_code is not None and auth_code.code == code
    token = await provider.exchange_authorization_code(client, auth_code)
    assert (await provider.load_access_token(token.access_token)).claims[
        "redmine_api_key"
    ] == KEY

    files = [f for f in tmp_path.rglob("*.json") if f.is_file()]
    assert files, "the store wrote nothing"
    # The raw bytes, as a `strings` over the stolen volume would see them.
    assert not any(KEY.encode() in f.read_bytes() for f in files)

    after = await _attacker_walk(tmp_path, secret)
    assert after, "the operator secret opened nothing, so this proves nothing"
    assert KEY not in json.dumps(after, default=str)
    assert _key_recovered_from(after) is None

    # --- the contrast: the same walk under the default scheme hands it over ---
    monkeypatch.setattr(m.settings, "home", tmp_path / "default-scheme")
    default_secret = "another-operator-secret"
    default = _provider(
        m.build_store(default_secret), protection=m.ServerSecretBindingProtection()
    )
    await _session(default)
    plain = await _attacker_walk(tmp_path / "default-scheme", default_secret)
    assert any(r.get("api_key") == KEY for r in plain)
