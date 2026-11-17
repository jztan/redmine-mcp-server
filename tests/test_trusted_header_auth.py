"""Unit tests for the trusted-header auth mode (_trusted_header)."""

import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
import requests
from redminelib.exceptions import ImpersonateError
from starlette.datastructures import State

from redmine_mcp_server import _client, _per_user, _trusted_header
from redmine_mcp_server._errors import _handle_redmine_error
from redmine_mcp_server._per_user import PerUserAuthError
from redmine_mcp_server._trusted_header import (
    assert_startup_requirements,
    resolve_trusted_login,
)

ADMIN_KEY = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"  # 40 hex chars
VALID_SECRET = "s" * 32
DEFAULT_SECRET_HEADER = _trusted_header.DEFAULT_SECRET_HEADER_NAME


class FakeRequest:
    """Minimal stand-in for a Starlette request."""

    def __init__(self, headers=None, scope=None, include_secret=True):
        if isinstance(headers, dict):
            self.headers = (
                {DEFAULT_SECRET_HEADER: VALID_SECRET} if include_secret else {}
            )
            self.headers.update(headers)
        elif headers is not None:
            self.headers = headers
        else:
            self.headers = (
                {DEFAULT_SECRET_HEADER: VALID_SECRET} if include_secret else {}
            )
        if scope is not None:
            self.scope = scope


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv("REDMINE_TRUSTED_HEADER_NAME", raising=False)
    monkeypatch.delenv("REDMINE_TRUSTED_HEADER_MATCH", raising=False)
    monkeypatch.delenv("REDMINE_TRUSTED_HEADER_TRUST_PROXY", raising=False)
    monkeypatch.delenv("REDMINE_TRUSTED_HEADER_SECRET", raising=False)
    monkeypatch.delenv("REDMINE_TRUSTED_HEADER_ALLOW_ADMIN", raising=False)
    monkeypatch.setattr(_trusted_header, "_TRUSTED_HEADER_SECRET", VALID_SECRET)
    monkeypatch.setattr(_trusted_header, "_KEY_OWNER_ID", 1)


@pytest.fixture(autouse=True)
def _auto_mock_redmine(request):
    if "test_probe" in request.node.name or "test_redmine_get" in request.node.name:
        yield
        return

    def _fake_redmine_get(path, key, params=None):
        if path == "/users/current.json":
            resp = MagicMock(status_code=200)
            resp.json.return_value = {
                "user": {"id": 1, "admin": True, "login": "admin"}
            }
            return resp
        if path == "/users.json":
            name = ""
            if params:
                for k, v in params:
                    if k == "name":
                        name = v
                        break
            resp = MagicMock(status_code=200)
            resp.json.return_value = {
                "users": [
                    {
                        "id": 42,
                        "login": name,
                        "mail": name if "@" in name else f"{name}@corp.example",
                        "admin": False,
                        "status": 1,
                    }
                ],
                "total_count": 1,
            }
            return resp
        return MagicMock(status_code=404)

    with (
        patch.object(_client, "REDMINE_URL", "https://r.example.com"),
        patch.object(_client, "REDMINE_API_KEY", ADMIN_KEY),
        patch.object(_trusted_header, "_redmine_get", side_effect=_fake_redmine_get),
    ):
        yield


@pytest.fixture
def mail_mode(monkeypatch):
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_MATCH", "mail")


@pytest.fixture
def configured(monkeypatch):
    """A complete trusted-header configuration, minus the Redmine answer."""
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_TRUST_PROXY", "true")
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_SECRET", VALID_SECRET)
    with (
        patch.object(_client, "REDMINE_URL", "https://r.example.com"),
        patch.object(_client, "REDMINE_API_KEY", ADMIN_KEY),
    ):
        yield


def _probe_returns(status, admin=None, user_id=1):
    return patch.object(
        _trusted_header, "_probe_admin_key", return_value=(status, admin, user_id)
    )


def _probe_raises(exc):
    return patch.object(_trusted_header, "_probe_admin_key", side_effect=exc)


# --- reading the login ----------------------------------------------------


def test_resolve_returns_login_from_default_header():
    req = FakeRequest(headers={"X-Forwarded-User": "jsmith"})
    assert resolve_trusted_login(req) == "jsmith"


def test_resolve_reads_configured_header_name(monkeypatch):
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_NAME", "X-Remote-User")
    req = FakeRequest(headers={"X-Remote-User": "jsmith"})
    assert resolve_trusted_login(req) == "jsmith"


def test_resolve_ignores_default_header_when_another_is_configured(monkeypatch):
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_NAME", "X-Remote-User")
    req = FakeRequest(headers={"X-Forwarded-User": "jsmith"})
    with pytest.raises(PerUserAuthError) as exc:
        resolve_trusted_login(req)
    assert "X-Remote-User" in exc.value.message


def test_resolve_header_lookup_is_case_insensitive():
    req = FakeRequest(headers={"x-forwarded-user": "jsmith"})
    assert resolve_trusted_login(req) == "jsmith"


def test_resolve_accepts_every_character_redmine_allows_in_logins():
    login = "J.Smith-2_x@corp"
    req = FakeRequest(headers={"X-Forwarded-User": login})
    assert resolve_trusted_login(req) == login


def test_resolve_missing_header_raises():
    with pytest.raises(PerUserAuthError) as exc:
        resolve_trusted_login(FakeRequest(headers={}))
    assert "missing" in exc.value.message.lower()


def test_resolve_none_request_raises():
    with pytest.raises(PerUserAuthError):
        resolve_trusted_login(None)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "has space",
        "x" * 61,
        "jsmith\n",
        "jsmith;admin",
        "../jsmith",
        "jsmith+1",
        "\u212a",
        "\u0131",
    ],
)
def test_resolve_rejects_values_that_cannot_be_redmine_logins(bad):
    req = FakeRequest(headers={"X-Forwarded-User": bad})
    with pytest.raises(PerUserAuthError) as exc:
        resolve_trusted_login(req)
    assert "not a valid redmine login" in exc.value.message.lower()


def test_resolve_accepts_the_longest_redmine_login():
    login = "x" * 60
    assert resolve_trusted_login(FakeRequest(headers={"X-Forwarded-User": login}))


def test_resolve_logs_the_login(caplog):
    req = FakeRequest(headers={"X-Forwarded-User": "jsmith"})
    with caplog.at_level(logging.INFO, logger="redmine_mcp_server"):
        resolve_trusted_login(req)
    assert "jsmith" in " ".join(r.getMessage() for r in caplog.records)


def test_resolve_rejects_repeated_header_in_scope():
    req = FakeRequest(
        scope={
            "headers": [
                (DEFAULT_SECRET_HEADER.lower().encode(), VALID_SECRET.encode()),
                (b"x-forwarded-user", b"alice"),
                (b"x-forwarded-user", b"bob"),
            ]
        }
    )
    with pytest.raises(PerUserAuthError) as exc:
        resolve_trusted_login(req)
    assert "repeated X-Forwarded-User request header" in exc.value.message


def test_resolve_rejects_comma_joined_header():
    req = FakeRequest(headers={"X-Forwarded-User": "alice, bob"})
    with pytest.raises(PerUserAuthError) as exc:
        resolve_trusted_login(req)
    assert "repeated X-Forwarded-User request header" in exc.value.message


def test_resolve_rejects_missing_secret_header():
    req = FakeRequest(headers={"X-Forwarded-User": "jsmith"}, include_secret=False)
    with pytest.raises(PerUserAuthError) as exc:
        resolve_trusted_login(req)
    assert "missing X-Trusted-Proxy-Secret request header" in exc.value.message


def test_resolve_rejects_invalid_secret_header():
    req = FakeRequest(
        headers={"X-Forwarded-User": "jsmith", DEFAULT_SECRET_HEADER: "wrong" * 8}
    )
    with pytest.raises(PerUserAuthError) as exc:
        resolve_trusted_login(req)
    assert "invalid proxy secret" in exc.value.message


def test_resolve_rejects_repeated_secret_header_in_scope():
    req = FakeRequest(
        scope={
            "headers": [
                (DEFAULT_SECRET_HEADER.lower().encode(), VALID_SECRET.encode()),
                (DEFAULT_SECRET_HEADER.lower().encode(), VALID_SECRET.encode()),
                (b"x-forwarded-user", b"alice"),
            ]
        }
    )
    with pytest.raises(PerUserAuthError) as exc:
        resolve_trusted_login(req)
    assert "repeated X-Trusted-Proxy-Secret request header" in exc.value.message


def test_resolve_rejects_comma_joined_secret_header():
    req = FakeRequest(
        headers={
            "X-Forwarded-User": "jsmith",
            DEFAULT_SECRET_HEADER: f"{VALID_SECRET},{VALID_SECRET}",
        }
    )
    with pytest.raises(PerUserAuthError) as exc:
        resolve_trusted_login(req)
    # A merged value never equals the secret, so the comparison refuses it.
    assert "invalid proxy secret" in exc.value.message


def test_resolve_accepts_a_secret_with_a_comma(monkeypatch):
    secret = "a,b" + "c" * 37
    monkeypatch.setattr(_trusted_header, "_TRUSTED_HEADER_SECRET", secret)
    req = FakeRequest(
        headers={"X-Forwarded-User": "jsmith", DEFAULT_SECRET_HEADER: secret}
    )
    assert resolve_trusted_login(req) == "jsmith"


def test_resolve_refuses_when_no_secret_was_stored(monkeypatch):
    # Only assert_startup_requirements stores the secret; requests never read
    # the env var.
    monkeypatch.setattr(_trusted_header, "_TRUSTED_HEADER_SECRET", None)
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_SECRET", VALID_SECRET)
    req = FakeRequest(headers={"X-Forwarded-User": "jsmith"})
    with pytest.raises(PerUserAuthError) as exc:
        resolve_trusted_login(req)
    assert "invalid proxy secret" in exc.value.message


# --- header helper shared with legacy-per-user ----------------------------


def test_extract_header_reads_any_header_name():
    req = FakeRequest(headers={"X-Forwarded-User": "jsmith"})
    assert _per_user._extract_header(req, "X-Forwarded-User") == "jsmith"
    assert _per_user._extract_header(req, "X-Other") is None


def test_extract_header_asgi_scope_fallback():
    req = FakeRequest(
        headers=object(),  # no .get -> forces scope fallback
        scope={"headers": [(b"x-forwarded-user", b"jsmith")]},
    )
    assert _per_user._extract_header(req, "X-Forwarded-User") == "jsmith"


# --- startup requirements -------------------------------------------------


def test_startup_requires_attestation():
    with pytest.raises(RuntimeError) as exc:
        assert_startup_requirements()
    assert "REDMINE_TRUSTED_HEADER_TRUST_PROXY" in str(exc.value)


def test_startup_requires_redmine_url(monkeypatch):
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_TRUST_PROXY", "true")
    with (
        patch.object(_client, "REDMINE_URL", None),
        patch.object(_client, "REDMINE_API_KEY", ADMIN_KEY),
    ):
        with pytest.raises(RuntimeError) as exc:
            assert_startup_requirements()
    assert "REDMINE_URL" in str(exc.value)


def test_startup_requires_api_key(monkeypatch):
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_TRUST_PROXY", "true")
    with (
        patch.object(_client, "REDMINE_URL", "https://r.example.com"),
        patch.object(_client, "REDMINE_API_KEY", None),
    ):
        with pytest.raises(RuntimeError) as exc:
            assert_startup_requirements()
    assert "REDMINE_API_KEY" in str(exc.value)


def test_startup_rejects_key_redmine_does_not_accept(configured):
    with _probe_returns(401):
        with pytest.raises(RuntimeError) as exc:
            assert_startup_requirements()
    assert "rejected" in str(exc.value)


@pytest.mark.parametrize("admin", [False, None])
def test_startup_rejects_key_not_confirmed_as_admin(configured, admin):
    with _probe_returns(200, admin):
        with pytest.raises(RuntimeError) as exc:
            assert_startup_requirements()
    assert "administrator" in str(exc.value)


def test_startup_fails_when_redmine_is_unreachable(configured):
    with _probe_raises(requests.ConnectionError("refused")):
        with pytest.raises(RuntimeError) as exc:
            assert_startup_requirements()
    assert "could not reach Redmine" in str(exc.value)
    assert ADMIN_KEY not in str(exc.value)


def test_startup_fails_when_redmine_answers_with_an_error(configured):
    with _probe_returns(503):
        with pytest.raises(RuntimeError) as exc:
            assert_startup_requirements()
    assert "HTTP 503" in str(exc.value)


def test_startup_rejects_an_unknown_match_mode(configured, monkeypatch):
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_MATCH", "email")
    with _probe_returns(200, True):
        with pytest.raises(RuntimeError) as exc:
            assert_startup_requirements()
    assert "REDMINE_TRUSTED_HEADER_MATCH" in str(exc.value)


def test_startup_accepts_mail_mode(configured, mail_mode, caplog):
    with (
        _probe_returns(200, True),
        caplog.at_level(logging.WARNING, logger="redmine_mcp_server"),
    ):
        assert_startup_requirements()  # must not raise
    assert "whose email is in" in " ".join(r.getMessage() for r in caplog.records)


def test_startup_passes_with_admin_key_and_warns(configured, caplog):
    with (
        _probe_returns(200, True),
        caplog.at_level(logging.INFO, logger="redmine_mcp_server"),
    ):
        assert_startup_requirements()  # must not raise
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "ACTIVE" in joined
    assert "X-Forwarded-User" in joined
    assert ADMIN_KEY not in joined


def test_startup_requires_secret(configured, monkeypatch):
    monkeypatch.delenv("REDMINE_TRUSTED_HEADER_SECRET", raising=False)
    with _probe_returns(200, True):
        with pytest.raises(RuntimeError) as exc:
            assert_startup_requirements()
    assert "REDMINE_TRUSTED_HEADER_SECRET" in str(exc.value)


def test_startup_rejects_short_secret(configured, monkeypatch):
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_SECRET", "s" * 31)
    with _probe_returns(200, True):
        with pytest.raises(RuntimeError) as exc:
            assert_startup_requirements()
    assert "at least 32 characters" in str(exc.value)


def test_startup_rejects_secret_with_spaces(configured, monkeypatch):
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_SECRET", "s" * 31 + " ")
    with _probe_returns(200, True):
        with pytest.raises(RuntimeError) as exc:
            assert_startup_requirements()
    assert "printable ASCII characters without spaces" in str(exc.value)


def test_startup_rejects_non_ascii_secret(configured, monkeypatch):
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_SECRET", "s" * 31 + "é")
    with _probe_returns(200, True):
        with pytest.raises(RuntimeError) as exc:
            assert_startup_requirements()
    assert "printable ASCII characters without spaces" in str(exc.value)


def test_startup_accepts_a_secret_with_a_comma(configured, monkeypatch):
    secret = "a,b" + "c" * 37
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_SECRET", secret)
    with _probe_returns(200, True):
        assert_startup_requirements()  # must not raise
    assert _trusted_header._TRUSTED_HEADER_SECRET == secret


def test_startup_records_the_key_owner_id(configured):
    with _probe_returns(200, True, user_id=7):
        assert_startup_requirements()
    assert _trusted_header._KEY_OWNER_ID == 7


def test_startup_refuses_without_the_key_owner_id(configured):
    with _probe_returns(200, True, user_id=None):
        with pytest.raises(RuntimeError) as exc:
            assert_startup_requirements()
    assert "did not return the id" in str(exc.value)


# --- the Redmine client ---------------------------------------------------


@contextmanager
def _trusted_header_mode(get_http_request):
    """Put _client in trusted-header mode, with ``get_http_request`` patched
    and Redmine confirming an administrator key unless a test says otherwise.
    """
    with (
        patch.object(_client, "REDMINE_URL", "https://r.example.com"),
        patch.object(_client, "REDMINE_API_KEY", ADMIN_KEY),
        patch.object(_client, "REDMINE_AUTH_MODE", "trusted-header"),
        patch.object(_client, "redmine", None),
        patch.object(_client, "_build_requests_config", return_value={}),
        patch.object(_client, "get_http_request", get_http_request),
        _probe_returns(200, True),
    ):
        yield


def _request(headers):
    request = MagicMock()
    h = {DEFAULT_SECRET_HEADER: VALID_SECRET}
    if headers is not None:
        h.update(headers)
    request.headers = h
    request.state = State()
    return request


def _serving(headers):
    """A get_http_request that keeps returning one and the same request."""
    return MagicMock(return_value=_request(headers))


def test_client_switches_to_the_login_from_the_header():
    with (
        _trusted_header_mode(_serving({"X-Forwarded-User": "jsmith"})),
        patch.object(_client, "Redmine") as mock_redmine,
    ):
        _client._get_redmine_client()
    mock_redmine.assert_called_once_with(
        "https://r.example.com",
        engine=_client.TimeoutSyncEngine,
        key=ADMIN_KEY,
        impersonate="jsmith",
    )


def test_client_gives_each_request_its_own_user():
    # Real python-redmine clients: one request's user must not reach another.
    with _trusted_header_mode(_serving({"X-Forwarded-User": "alice"})):
        alice = _client._get_redmine_client()
    with _trusted_header_mode(_serving({"X-Forwarded-User": "bob"})):
        bob = _client._get_redmine_client()
    assert alice.engine.session.headers["X-Redmine-Switch-User"] == "alice"
    assert bob.engine.session.headers["X-Redmine-Switch-User"] == "bob"
    assert alice.engine.session.headers["X-Redmine-API-Key"] == ADMIN_KEY
    assert bob.engine.session.headers["X-Redmine-API-Key"] == ADMIN_KEY


def test_client_without_the_header_raises_instead_of_using_the_shared_client():
    with (
        _trusted_header_mode(_serving({})),
        patch.object(_client, "_legacy_client", MagicMock(name="shared client")),
        patch.object(_client, "Redmine") as mock_redmine,
    ):
        with pytest.raises(PerUserAuthError):
            _client._get_redmine_client()
    mock_redmine.assert_not_called()


def test_client_without_a_request_context_raises():
    with (
        _trusted_header_mode(MagicMock(side_effect=RuntimeError("no request"))),
        patch.object(_client, "Redmine") as mock_redmine,
    ):
        with pytest.raises(PerUserAuthError):
            _client._get_redmine_client()
    mock_redmine.assert_not_called()


def test_client_checks_the_admin_key_once_per_request():
    # A tool that builds several clients while serving one request.
    with (
        _trusted_header_mode(_serving({"X-Forwarded-User": "jsmith"})),
        _lookup_returns(
            _users_response(users=[{"id": 42, "login": "jsmith", "admin": False}])
        ) as lookup,
        patch.object(_client, "Redmine"),
    ):
        _client._get_redmine_client()
        _client._get_redmine_client()
    lookup.assert_called_once()


def test_client_checks_the_admin_key_again_for_the_next_request():
    requests_in_turn = MagicMock(
        side_effect=[
            _request({"X-Forwarded-User": "jsmith"}),
            _request({"X-Forwarded-User": "jsmith"}),
        ]
    )
    with (
        _trusted_header_mode(requests_in_turn),
        _lookup_returns(
            _users_response(users=[{"id": 42, "login": "jsmith", "admin": False}])
        ) as lookup,
        patch.object(_client, "Redmine"),
    ):
        _client._get_redmine_client()
        _client._get_redmine_client()
    assert lookup.call_count == 2


def test_client_does_not_remember_a_failed_check():
    with _trusted_header_mode(_serving({"X-Forwarded-User": "jsmith"})):
        with (
            _lookup_returns(_users_response(status=403)),
            pytest.raises(PerUserAuthError),
        ):
            _client._get_redmine_client()
        with (
            _lookup_returns(
                _users_response(users=[{"id": 42, "login": "jsmith", "admin": False}])
            ) as lookup,
            patch.object(_client, "Redmine"),
        ):
            _client._get_redmine_client()
    assert lookup.call_count == 1


@pytest.mark.parametrize(
    "status, expected",
    [
        (401, "refused"),
        (403, "refused"),
        (503, "HTTP 503"),
    ],
    ids=["key-rejected", "no-longer-admin", "server-error"],
)
def test_client_refuses_when_the_key_cannot_switch_users(status, expected):
    with (
        _trusted_header_mode(_serving({"X-Forwarded-User": "jsmith"})),
        _lookup_returns(_users_response(status=status)),
        patch.object(_client, "Redmine") as mock_redmine,
    ):
        with pytest.raises(PerUserAuthError) as exc:
            _client._get_redmine_client()
    assert expected in exc.value.message
    mock_redmine.assert_not_called()


def test_client_reports_unreachable_redmine_as_a_connection_error():
    with (
        _trusted_header_mode(_serving({"X-Forwarded-User": "jsmith"})),
        patch.object(
            _trusted_header,
            "_redmine_get",
            side_effect=requests.ConnectionError("refused"),
        ),
        patch.object(_client, "Redmine") as mock_redmine,
    ):
        with pytest.raises(requests.ConnectionError) as exc:
            _client._get_redmine_client()
    result = _handle_redmine_error(exc.value, "listing issues")
    assert result["code"] == "CONNECTION_FAILED"
    mock_redmine.assert_not_called()


def test_client_reads_the_login_before_asking_redmine():
    with (
        _trusted_header_mode(_serving({})),
        _probe_returns(200, True) as probe,
    ):
        with pytest.raises(PerUserAuthError):
            _client._get_redmine_client()
    probe.assert_not_called()


# --- app startup and error mapping ----------------------------------------


def test_build_app_runs_the_startup_checks():
    from redmine_mcp_server import main

    with (
        patch.object(main, "REDMINE_AUTH_MODE", "trusted-header"),
        patch.object(_trusted_header, "assert_startup_requirements") as checks,
    ):
        main.build_app()
    checks.assert_called_once_with()


def test_build_app_refuses_to_start_when_the_checks_fail():
    from redmine_mcp_server import main

    with (
        patch.object(main, "REDMINE_AUTH_MODE", "trusted-header"),
        patch.object(
            _trusted_header,
            "assert_startup_requirements",
            side_effect=RuntimeError("not an administrator"),
        ),
    ):
        with pytest.raises(RuntimeError, match="not an administrator"):
            main.build_app()


def test_build_app_installs_trusted_header_middleware():
    from redmine_mcp_server import main
    from redmine_mcp_server._trusted_header import TrustedHeaderMiddleware

    with (
        patch.object(main, "REDMINE_AUTH_MODE", "trusted-header"),
        patch.object(_trusted_header, "assert_startup_requirements"),
    ):
        app = main.build_app()
    assert any(m.cls is TrustedHeaderMiddleware for m in app.user_middleware)


def test_refused_user_switch_maps_to_a_clear_error():
    result = _handle_redmine_error(ImpersonateError(), "listing issues")
    assert result["code"] == "PER_USER_AUTH"
    assert "does not exist" in result["error"]
    assert "not active" in result["error"]


def test_middleware_allows_health_without_secret():
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    app = Starlette(
        routes=[
            Route(
                "/health", lambda r: PlainTextResponse("ok"), methods=["GET", "HEAD"]
            ),
            Route(
                "/mcp", lambda r: PlainTextResponse("mcp-ok"), methods=["GET", "POST"]
            ),
        ],
        middleware=[Middleware(_trusted_header.TrustedHeaderMiddleware)],
    )
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.head("/health").status_code == 200


def test_middleware_blocks_non_health_without_secret():
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    app = Starlette(
        routes=[
            Route(
                "/mcp", lambda r: PlainTextResponse("mcp-ok"), methods=["GET", "POST"]
            ),
            Route("/files/1", lambda r: PlainTextResponse("file-ok"), methods=["GET"]),
        ],
        middleware=[Middleware(_trusted_header.TrustedHeaderMiddleware)],
    )
    client = TestClient(app)

    assert client.get("/mcp").status_code == 401
    assert client.post("/mcp").status_code == 401
    assert client.get("/files/1").status_code == 401


def test_middleware_blocks_wrong_secret():
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    app = Starlette(
        routes=[
            Route(
                "/mcp", lambda r: PlainTextResponse("mcp-ok"), methods=["GET", "POST"]
            ),
        ],
        middleware=[Middleware(_trusted_header.TrustedHeaderMiddleware)],
    )
    client = TestClient(app)

    resp = client.get("/mcp", headers={DEFAULT_SECRET_HEADER: "wrong" * 8})
    assert resp.status_code == 401


def test_middleware_blocks_repeated_secret_header():
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    app = Starlette(
        routes=[
            Route(
                "/mcp", lambda r: PlainTextResponse("mcp-ok"), methods=["GET", "POST"]
            ),
        ],
        middleware=[Middleware(_trusted_header.TrustedHeaderMiddleware)],
    )
    client = TestClient(app)

    resp = client.get(
        "/mcp",
        headers=[
            (DEFAULT_SECRET_HEADER, VALID_SECRET),
            (DEFAULT_SECRET_HEADER, VALID_SECRET),
        ],
    )
    assert resp.status_code == 401


def test_middleware_allows_valid_secret():
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    app = Starlette(
        routes=[
            Route(
                "/mcp", lambda r: PlainTextResponse("mcp-ok"), methods=["GET", "POST"]
            ),
        ],
        middleware=[Middleware(_trusted_header.TrustedHeaderMiddleware)],
    )
    client = TestClient(app)

    resp = client.get("/mcp", headers={DEFAULT_SECRET_HEADER: VALID_SECRET})
    assert resp.status_code == 200
    assert resp.text == "mcp-ok"


def _guarded_client(**client_kwargs):
    """A TestClient for /health and /mcp behind TrustedHeaderMiddleware."""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    app = Starlette(
        routes=[
            Route("/health", lambda r: PlainTextResponse("ok"), methods=["GET"]),
            Route("/mcp", lambda r: PlainTextResponse("mcp-ok"), methods=["GET"]),
        ],
        middleware=[Middleware(_trusted_header.TrustedHeaderMiddleware)],
    )
    return TestClient(app, **client_kwargs)


def test_middleware_allows_health_behind_a_root_path():
    # Matched with get_route_path, so a root_path doesn't break the Docker
    # healthcheck.
    client = _guarded_client(root_path="/redmine")
    assert client.get("/redmine/health").status_code == 200
    assert client.get("/redmine/mcp").status_code == 401


def test_middleware_allows_a_secret_with_a_comma(monkeypatch):
    secret = "a,b" + "c" * 37
    monkeypatch.setattr(_trusted_header, "_TRUSTED_HEADER_SECRET", secret)
    resp = _guarded_client().get("/mcp", headers={DEFAULT_SECRET_HEADER: secret})
    assert resp.status_code == 200


def test_middleware_refuses_when_no_secret_was_stored(monkeypatch):
    monkeypatch.setattr(_trusted_header, "_TRUSTED_HEADER_SECRET", None)
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_SECRET", VALID_SECRET)
    resp = _guarded_client().get("/mcp", headers={DEFAULT_SECRET_HEADER: VALID_SECRET})
    assert resp.status_code == 401


# --- matching by email ----------------------------------------------------

ANNA = {"id": 7, "login": "anna", "mail": "anna@corp.example", "admin": False}


def _users_response(status=200, users=(), json_error=None):
    response = MagicMock(status_code=status)
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = {"users": list(users)}
    return response


def _lookup_returns(response):
    return patch.object(_trusted_header, "_redmine_get", return_value=response)


def test_login_mode_looks_up_and_matches_by_login():
    users = [{"id": 5, "login": "anna", "admin": False}]
    with _lookup_returns(_users_response(users=users)) as lookup:
        login = resolve_trusted_login(_request({"X-Forwarded-User": "anna"}))
    assert login == "anna"
    assert lookup.call_args.args == ("/users.json", ADMIN_KEY)
    assert lookup.call_args.kwargs["params"] == [
        ("name", "anna"),
        ("status", "1"),
        ("limit", "100"),
    ]


def test_mail_mode_resolves_the_email_to_a_login(mail_mode):
    with (
        patch.object(_client, "REDMINE_API_KEY", ADMIN_KEY),
        _lookup_returns(_users_response(users=[ANNA])) as lookup,
    ):
        login = resolve_trusted_login(_request({"X-Forwarded-User": ANNA["mail"]}))
    assert login == "anna"
    assert lookup.call_args.args == ("/users.json", ADMIN_KEY)
    assert lookup.call_args.kwargs["params"] == [
        ("name", ANNA["mail"]),
        ("status", "1"),
        ("limit", "100"),
    ]


def test_mail_mode_ignores_case(mail_mode):
    users = [{**ANNA, "mail": "Anna@Corp.Example"}]
    with _lookup_returns(_users_response(users=users)):
        login = resolve_trusted_login(_request({"X-Forwarded-User": ANNA["mail"]}))
    assert login == "anna"


@pytest.mark.parametrize(
    "users",
    [[], [{"login": "anna", "mail": "anna@corp.example.org"}]],
    ids=["no-user", "only-a-longer-address"],
)
def test_mail_mode_refuses_without_an_exact_match(mail_mode, users):
    with _lookup_returns(_users_response(users=users)):
        with pytest.raises(PerUserAuthError) as exc:
            resolve_trusted_login(_request({"X-Forwarded-User": ANNA["mail"]}))
    assert "no active Redmine user" in exc.value.message


def test_mail_mode_refuses_several_matches(mail_mode):
    users = [ANNA, {"login": "anna2", "mail": "ANNA@corp.example"}]
    with _lookup_returns(_users_response(users=users)):
        with pytest.raises(PerUserAuthError) as exc:
            resolve_trusted_login(_request({"X-Forwarded-User": ANNA["mail"]}))
    assert "several" in exc.value.message


@pytest.mark.parametrize(
    "status, expected",
    [(401, "refused"), (403, "refused"), (500, "HTTP 500")],
)
def test_mail_mode_refuses_when_the_lookup_fails(mail_mode, status, expected):
    with _lookup_returns(_users_response(status=status)):
        with pytest.raises(PerUserAuthError) as exc:
            resolve_trusted_login(_request({"X-Forwarded-User": ANNA["mail"]}))
    assert expected in exc.value.message


@pytest.mark.parametrize(
    "response",
    [
        _users_response(json_error=ValueError("not json")),
        MagicMock(status_code=200, json=MagicMock(return_value={"users": "x"})),
        _users_response(users=[{"mail": ANNA["mail"]}]),
    ],
    ids=["not-json", "users-not-a-list", "no-login"],
)
def test_mail_mode_refuses_an_unexpected_response(mail_mode, response):
    with _lookup_returns(response):
        with pytest.raises(PerUserAuthError) as exc:
            resolve_trusted_login(_request({"X-Forwarded-User": ANNA["mail"]}))
    assert "unexpected response" in exc.value.message


@pytest.mark.parametrize(
    "bad",
    [
        "anna",
        "anna@",
        "@corp.example",
        "an na@corp.example",
        "anna@corp.example\n",
        "a" * 245 + "@corp.example",  # 258 characters, over Redmine's 254
    ],
)
def test_mail_mode_refuses_values_that_are_not_emails(mail_mode, bad):
    with _lookup_returns(_users_response(users=[ANNA])) as lookup:
        with pytest.raises(PerUserAuthError) as exc:
            resolve_trusted_login(_request({"X-Forwarded-User": bad}))
    assert "not a valid email address" in exc.value.message
    lookup.assert_not_called()


def test_mail_mode_looks_up_once_per_request(mail_mode):
    request = _request({"X-Forwarded-User": ANNA["mail"]})
    with _lookup_returns(_users_response(users=[ANNA])) as lookup:
        resolve_trusted_login(request)
        assert resolve_trusted_login(request) == "anna"
    lookup.assert_called_once()


def test_mail_mode_looks_up_again_for_the_next_request(mail_mode):
    with _lookup_returns(_users_response(users=[ANNA])) as lookup:
        resolve_trusted_login(_request({"X-Forwarded-User": ANNA["mail"]}))
        resolve_trusted_login(_request({"X-Forwarded-User": ANNA["mail"]}))
    assert lookup.call_count == 2


def test_mail_mode_does_not_remember_a_failed_lookup(mail_mode):
    request = _request({"X-Forwarded-User": ANNA["mail"]})
    with _lookup_returns(_users_response(users=[])):
        with pytest.raises(PerUserAuthError):
            resolve_trusted_login(request)
    with _lookup_returns(_users_response(users=[ANNA])) as lookup:
        assert resolve_trusted_login(request) == "anna"
    lookup.assert_called_once()


def test_client_switches_to_the_user_found_by_email(mail_mode):
    with (
        _trusted_header_mode(_serving({"X-Forwarded-User": ANNA["mail"]})),
        _lookup_returns(_users_response(users=[ANNA])),
        patch.object(_client, "Redmine") as mock_redmine,
    ):
        _client._get_redmine_client()
    mock_redmine.assert_called_once_with(
        "https://r.example.com",
        engine=_client.TimeoutSyncEngine,
        key=ADMIN_KEY,
        impersonate="anna",
    )


def test_client_reports_an_unreachable_lookup_as_a_connection_error(mail_mode):
    with (
        _trusted_header_mode(_serving({"X-Forwarded-User": ANNA["mail"]})),
        patch.object(
            _trusted_header,
            "_redmine_get",
            side_effect=requests.ConnectionError("refused"),
        ),
        patch.object(_client, "Redmine") as mock_redmine,
    ):
        with pytest.raises(requests.ConnectionError):
            _client._get_redmine_client()
    mock_redmine.assert_not_called()


# --- Problem #2: Admin targets, key owner refusal & pagination ------------


def test_resolve_refuses_admin_target_by_default():
    admin_user = {"id": 10, "login": "superadmin", "admin": True}
    with _lookup_returns(_users_response(users=[admin_user])):
        with pytest.raises(PerUserAuthError) as exc:
            resolve_trusted_login(_request({"X-Forwarded-User": "superadmin"}))
    assert "refusing to run request as administrator" in exc.value.message
    assert "REDMINE_TRUSTED_HEADER_ALLOW_ADMIN is false" in exc.value.message


def test_resolve_allows_admin_target_when_flag_enabled(monkeypatch):
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_ALLOW_ADMIN", "true")
    admin_user = {"id": 10, "login": "superadmin", "admin": True}
    with _lookup_returns(_users_response(users=[admin_user])):
        assert (
            resolve_trusted_login(_request({"X-Forwarded-User": "superadmin"}))
            == "superadmin"
        )


def test_resolve_always_refuses_key_owner_even_with_flag(monkeypatch):
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_ALLOW_ADMIN", "true")
    # Key owner ID was recorded as 1 in _isolated fixture
    owner_user = {"id": 1, "login": "keyowner", "admin": True}
    with _lookup_returns(_users_response(users=[owner_user])):
        with pytest.raises(PerUserAuthError) as exc:
            resolve_trusted_login(_request({"X-Forwarded-User": "keyowner"}))
    assert (
        "refusing to run request as the account that owns REDMINE_API_KEY"
        in exc.value.message
    )


def test_resolve_refuses_when_the_key_owner_is_unknown(monkeypatch):
    monkeypatch.setattr(_trusted_header, "_KEY_OWNER_ID", None)
    with pytest.raises(PerUserAuthError) as exc:
        resolve_trusted_login(_request({"X-Forwarded-User": "jsmith"}))
    assert "owns REDMINE_API_KEY is unknown" in exc.value.message


@pytest.mark.parametrize(
    "entry",
    [
        {"id": 42, "login": "jsmith"},
        {"id": 42, "login": "jsmith", "admin": "false"},
        {"login": "jsmith", "admin": False},
    ],
    ids=["no-admin-flag", "string-admin-flag", "no-id"],
)
def test_resolve_refuses_a_user_entry_it_cannot_check(entry):
    with _lookup_returns(_users_response(users=[entry])):
        with pytest.raises(PerUserAuthError) as exc:
            resolve_trusted_login(_request({"X-Forwarded-User": "jsmith"}))
    assert "unexpected response" in exc.value.message


def test_resolve_paginates_user_lookup():
    # Page 1: 100 users, target not there
    page1_users = [
        {"id": 100 + i, "login": f"user{i}", "admin": False} for i in range(100)
    ]
    # Page 2: target user is here
    page2_users = [{"id": 500, "login": "targetuser", "admin": False}]

    call_count = 0

    def _paged_get(path, key, params=None):
        nonlocal call_count
        call_count += 1
        resp = MagicMock(status_code=200)
        p_dict = dict(params or [])
        offset = int(p_dict.get("offset", 0))
        if offset == 0:
            resp.json.return_value = {"users": page1_users, "total_count": 101}
        else:
            resp.json.return_value = {"users": page2_users, "total_count": 101}
        return resp

    with patch.object(_trusted_header, "_redmine_get", side_effect=_paged_get):
        login = resolve_trusted_login(_request({"X-Forwarded-User": "targetuser"}))
    assert login == "targetuser"
    assert call_count == 2


def test_resolve_refuses_when_pagination_exceeds_10_pages():
    # Returns 100 users on every page with total_count=1500
    page_users = [
        {"id": 100 + i, "login": f"other{i}", "admin": False} for i in range(100)
    ]
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"users": page_users, "total_count": 1500}

    with patch.object(_trusted_header, "_redmine_get", return_value=resp):
        with pytest.raises(PerUserAuthError) as exc:
            resolve_trusted_login(_request({"X-Forwarded-User": "targetuser"}))
    assert "exceeded maximum page limit" in exc.value.message


# --- the probe itself -----------------------------------------------------


def _fake_session(status, body=None, json_error=None):
    response = MagicMock(status_code=status)
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = body
    session = MagicMock()
    session.__enter__.return_value = session
    session.get.return_value = response
    return session


@pytest.mark.parametrize(
    "status, body, json_error, expected",
    [
        (200, {"user": {"id": 1, "admin": True}}, None, (200, True, 1)),
        (200, {"user": {"id": 2, "admin": False}}, None, (200, False, 2)),
        (200, {"user": {"id": 3}}, None, (200, None, 3)),
        (200, {"user": {"admin": "true"}}, None, (200, None, None)),
        (200, ["not", "an", "object"], None, (200, None, None)),
        (200, None, ValueError("not json"), (200, None, None)),
        (401, None, None, (401, None, None)),
    ],
    ids=["admin", "not-admin", "no-flag", "string-flag", "list", "not-json", "401"],
)
def test_probe_reads_admin_flag(status, body, json_error, expected):
    session = _fake_session(status, body, json_error)
    with (
        patch.object(_client, "REDMINE_URL", "https://r.example.com/"),
        patch.object(_client, "_build_requests_config", return_value={}),
        patch.object(_trusted_header.requests, "Session", return_value=session),
    ):
        assert _trusted_header._probe_admin_key(ADMIN_KEY) == expected


def test_probe_sends_key_in_header_and_does_not_follow_redirects():
    session = _fake_session(200, {"user": {"admin": True}})
    with (
        patch.object(_client, "REDMINE_URL", "https://r.example.com/"),
        patch.object(_client, "_build_requests_config", return_value={}),
        patch.object(_trusted_header.requests, "Session", return_value=session),
    ):
        _trusted_header._probe_admin_key(ADMIN_KEY)
    args, kwargs = session.get.call_args
    assert args == ("https://r.example.com/users/current.json",)
    assert kwargs["headers"] == {"X-Redmine-API-Key": ADMIN_KEY}
    assert kwargs["allow_redirects"] is False


def test_redmine_get_sends_the_query_parameters():
    session = _fake_session(200, {"users": []})
    with (
        patch.object(_client, "REDMINE_URL", "https://r.example.com/"),
        patch.object(_client, "_build_requests_config", return_value={}),
        patch.object(_trusted_header.requests, "Session", return_value=session),
    ):
        _trusted_header._redmine_get("/users.json", ADMIN_KEY, params=[("limit", "1")])
    args, kwargs = session.get.call_args
    assert args == ("https://r.example.com/users.json",)
    assert kwargs["params"] == [("limit", "1")]
    assert kwargs["headers"] == {"X-Redmine-API-Key": ADMIN_KEY}
    assert kwargs["allow_redirects"] is False
