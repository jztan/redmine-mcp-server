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


import base64 as _b64  # noqa: E402

from redmine_mcp_server.tools.files import _resolve_upload_content  # noqa: E402


@pytest.mark.asyncio
async def test_resolve_content_base64_requires_filename():
    b64 = _b64.b64encode(b"data").decode("ascii")
    content, name, err = await _resolve_upload_content(
        filename=None, content_base64=b64, source_url=None, file_path=None
    )
    assert err is not None
    assert "filename" in err["error"]


@pytest.mark.asyncio
async def test_resolve_content_base64_ok():
    b64 = _b64.b64encode(b"data").decode("ascii")
    content, name, err = await _resolve_upload_content(
        filename="d.bin", content_base64=b64, source_url=None, file_path=None
    )
    assert err is None
    assert content == b"data"
    assert name == "d.bin"


@pytest.mark.asyncio
async def test_resolve_requires_exactly_one_source():
    b64 = _b64.b64encode(b"data").decode("ascii")
    _, _, none_err = await _resolve_upload_content(
        filename="d.bin", content_base64=None, source_url=None, file_path=None
    )
    assert none_err is not None
    _, _, both_err = await _resolve_upload_content(
        filename="d.bin", content_base64=b64, source_url="http://x", file_path=None
    )
    assert both_err is not None


@pytest.mark.asyncio
async def test_resolve_file_path_derives_basename(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    f = tmp_path / "report.csv"
    f.write_bytes(b"a,b")
    content, name, err = await _resolve_upload_content(
        filename=None, content_base64=None, source_url=None, file_path=str(f)
    )
    assert err is None
    assert content == b"a,b"
    assert name == "report.csv"


@pytest.mark.asyncio
async def test_resolve_source_url_uses_inferred_filename(monkeypatch):
    async def fake_download(url):
        return b"web-bytes", "inferred.png", None

    monkeypatch.setattr(
        "redmine_mcp_server.tools.files._download_file_url", fake_download
    )
    content, name, err = await _resolve_upload_content(
        filename=None, content_base64=None, source_url="http://x/y", file_path=None
    )
    assert err is None
    assert content == b"web-bytes"
    assert name == "inferred.png"
