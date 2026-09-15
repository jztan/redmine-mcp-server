"""Expired OAuth state is deleted from disk, not just hidden (#289).

``FileTreeStore`` stops serving a record once its TTL passes but never deletes
the file, and in ``oauth-proxy`` and ``api-key-login`` modes unauthenticated
endpoints write those files. The cleanup task sweeps them. Every record here
is written through the real encrypted store each mode builds, so a change in
the on-disk format upstream fails these tests instead of silently disabling
the sweep.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import settings

from redmine_mcp_server import _cleanup
from redmine_mcp_server._cleanup import sweep_expired_auth_state

LATER = datetime.now(timezone.utc) + timedelta(hours=1)


def _record_files(home: Path) -> set[str]:
    return {
        str(p.relative_to(home))
        for p in home.rglob("*.json")
        if not p.name.endswith("-info.json")
    }


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "home", tmp_path)
    return tmp_path


@pytest.fixture
def api_key_login_store(home):
    from redmine_mcp_server._api_key_login import build_store

    return build_store("sweep-test-signing-key")


@pytest.fixture
def oauth_proxy_store(home, monkeypatch):
    from redmine_mcp_server._oauth_proxy import build_oauth_proxy

    monkeypatch.setenv("REDMINE_URL", "https://redmine.example")
    monkeypatch.setenv("REDMINE_MCP_BASE_URL", "https://mcp.example")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "introspect-client")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "introspect-secret")
    monkeypatch.setenv("REDMINE_MCP_JWT_SIGNING_KEY", "sweep-test-signing-key")
    return build_oauth_proxy()._client_storage


@pytest.mark.unit
class TestSweepExpiredAuthState:
    async def test_deletes_an_expired_api_key_login_record(
        self, home, api_key_login_store
    ):
        await api_key_login_store.put(
            key="txn", value={"a": 1}, collection="transactions", ttl=60
        )
        assert _record_files(home)

        assert sweep_expired_auth_state(home, now=LATER) == 1

        assert _record_files(home) == set()

    async def test_deletes_an_expired_oauth_proxy_record(self, home, oauth_proxy_store):
        await oauth_proxy_store.put(
            key="txn", value={"a": 1}, collection="mcp-oauth-transactions", ttl=60
        )
        assert _record_files(home)

        assert sweep_expired_auth_state(home, now=LATER) == 1

        assert _record_files(home) == set()

    async def test_keeps_a_record_that_has_not_expired(self, home, api_key_login_store):
        await api_key_login_store.put(
            key="binding", value={"a": 1}, collection="bindings", ttl=7200
        )
        before = _record_files(home)

        assert sweep_expired_auth_state(home, now=LATER) == 0

        assert _record_files(home) == before
        assert await api_key_login_store.get(key="binding", collection="bindings")

    async def test_keeps_a_record_without_a_ttl(self, home, oauth_proxy_store):
        # OAuthProxy stores client registrations with no TTL at all.
        await oauth_proxy_store.put(
            key="client", value={"a": 1}, collection="mcp-oauth-proxy-clients"
        )
        before = _record_files(home)

        assert sweep_expired_auth_state(home, now=LATER) == 0

        assert _record_files(home) == before

    async def test_keeps_the_store_metadata_and_directories(
        self, home, api_key_login_store
    ):
        await api_key_login_store.put(
            key="txn", value={"a": 1}, collection="transactions", ttl=60
        )
        metadata = sorted(home.rglob("*-info.json"))
        directories = sorted(p for p in home.rglob("*") if p.is_dir())

        sweep_expired_auth_state(home, now=LATER)

        assert sorted(home.rglob("*-info.json")) == metadata
        assert sorted(p for p in home.rglob("*") if p.is_dir()) == directories
        # The store still works after its collection was emptied.
        await api_key_login_store.put(
            key="txn2", value={"a": 2}, collection="transactions", ttl=60
        )
        assert await api_key_login_store.get(key="txn2", collection="transactions")

    async def test_keeps_a_record_rewritten_while_the_sweep_read_it(
        self, home, api_key_login_store, monkeypatch
    ):
        # The sweep reads an expired record, then a writer renames a fresh one
        # over it before the unlink. The fresh one must survive.
        await api_key_login_store.put(
            key="txn", value={"a": 1}, collection="transactions", ttl=60
        )
        (path,) = (home / "api-key-login").glob("*/transactions/*.json")
        fresh = path.read_text().replace('"expires_at": "', '"expires_at": "9')
        real_load = _cleanup.json.load

        def load_then_rewrite(handle):
            record = real_load(handle)
            replacement = path.with_suffix(".new")
            replacement.write_text(fresh)
            os.replace(replacement, path)
            return record

        monkeypatch.setattr(_cleanup.json, "load", load_then_rewrite)

        assert sweep_expired_auth_state(home, now=LATER) == 0

        assert path.read_text() == fresh

    def test_keeps_files_it_cannot_read_as_a_record(self, home):
        collection = home / "api-key-login" / "abc123" / "transactions"
        collection.mkdir(parents=True)
        (collection / "garbled.json").write_text("{not json")
        (collection / "list.json").write_text("[1, 2]")
        (collection / "bad-date.json").write_text('{"expires_at": "yesterday"}')
        (collection / "half-written.tmp").write_text(
            '{"expires_at": "2000-01-01T00:00:00+00:00"}'
        )

        assert sweep_expired_auth_state(home, now=LATER) == 0

        assert len(list(collection.iterdir())) == 4

    def test_leaves_other_directories_under_the_home_alone(self, home):
        elsewhere = home / "something-else" / "abc123" / "collection"
        elsewhere.mkdir(parents=True)
        stray = elsewhere / "record.json"
        stray.write_text('{"expires_at": "2000-01-01T00:00:00+00:00"}')

        assert sweep_expired_auth_state(home, now=LATER) == 0

        assert stray.exists()

    def test_a_home_without_any_store_is_a_no_op(self, tmp_path):
        assert sweep_expired_auth_state(tmp_path / "missing", now=LATER) == 0


@pytest.mark.unit
class TestCleanupTaskSweepsAuthState:
    @pytest.mark.parametrize("mode", ["oauth-proxy", "api-key-login"])
    async def test_runs_in_the_stateful_modes_without_attachment_cleanup(self, mode):
        manager = _cleanup.CleanupTaskManager()
        env = {"AUTO_CLEANUP_ENABLED": "false", "REDMINE_AUTH_MODE": mode}
        with patch.dict(os.environ, env):
            await manager.start()
        try:
            assert manager.task is not None
            assert manager.manager is None
            assert manager.sweep_auth_state is True
        finally:
            await manager.stop()

    @pytest.mark.parametrize("mode", ["legacy", "legacy-per-user", "oauth"])
    async def test_stays_off_in_the_other_modes(self, mode):
        manager = _cleanup.CleanupTaskManager()
        env = {"AUTO_CLEANUP_ENABLED": "false", "REDMINE_AUTH_MODE": mode}
        with patch.dict(os.environ, env):
            await manager.start()

        assert manager.task is None
        assert manager.sweep_auth_state is False

    async def test_one_pass_deletes_expired_state(
        self, home, api_key_login_store, monkeypatch
    ):
        await api_key_login_store.put(
            key="txn", value={"a": 1}, collection="transactions", ttl=60
        )
        manager = _cleanup.CleanupTaskManager()
        manager.sweep_auth_state = True
        monkeypatch.setattr(_cleanup, "_utcnow", lambda: LATER, raising=True)

        await manager._run_once()

        assert _record_files(home) == set()

    async def test_status_reports_the_sweep(self):
        manager = _cleanup.CleanupTaskManager()
        manager.sweep_auth_state = True

        assert manager.get_status()["auth_state_sweep"] is True

    @pytest.mark.parametrize("mode", ["oauth-proxy", "api-key-login"])
    async def test_lazy_start_fires_in_the_stateful_modes(self, mode):
        original = _cleanup._cleanup_initialized
        _cleanup._cleanup_initialized = False
        try:
            env = {"AUTO_CLEANUP_ENABLED": "false", "REDMINE_AUTH_MODE": mode}
            with (
                patch.dict(os.environ, env),
                patch.object(
                    _cleanup.cleanup_manager, "start", new_callable=AsyncMock
                ) as start,
            ):
                await _cleanup._ensure_cleanup_started()

            start.assert_called_once()
        finally:
            _cleanup._cleanup_initialized = original

    async def test_authenticated_app_starts_the_task_with_the_server(
        self, oauth_proxy_store, monkeypatch
    ):
        # The endpoints that write this state are unauthenticated, so the
        # sweep cannot wait for a tool call or a health check to start it.
        from fastmcp import FastMCP

        from redmine_mcp_server._oauth_proxy import build_oauth_proxy
        from redmine_mcp_server.main import build_authenticated_app

        auth = build_oauth_proxy()
        app = build_authenticated_app(FastMCP("sweep_test", auth=auth), auth)

        with patch.object(
            _cleanup, "_ensure_cleanup_started", new_callable=AsyncMock
        ) as ensure:
            async with app.router.lifespan_context(app):
                ensure.assert_called_once()
