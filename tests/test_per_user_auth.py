"""Unit tests for the legacy-per-user auth mode (_per_user)."""

import logging

import pytest

from redmine_mcp_server import _per_user
from redmine_mcp_server._per_user import (
    PerUserAuthError,
    resolve_per_user_key,
)

VALID_KEY = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"  # 40 hex chars


class FakeRequest:
    """Minimal stand-in for a Starlette request."""

    def __init__(self, headers=None, scope=None):
        self.headers = headers if headers is not None else {}
        if scope is not None:
            self.scope = scope


def test_resolve_returns_key_when_valid_and_no_forwarded_proto():
    req = FakeRequest(headers={"X-Redmine-API-Key": VALID_KEY})
    assert resolve_per_user_key(req) == VALID_KEY


def test_resolve_missing_header_raises():
    with pytest.raises(PerUserAuthError) as exc:
        resolve_per_user_key(FakeRequest(headers={}))
    assert "missing" in exc.value.message.lower()


def test_resolve_none_request_raises():
    with pytest.raises(PerUserAuthError):
        resolve_per_user_key(None)


def test_resolve_malformed_key_raises():
    for bad in ["", "short", "has spaces inside here now", "bad/chars!" * 3]:
        with pytest.raises(PerUserAuthError) as exc:
            resolve_per_user_key(FakeRequest(headers={"X-Redmine-API-Key": bad}))
        assert "malformed" in exc.value.message.lower()


def test_resolve_rejects_forwarded_proto_http():
    req = FakeRequest(
        headers={"X-Redmine-API-Key": VALID_KEY, "X-Forwarded-Proto": "http"}
    )
    with pytest.raises(PerUserAuthError) as exc:
        resolve_per_user_key(req)
    assert "transport" in exc.value.message.lower()


def test_resolve_accepts_forwarded_proto_https():
    req = FakeRequest(
        headers={"X-Redmine-API-Key": VALID_KEY, "X-Forwarded-Proto": "https"}
    )
    assert resolve_per_user_key(req) == VALID_KEY


def test_extract_key_lowercase_header():
    req = FakeRequest(headers={"x-redmine-api-key": VALID_KEY})
    assert _per_user._extract_key(req) == VALID_KEY


def test_extract_key_asgi_scope_fallback():
    # headers has no usable .get; key only present in raw byte scope
    req = FakeRequest(
        headers=object(),  # no .get -> forces scope fallback
        scope={"headers": [(b"x-redmine-api-key", VALID_KEY.encode())]},
    )
    assert _per_user._extract_key(req) == VALID_KEY


def test_fingerprint_redacts_key():
    fp = _per_user._fingerprint(VALID_KEY)
    assert VALID_KEY not in fp
    assert fp.endswith(VALID_KEY[-4:])


def test_resolve_logs_fingerprint_not_key(caplog):
    req = FakeRequest(headers={"X-Redmine-API-Key": VALID_KEY})
    with caplog.at_level(logging.INFO, logger="redmine_mcp_server"):
        resolve_per_user_key(req)
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert VALID_KEY not in joined
    assert VALID_KEY[-4:] in joined


def test_startup_gate_raises_without_attestation(monkeypatch):
    monkeypatch.delenv("REDMINE_PER_USER_TRUST_PROXY", raising=False)
    with pytest.raises(RuntimeError) as exc:
        _per_user.assert_startup_attestation()
    assert "REDMINE_PER_USER_TRUST_PROXY" in str(exc.value)


def test_startup_gate_passes_with_attestation_and_warns(monkeypatch, caplog):
    monkeypatch.setenv("REDMINE_PER_USER_TRUST_PROXY", "true")
    with caplog.at_level(logging.WARNING, logger="redmine_mcp_server"):
        _per_user.assert_startup_attestation()  # must not raise
    joined = " ".join(r.getMessage() for r in caplog.records).lower()
    assert "tls" in joined
