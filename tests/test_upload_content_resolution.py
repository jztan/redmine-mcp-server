"""Unit tests for the shared upload content-resolution layer."""

import os
import sys

import pytest

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


from redmine_mcp_server.tools.files import _resolve_local_file  # noqa: E402


def _allow(monkeypatch, root):
    monkeypatch.setenv("ATTACHMENTS_DIR", str(root))
    monkeypatch.delenv("REDMINE_MCP_UPLOAD_FILE_ROOTS", raising=False)


def test_resolve_local_file_accepts_file_in_root(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"PDF-bytes")
    content, name, err = _resolve_local_file(str(f))
    assert err is None
    assert content == b"PDF-bytes"
    assert name == "doc.pdf"


def test_resolve_local_file_rejects_outside_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    _allow(monkeypatch, root)
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"nope")
    content, name, err = _resolve_local_file(str(outside))
    assert err is not None
    assert "REDMINE_MCP_UPLOAD_FILE_ROOTS" in err["error"]


def test_resolve_local_file_rejects_traversal(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.txt").write_bytes(b"nope")
    _allow(monkeypatch, root)
    content, name, err = _resolve_local_file(str(root / ".." / "secret.txt"))
    assert err is not None


def test_resolve_local_file_rejects_sibling_prefix(tmp_path, monkeypatch):
    root = tmp_path / "attachments"
    sibling = tmp_path / "attachments-evil"
    root.mkdir()
    sibling.mkdir()
    _allow(monkeypatch, root)
    evil = sibling / "x.txt"
    evil.write_bytes(b"x")
    content, name, err = _resolve_local_file(str(evil))
    assert err is not None


def test_resolve_local_file_rejects_symlink_escape(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "outside.txt"
    target.write_bytes(b"secret")
    link = root / "link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    _allow(monkeypatch, root)
    content, name, err = _resolve_local_file(str(link))
    assert err is not None


def test_resolve_local_file_rejects_directory(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    d = tmp_path / "sub"
    d.mkdir()
    content, name, err = _resolve_local_file(str(d))
    assert err is not None


def test_resolve_local_file_rejects_missing(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    content, name, err = _resolve_local_file(str(tmp_path / "ghost.txt"))
    assert err is not None


def test_resolve_local_file_rejects_empty(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")
    content, name, err = _resolve_local_file(str(f))
    assert err is not None
