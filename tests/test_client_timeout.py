"""Tests for the Redmine request timeout (issue #214).

redminelib never passes a timeout to requests, so before this change a Redmine
that accepted a connection and never answered hung the call forever. These
tests lock in that every client carries a timeout and that the resulting
errors are distinguishable.
"""

from redmine_mcp_server._env import get_redmine_timeout


class TestGetRedmineTimeout:
    def test_default_is_10_connect_30_read(self, monkeypatch):
        monkeypatch.delenv("REDMINE_TIMEOUT", raising=False)
        assert get_redmine_timeout() == (10.0, 30.0)

    def test_connect_never_exceeds_read(self, monkeypatch):
        monkeypatch.setenv("REDMINE_TIMEOUT", "5")
        assert get_redmine_timeout() == (5.0, 5.0)

    def test_large_value_keeps_connect_at_10(self, monkeypatch):
        monkeypatch.setenv("REDMINE_TIMEOUT", "300")
        assert get_redmine_timeout() == (10.0, 300.0)

    def test_zero_disables(self, monkeypatch):
        monkeypatch.setenv("REDMINE_TIMEOUT", "0")
        assert get_redmine_timeout() is None

    def test_negative_disables(self, monkeypatch):
        monkeypatch.setenv("REDMINE_TIMEOUT", "-1")
        assert get_redmine_timeout() is None

    def test_garbage_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("REDMINE_TIMEOUT", "soon")
        assert get_redmine_timeout() == (10.0, 30.0)
