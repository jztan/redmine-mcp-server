"""Unit tests for legacy-per-user key validation against Redmine (issue #290).

Redmine serves an unknown or reset API key as the anonymous user on any
endpoint anonymous may read, so a format check alone lets a bad key quietly
return the anonymous view. Each distinct key is now checked once with
GET /users/current.json and the outcome cached in-process.
"""

import logging
import threading
from unittest.mock import MagicMock, patch

import pytest
import requests

from redmine_mcp_server import _client, _per_user
from redmine_mcp_server._per_user import PerUserAuthError, validate_key_with_redmine

VALID_KEY = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
OTHER_KEY = "ffffffffffffffffffffffffffffffffffff5678"  # same last 4 chars


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    _per_user._clear_key_cache()
    monkeypatch.setattr(_client, "REDMINE_URL", "https://redmine.example.com")
    yield
    _per_user._clear_key_cache()


@pytest.fixture
def clock(monkeypatch):
    """Controllable monotonic clock for TTL tests."""
    now = [1000.0]
    monkeypatch.setattr(_per_user.time, "monotonic", lambda: now[0])
    return now


def _probe_returning(status):
    return patch.object(_per_user, "_probe_key", return_value=status)


# --- outcome handling --------------------------------------------------------


def test_valid_key_is_accepted_and_cached():
    with _probe_returning(200) as probe:
        validate_key_with_redmine(VALID_KEY)
        validate_key_with_redmine(VALID_KEY)
    assert probe.call_count == 1


def test_valid_key_cache_expires_after_five_minutes(clock):
    with _probe_returning(200) as probe:
        validate_key_with_redmine(VALID_KEY)
        clock[0] += 299
        validate_key_with_redmine(VALID_KEY)
        assert probe.call_count == 1
        clock[0] += 2
        validate_key_with_redmine(VALID_KEY)
    assert probe.call_count == 2


def test_401_is_rejected_with_per_user_auth_error():
    with _probe_returning(401):
        with pytest.raises(PerUserAuthError) as exc:
            validate_key_with_redmine(VALID_KEY)
    assert "did not accept this API key" in exc.value.message
    assert VALID_KEY not in exc.value.message
    assert VALID_KEY not in str(exc.value)


def test_401_is_negatively_cached_for_a_short_time(clock):
    with _probe_returning(401) as probe:
        for _ in range(2):
            with pytest.raises(PerUserAuthError):
                validate_key_with_redmine(VALID_KEY)
        assert probe.call_count == 1
        clock[0] += 61
        probe.return_value = 200
        validate_key_with_redmine(VALID_KEY)
    assert probe.call_count == 2


def test_negative_ttl_is_shorter_than_positive_ttl():
    assert _per_user._KEY_REJECTED_TTL < _per_user._KEY_VALID_TTL
    assert _per_user._KEY_VALID_TTL == 300


@pytest.mark.parametrize("status", [403, 404, 500, 502, 503, 301, 302])
def test_non_401_statuses_pass_through_and_are_not_cached(status):
    with _probe_returning(status) as probe:
        validate_key_with_redmine(VALID_KEY)
        validate_key_with_redmine(VALID_KEY)
    assert probe.call_count == 2


@pytest.mark.parametrize(
    "exc",
    [
        requests.Timeout("slow"),
        requests.ConnectionError("down"),
        requests.exceptions.SSLError("bad cert"),
        OSError("socket"),
    ],
)
def test_transport_errors_pass_through_and_are_not_cached(exc):
    with patch.object(_per_user, "_probe_key", side_effect=exc) as probe:
        validate_key_with_redmine(VALID_KEY)
        validate_key_with_redmine(VALID_KEY)
    assert probe.call_count == 2


def test_outage_then_401_still_rejects():
    """A pass-through outcome must not poison the cache as 'valid'."""
    with patch.object(
        _per_user, "_probe_key", side_effect=[requests.Timeout("x"), 401]
    ):
        validate_key_with_redmine(VALID_KEY)
        with pytest.raises(PerUserAuthError):
            validate_key_with_redmine(VALID_KEY)


def test_cache_distinguishes_keys_sharing_a_fingerprint():
    """_fingerprint() is only the last 4 chars; the cache must not collide on
    it, or a rejected stranger's key would lock out a valid user."""
    assert _per_user._fingerprint(VALID_KEY) == _per_user._fingerprint(OTHER_KEY)
    with patch.object(
        _per_user,
        "_probe_key",
        side_effect=lambda k: 401 if k == OTHER_KEY else 200,
    ):
        with pytest.raises(PerUserAuthError):
            validate_key_with_redmine(OTHER_KEY)
        validate_key_with_redmine(VALID_KEY)


def test_cache_never_stores_the_raw_key():
    with _probe_returning(200):
        validate_key_with_redmine(VALID_KEY)
    assert VALID_KEY not in repr(_per_user._key_cache)
    assert all(VALID_KEY not in k for k in _per_user._key_cache)


def test_no_redmine_url_skips_validation(monkeypatch):
    monkeypatch.setattr(_client, "REDMINE_URL", None)
    with _probe_returning(401) as probe:
        validate_key_with_redmine(VALID_KEY)
    probe.assert_not_called()


# --- cache bound and concurrency --------------------------------------------


def _key(i):
    return f"{i:040x}"


def test_cache_is_bounded_and_evicts_oldest(monkeypatch):
    monkeypatch.setattr(_per_user, "_KEY_CACHE_MAX", 3)
    with _probe_returning(200) as probe:
        for i in range(4):
            validate_key_with_redmine(_key(i))
        assert len(_per_user._key_cache) == 3
        # Newest three are still cached...
        for i in (1, 2, 3):
            validate_key_with_redmine(_key(i))
        assert probe.call_count == 4
        # ...and the oldest was evicted, so it is probed again.
        validate_key_with_redmine(_key(0))
    assert probe.call_count == 5


def test_default_cache_bound():
    assert _per_user._KEY_CACHE_MAX == 1024


def test_concurrent_threads_keep_cache_consistent_and_bounded(monkeypatch):
    monkeypatch.setattr(_per_user, "_KEY_CACHE_MAX", 50)
    errors = []
    barrier = threading.Barrier(16)

    def worker(t):
        try:
            barrier.wait()
            for i in range(200):
                validate_key_with_redmine(_key(t * 1000 + i % 60))
        except Exception as e:  # pragma: no cover - surfaced below
            errors.append(e)

    with _probe_returning(200):
        threads = [threading.Thread(target=worker, args=(t,)) for t in range(16)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
    assert errors == []
    assert len(_per_user._key_cache) <= 50


def test_cache_operations_use_the_module_lock():
    assert isinstance(_per_user._key_cache_lock, type(threading.Lock()))
    held = []

    def probe(_key):
        # The HTTP call must not run while holding the lock, or one slow
        # Redmine response would stall every other user's first request.
        held.append(_per_user._key_cache_lock.locked())
        return 200

    with patch.object(_per_user, "_probe_key", side_effect=probe):
        validate_key_with_redmine(VALID_KEY)
    assert held == [False]


# --- the probe itself --------------------------------------------------------


def _fake_session(status=200):
    session = MagicMock()
    session.__enter__.return_value = session
    session.get.return_value = MagicMock(status_code=status)
    return session


def test_probe_sends_key_header_only(monkeypatch):
    monkeypatch.setattr(_client, "_build_requests_config", lambda: {})
    session = _fake_session(200)
    with patch.object(_per_user.requests, "Session", return_value=session):
        assert _per_user._probe_key(VALID_KEY) == 200
    args, kwargs = session.get.call_args
    assert args[0] == "https://redmine.example.com/users/current.json"
    assert kwargs["headers"] == {"X-Redmine-API-Key": VALID_KEY}
    assert kwargs["allow_redirects"] is False
    assert "auth" not in kwargs
    assert not kwargs.get("params")
    assert "key=" not in args[0]


def test_probe_uses_redmine_timeout(monkeypatch):
    monkeypatch.setattr(_client, "_build_requests_config", lambda: {})
    monkeypatch.setenv("REDMINE_TIMEOUT", "7")
    session = _fake_session(200)
    with patch.object(_per_user.requests, "Session", return_value=session):
        _per_user._probe_key(VALID_KEY)
    assert session.get.call_args.kwargs["timeout"] == (7.0, 7.0)


def test_probe_applies_tls_and_proxy_config(monkeypatch):
    config = {
        "verify": "/ca.pem",
        "cert": ("c.pem", "k.pem"),
        "trust_env": False,
        "proxies": {"https": "http://proxy:3128"},
    }
    monkeypatch.setattr(_client, "_build_requests_config", lambda: dict(config))
    session = _fake_session(200)
    with patch.object(_per_user.requests, "Session", return_value=session):
        _per_user._probe_key(VALID_KEY)
    assert session.verify == "/ca.pem"
    assert session.cert == ("c.pem", "k.pem")
    assert session.trust_env is False
    assert session.proxies == {"https": "http://proxy:3128"}


def test_probe_strips_trailing_slash_from_url(monkeypatch):
    monkeypatch.setattr(_client, "REDMINE_URL", "https://redmine.example.com/sub/")
    monkeypatch.setattr(_client, "_build_requests_config", lambda: {})
    session = _fake_session(200)
    with patch.object(_per_user.requests, "Session", return_value=session):
        _per_user._probe_key(VALID_KEY)
    assert (
        session.get.call_args.args[0]
        == "https://redmine.example.com/sub/users/current.json"
    )


# --- the key never leaks -----------------------------------------------------


@pytest.mark.parametrize("status", [200, 401, 403, 500])
def test_key_never_logged_at_debug(caplog, status):
    with caplog.at_level(logging.DEBUG):
        with _probe_returning(status):
            try:
                validate_key_with_redmine(VALID_KEY)
            except PerUserAuthError:
                pass
    assert caplog.records, "expected at least one log line"
    for record in caplog.records:
        assert VALID_KEY not in record.getMessage()


def test_key_never_logged_on_transport_error(caplog):
    err = requests.ConnectionError(f"failed with header {VALID_KEY}")
    with caplog.at_level(logging.DEBUG):
        with patch.object(_per_user, "_probe_key", side_effect=err):
            validate_key_with_redmine(VALID_KEY)
    assert caplog.records
    for record in caplog.records:
        assert VALID_KEY not in record.getMessage()
        assert record.exc_info is None


@pytest.mark.parametrize(
    "bad",
    [VALID_KEY + "\r\nX-Evil: 1", VALID_KEY + "\n", "k" * 30 + " " + "k" * 10],
)
def test_header_unsafe_keys_never_reach_the_probe(bad):
    """requests/httpx echo an invalid header value in their exception text;
    the format check must stop such keys before any HTTP call is made."""
    from redmine_mcp_server._per_user import resolve_per_user_key

    req = MagicMock()
    req.headers = {"X-Redmine-API-Key": bad}
    with patch.object(_per_user, "_probe_key") as probe:
        with pytest.raises(PerUserAuthError) as exc:
            resolve_per_user_key(req)
    probe.assert_not_called()
    assert bad not in exc.value.message


# --- wiring into the client factory -----------------------------------------


def _patched_factory(mode, req):
    return (
        patch.object(_client, "REDMINE_AUTH_MODE", mode),
        patch.object(_client, "redmine", None),
        patch.object(_client, "_legacy_client", MagicMock()),
        patch.object(_client, "Redmine"),
        patch.object(_client, "_build_requests_config", return_value={}),
        patch.object(_client, "get_access_token", return_value=None),
        patch("redmine_mcp_server._client.get_http_request", return_value=req),
    )


def test_client_factory_rejects_unknown_key_in_per_user_mode():
    req = MagicMock()
    req.headers = {"X-Redmine-API-Key": VALID_KEY}
    patches = _patched_factory("legacy-per-user", req)
    with patches[0], patches[1], patches[2], patches[3] as mock_redmine:
        with patches[4], patches[5], patches[6], _probe_returning(401):
            with pytest.raises(PerUserAuthError):
                _client._get_redmine_client()
    mock_redmine.assert_not_called()


def test_client_factory_builds_client_for_accepted_key():
    req = MagicMock()
    req.headers = {"X-Redmine-API-Key": VALID_KEY}
    patches = _patched_factory("legacy-per-user", req)
    with patches[0], patches[1], patches[2], patches[3] as mock_redmine:
        with patches[4], patches[5], patches[6], _probe_returning(200) as probe:
            _client._get_redmine_client()
    probe.assert_called_once_with(VALID_KEY)
    assert mock_redmine.call_args.kwargs["key"] == VALID_KEY


@pytest.mark.parametrize("mode", ["legacy", "oauth", "oauth-proxy"])
def test_other_auth_modes_never_validate(mode):
    req = MagicMock()
    req.headers = {"X-Redmine-API-Key": VALID_KEY}
    patches = _patched_factory(mode, req)
    with patches[0], patches[1], patches[2], patches[3]:
        with patches[4], patches[5], patches[6], _probe_returning(401) as probe:
            _client._get_redmine_client()
    probe.assert_not_called()


def test_oauth_bearer_request_never_validates():
    token = MagicMock()
    token.token = "bearer-token"
    req = MagicMock()
    req.headers = {"X-Redmine-API-Key": VALID_KEY}
    patches = _patched_factory("oauth", req)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[6]:
        with patch.object(_client, "get_access_token", return_value=token):
            with _probe_returning(401) as probe:
                _client._get_redmine_client()
    probe.assert_not_called()
