"""Unit tests for the shared upload content-resolution layer."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server._env import _get_upload_file_roots  # noqa: E402


def test_upload_roots_defaults_to_attachments_dir(tmp_path, monkeypatch):
    att = tmp_path / "attach"
    att.mkdir()
    monkeypatch.setenv("ATTACHMENTS_DIR", str(att))
    monkeypatch.delenv("REDMINE_MCP_UPLOAD_FILE_ROOTS", raising=False)
    roots = _get_upload_file_roots()
    assert roots == [os.path.realpath(str(att))]


def test_upload_roots_appends_extra_roots(tmp_path, monkeypatch):
    att = tmp_path / "attach"
    extra = tmp_path / "extra"
    att.mkdir()
    extra.mkdir()
    monkeypatch.setenv("ATTACHMENTS_DIR", str(att))
    monkeypatch.setenv("REDMINE_MCP_UPLOAD_FILE_ROOTS", str(extra))
    roots = _get_upload_file_roots()
    assert os.path.realpath(str(att)) in roots
    assert os.path.realpath(str(extra)) in roots


def test_upload_roots_skips_blank_entries(tmp_path, monkeypatch):
    att = tmp_path / "a"
    extra = tmp_path / "b"
    att.mkdir()
    extra.mkdir()
    monkeypatch.setenv("ATTACHMENTS_DIR", str(att))
    sep = os.pathsep
    monkeypatch.setenv("REDMINE_MCP_UPLOAD_FILE_ROOTS", f"{sep}{extra}{sep}{sep}")
    roots = _get_upload_file_roots()
    assert roots.count(os.path.realpath(str(extra))) == 1
    assert "" not in roots
