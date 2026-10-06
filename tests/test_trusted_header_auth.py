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


class FakeRequest:
    """Minimal stand-in for a Starlette request."""

    def __init__(self, headers=None, scope=None):
        self.headers = headers if headers is not None else {}
        if scope is not None:
            self.scope = scope


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv("REDMINE_TRUSTED_HEADER_NAME", raising=False)
    monkeypatch.delenv("REDMINE_TRUSTED_HEADER_MATCH", raising=False)
    monkeypatch.delenv("REDMINE_TRUSTED_HEADER_TRUST_PROXY", raising=False)


@pytest.fixture
def mail_mode(monkeypatch):
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_MATCH", "mail")


@pytest.fixture
def configured(monkeypatch):
    """A complete trusted-header configuration, minus the Redmine answer."""
    monkeypatch.setenv("REDMINE_TRUSTED_HEADER_TRUST_PROXY", "true")
    with (
        patch.object(_client, "REDMINE_URL", "https://r.example.com"),
        patch.object(_client, "REDMINE_API_KEY", ADMIN_KEY),
    ):
        yield


def _probe_returns(status, admin=None):
    return patch.object(
        _trusted_header, "_probe_admin_key", return_value=(status, admin)
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
    ["", "has space", "x" * 61, "jsmith\n", "jsmith;admin", "../jsmith", "jsmith+1"],
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
    request.headers = headers
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
        _probe_returns(200, True) as probe,
        patch.object(_client, "Redmine"),
    ):
        _client._get_redmine_client()
        _client._get_redmine_client()
    probe.assert_called_once_with(ADMIN_KEY)


def test_client_checks_the_admin_key_again_for_the_next_request():
    requests_in_turn = MagicMock(
        side_effect=[
            _request({"X-Forwarded-User": "jsmith"}),
            _request({"X-Forwarded-User": "jsmith"}),
        ]
    )
    with (
        _trusted_header_mode(requests_in_turn),
        _probe_returns(200, True) as probe,
        patch.object(_client, "Redmine"),
    ):
        _client._get_redmine_client()
        _client._get_redmine_client()
    assert probe.call_count == 2


def test_client_does_not_remember_a_failed_check():
    with _trusted_header_mode(_serving({"X-Forwarded-User": "jsmith"})):
        with _probe_returns(200, False), pytest.raises(PerUserAuthError):
            _client._get_redmine_client()
        with _probe_returns(200, True) as probe, patch.object(_client, "Redmine"):
            _client._get_redmine_client()
    probe.assert_called_once_with(ADMIN_KEY)


@pytest.mark.parametrize(
    "status, admin, expected",
    [
        (200, False, "administrator"),
        (200, None, "administrator"),
        (401, None, "rejected"),
        (503, None, "HTTP 503"),
    ],
    ids=["no-longer-admin", "no-admin-flag", "key-rejected", "server-error"],
)
def test_client_refuses_when_the_key_cannot_switch_users(status, admin, expected):
    with (
        _trusted_header_mode(_serving({"X-Forwarded-User": "jsmith"})),
        _probe_returns(status, admin),
        patch.object(_client, "Redmine") as mock_redmine,
    ):
        with pytest.raises(PerUserAuthError) as exc:
            _client._get_redmine_client()
    assert expected in exc.value.message
    mock_redmine.assert_not_called()


def test_client_reports_unreachable_redmine_as_a_connection_error():
    with (
        _trusted_header_mode(_serving({"X-Forwarded-User": "jsmith"})),
        _probe_raises(requests.ConnectionError("refused")),
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


def test_refused_user_switch_maps_to_a_clear_error():
    result = _handle_redmine_error(ImpersonateError(), "listing issues")
    assert result["code"] == "PER_USER_AUTH"
    assert "does not exist" in result["error"]
    assert "locked" in result["error"]


# --- matching by email ----------------------------------------------------

ANNA = {"login": "anna", "mail": "anna@corp.example"}


def _users_response(status=200, users=(), json_error=None):
    response = MagicMock(status_code=status)
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = {"users": list(users)}
    return response


def _lookup_returns(response):
    return patch.object(_trusted_header, "_redmine_get", return_value=response)


def test_login_mode_uses_the_header_value_as_is():
    # Some Redmines use email addresses as logins; login mode never looks up.
    with _lookup_returns(_users_response()) as lookup:
        login = resolve_trusted_login(_request({"X-Forwarded-User": ANNA["mail"]}))
    assert login == ANNA["mail"]
    lookup.assert_not_called()


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
    users = [{"login": "anna", "mail": "Anna@Corp.Example"}]
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
        (200, {"user": {"id": 1, "admin": True}}, None, (200, True)),
        (200, {"user": {"id": 2, "admin": False}}, None, (200, False)),
        (200, {"user": {"id": 3}}, None, (200, None)),
        (200, {"user": {"admin": "true"}}, None, (200, None)),
        (200, ["not", "an", "object"], None, (200, None)),
        (200, None, ValueError("not json"), (200, None)),
        (401, None, None, (401, None)),
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
