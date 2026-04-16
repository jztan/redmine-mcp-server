"""Unit tests for Stage B project file tools.

Covers:
    - list_files
    - upload_file
    - delete_file
    - _file_to_dict helper
"""

import base64
import os
import sys

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    _file_to_dict,
    delete_file,
    list_files,
    upload_file,
)


def _make_streaming_response(status_code=200, body=b"hello", headers=None):
    """Build a MagicMock that emulates httpx.AsyncClient().stream() as an
    async context manager yielding a response with `aiter_bytes`."""

    async def aiter_bytes():
        yield body

    response = MagicMock()
    response.status_code = status_code
    response.reason_phrase = "OK" if status_code < 400 else "Error"
    response.headers = headers or {}
    response.aiter_bytes = aiter_bytes

    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=response)
    stream_cm.__aexit__ = AsyncMock(return_value=None)
    return stream_cm


def _patch_httpx_stream(stream_cm):
    """Patch httpx.AsyncClient to yield our mocked stream context manager."""
    client = MagicMock()
    client.stream = MagicMock(return_value=stream_cm)
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=client)
    client_cm.__aexit__ = AsyncMock(return_value=None)
    return patch("httpx.AsyncClient", return_value=client_cm)


def _mock_with_name(id_val, name_val):
    m = Mock()
    m.id = id_val
    m.name = name_val
    return m


def _mock_file(
    file_id=1,
    filename="test.pdf",
    filesize=1024,
    content_type="application/pdf",
    description="",
    author_id=5,
    author_name="Alice",
    with_version=False,
):
    f = Mock()
    f.id = file_id
    f.filename = filename
    f.filesize = filesize
    f.content_type = content_type
    f.description = description
    f.content_url = f"https://example.com/attachments/{file_id}/{filename}"
    f.digest = "abc123"
    f.downloads = 0
    f.author = _mock_with_name(author_id, author_name)
    f.version = _mock_with_name(3, "Release 1.0") if with_version else None
    f.created_on = None
    return f


# ---------------------------------------------------------------------------
# _file_to_dict helper
# ---------------------------------------------------------------------------


class TestFileToDict:
    def test_full_file(self):
        f = _mock_file(
            file_id=42,
            filename="spec.pdf",
            filesize=125678,
            content_type="application/pdf",
            description="Design spec",
            with_version=True,
        )
        result = _file_to_dict(f)
        assert result["id"] == 42
        # filename and description are wrapped in <insecure-content> to
        # neutralise prompt-injection payloads embedded by uploaders.
        assert "spec.pdf" in result["filename"]
        assert result["filename"].startswith("<insecure-content-")
        assert result["filesize"] == 125678
        assert result["content_type"] == "application/pdf"
        assert "Design spec" in result["description"]
        assert result["description"].startswith("<insecure-content-")
        # author.name and version.name are also wrapped (display names
        # are user-controlled).
        assert result["author"]["id"] == 5
        assert "Alice" in result["author"]["name"]
        assert result["version"]["id"] == 3
        assert "Release 1.0" in result["version"]["name"]

    def test_no_version(self):
        f = _mock_file(with_version=False)
        result = _file_to_dict(f)
        assert result["version"] is None

    def test_no_author(self):
        f = _mock_file()
        f.author = None
        result = _file_to_dict(f)
        assert result["author"] is None

    def test_missing_attributes(self):
        f = Mock(spec=["id"])
        f.id = 1
        result = _file_to_dict(f)
        assert result["id"] == 1
        assert result["filename"] == ""
        assert result["filesize"] == 0
        assert result["author"] is None


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------


class TestListFiles:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_returns_files(self, mock_redmine):
        f1 = _mock_file(file_id=1, filename="a.pdf")
        f2 = _mock_file(file_id=2, filename="b.png", content_type="image/png")
        mock_redmine.file.filter.return_value = [f1, f2]

        result = await list_files(project_id="web")

        assert len(result) == 2
        # Filenames are wrapped in <insecure-content> — assert substring match.
        assert "a.pdf" in result[0]["filename"]
        assert "b.png" in result[1]["filename"]
        mock_redmine.file.filter.assert_called_once_with(project_id="web")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_empty(self, mock_redmine):
        mock_redmine.file.filter.return_value = []
        result = await list_files(project_id=10)
        assert result == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_by_numeric_id(self, mock_redmine):
        mock_redmine.file.filter.return_value = []
        await list_files(project_id=5)
        mock_redmine.file.filter.assert_called_once_with(project_id=5)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_project_not_found(self, mock_redmine):
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.file.filter.side_effect = ResourceNotFoundError()
        result = await list_files(project_id=9999)
        assert isinstance(result, dict)
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_forbidden(self, mock_redmine):
        from redminelib.exceptions import ForbiddenError

        mock_redmine.file.filter.side_effect = ForbiddenError()
        result = await list_files(project_id=10)
        assert isinstance(result, dict)
        assert "error" in result
        assert "Access denied" in result["error"]


# ---------------------------------------------------------------------------
# upload_file
# ---------------------------------------------------------------------------


class TestUploadFile:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_upload_basic(self, mock_redmine):
        content = b"Hello, world!"
        b64 = base64.b64encode(content).decode("ascii")

        mock_redmine.upload.return_value = {"token": "tok123.abc"}
        # python-redmine's FileManager synthesizes a minimal response with
        # only the id (since Redmine returns HTTP 204 on create).
        minimal_upload = Mock(spec=["id"])
        minimal_upload.id = 100
        mock_redmine.file.create.return_value = minimal_upload
        # The tool re-fetches the full metadata via attachment.get().
        mock_redmine.attachment.get.return_value = _mock_file(
            file_id=100, filename="hello.txt"
        )

        result = await upload_file(
            project_id="web",
            filename="hello.txt",
            content_base64=b64,
        )

        # Full metadata should be returned, not just {"id": 100, ...blanks}.
        assert result["id"] == 100
        # Filename is wrapped in <insecure-content> boundary tags.
        assert "hello.txt" in result["filename"]
        assert result["filesize"] == 1024
        assert result["author"]["id"] == 5
        assert "Alice" in result["author"]["name"]

        # Verify upload was called with a BytesIO containing the decoded bytes
        mock_redmine.upload.assert_called_once()
        upload_args = mock_redmine.upload.call_args
        stream = upload_args.args[0]
        assert stream.getvalue() == content
        assert upload_args.kwargs == {"filename": "hello.txt"}

        # Verify file.create was called with token
        mock_redmine.file.create.assert_called_once_with(
            project_id="web",
            token="tok123.abc",
            filename="hello.txt",
        )

        # Verify the enrichment re-fetch happened
        mock_redmine.attachment.get.assert_called_once_with(100)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_upload_with_description_and_version(self, mock_redmine):
        b64 = base64.b64encode(b"x").decode("ascii")

        mock_redmine.upload.return_value = {"token": "tok"}
        minimal = Mock(spec=["id"])
        minimal.id = 7
        mock_redmine.file.create.return_value = minimal
        mock_redmine.attachment.get.return_value = _mock_file(file_id=7)

        await upload_file(
            project_id=10,
            filename="doc.txt",
            content_base64=b64,
            description="Release notes",
            version_id=3,
        )

        _, kwargs = mock_redmine.file.create.call_args
        assert kwargs["description"] == "Release notes"
        assert kwargs["version_id"] == 3

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_upload_falls_back_when_refetch_fails(self, mock_redmine):
        """If attachment.get() fails after upload, we return the minimal
        response enriched with the filename and description we know."""
        from redminelib.exceptions import ResourceNotFoundError

        b64 = base64.b64encode(b"x").decode("ascii")
        mock_redmine.upload.return_value = {"token": "tok"}
        minimal = Mock(spec=["id"])
        minimal.id = 55
        mock_redmine.file.create.return_value = minimal
        mock_redmine.attachment.get.side_effect = ResourceNotFoundError()

        result = await upload_file(
            project_id=10,
            filename="fallback.txt",
            content_base64=b64,
            description="Fallback test",
        )

        # Upload itself succeeded — caller still gets a useful response
        assert "error" not in result
        assert result["id"] == 55
        assert result["filename"] == "fallback.txt"
        assert result["description"] == "Fallback test"

    @pytest.mark.asyncio
    async def test_missing_filename(self):
        b64 = base64.b64encode(b"x").decode("ascii")
        result = await upload_file(project_id=10, filename="", content_base64=b64)
        assert "error" in result
        assert "filename" in result["error"]

    @pytest.mark.asyncio
    async def test_whitespace_only_filename(self):
        b64 = base64.b64encode(b"x").decode("ascii")
        result = await upload_file(project_id=10, filename="   ", content_base64=b64)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_content(self):
        result = await upload_file(
            project_id=10, filename="test.txt", content_base64=""
        )
        assert "error" in result
        assert "content_base64" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_both_content_sources(self):
        result = await upload_file(project_id=10, filename="test.txt")
        assert "error" in result
        assert "content_base64 or source_url" in result["error"]

    @pytest.mark.asyncio
    async def test_both_content_sources_provided(self):
        b64 = base64.b64encode(b"x").decode("ascii")
        result = await upload_file(
            project_id=10,
            filename="test.txt",
            content_base64=b64,
            source_url="https://example.com/file",
        )
        assert "error" in result
        assert "exactly ONE" in result["error"]

    # -- source_url tests --

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_upload_from_url_basic(self, mock_redmine):
        body = b"Hello from URL!"
        stream_cm = _make_streaming_response(status_code=200, body=body)

        mock_redmine.upload.return_value = {"token": "tok-url"}
        minimal = Mock(spec=["id"])
        minimal.id = 200
        mock_redmine.file.create.return_value = minimal
        mock_redmine.attachment.get.return_value = _mock_file(
            file_id=200, filename="hello.txt", filesize=len(body)
        )

        with _patch_httpx_stream(stream_cm):
            result = await upload_file(
                project_id="web",
                source_url="https://example.com/downloads/hello.txt",
                description="From URL",
            )

        assert "error" not in result
        assert result["id"] == 200
        # Filename is wrapped in <insecure-content> boundary tags.
        assert "hello.txt" in result["filename"]

        # Verify the bytes that got uploaded match what we streamed
        stream = mock_redmine.upload.call_args.args[0]
        assert stream.getvalue() == body
        # Filename was inferred from URL path
        assert mock_redmine.upload.call_args.kwargs == {"filename": "hello.txt"}

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_upload_from_url_explicit_filename_wins(self, mock_redmine):
        """Caller-supplied filename overrides the URL-inferred one."""
        stream_cm = _make_streaming_response(body=b"x")
        mock_redmine.upload.return_value = {"token": "tok"}
        minimal = Mock(spec=["id"])
        minimal.id = 201
        mock_redmine.file.create.return_value = minimal
        mock_redmine.attachment.get.return_value = _mock_file(file_id=201)

        with _patch_httpx_stream(stream_cm):
            await upload_file(
                project_id="web",
                source_url="https://example.com/downloads/original.bin",
                filename="renamed.bin",
            )

        assert mock_redmine.upload.call_args.kwargs["filename"] == "renamed.bin"

    @pytest.mark.asyncio
    async def test_upload_from_url_invalid_scheme(self):
        result = await upload_file(
            project_id="web",
            source_url="ftp://example.com/file.txt",
        )
        assert "error" in result
        assert "scheme" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_upload_from_url_http_error(self):
        stream_cm = _make_streaming_response(status_code=404, body=b"")
        with _patch_httpx_stream(stream_cm):
            result = await upload_file(
                project_id="web",
                source_url="https://example.com/missing.pdf",
            )
        assert "error" in result
        assert "404" in result["error"]

    @pytest.mark.asyncio
    async def test_upload_from_url_content_disposition_filename(self):
        """When URL path has no filename, fall back to Content-Disposition."""
        stream_cm = _make_streaming_response(
            body=b"body",
            headers={"content-disposition": 'attachment; filename="server-named.pdf"'},
        )
        with (
            _patch_httpx_stream(stream_cm),
            patch("redmine_mcp_server.redmine_handler.redmine") as mock_redmine,
        ):
            mock_redmine.upload.return_value = {"token": "tok"}
            minimal = Mock(spec=["id"])
            minimal.id = 77
            mock_redmine.file.create.return_value = minimal
            mock_redmine.attachment.get.return_value = _mock_file(file_id=77)

            result = await upload_file(
                project_id="web",
                # Path ends in "/" so urlpath-derived filename will be empty.
                source_url="https://example.com/download/",
            )

        assert "error" not in result
        assert mock_redmine.upload.call_args.kwargs["filename"] == "server-named.pdf"

    @pytest.mark.asyncio
    async def test_upload_from_url_empty_body(self):
        stream_cm = _make_streaming_response(body=b"")
        with _patch_httpx_stream(stream_cm):
            result = await upload_file(
                project_id="web",
                source_url="https://example.com/empty.txt",
            )
        assert "error" in result
        assert "empty" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_upload_from_url_unresolvable_filename(self):
        """URL path has no filename, no Content-Disposition, and caller
        didn't pass filename — we bail out."""
        stream_cm = _make_streaming_response(body=b"x")
        with _patch_httpx_stream(stream_cm):
            result = await upload_file(
                project_id="web",
                source_url="https://example.com/download/",
            )
        assert "error" in result
        assert "filename" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_upload_from_url_timeout(self):
        import httpx

        with patch("httpx.AsyncClient") as mock_client_ctor:
            mock_client_ctor.side_effect = httpx.TimeoutException("slow")
            result = await upload_file(
                project_id="web",
                source_url="https://example.com/slow.bin",
                filename="slow.bin",
            )
        assert "error" in result
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_upload_from_url_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await upload_file(
            project_id="web",
            source_url="https://example.com/file.txt",
        )
        assert "error" in result
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_base64(self):
        result = await upload_file(
            project_id=10,
            filename="test.txt",
            content_base64="not-valid-base64-content!!!",
        )
        assert "error" in result
        assert "base64" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_empty_decoded_content(self):
        # Valid base64 that decodes to empty bytes
        result = await upload_file(
            project_id=10, filename="test.txt", content_base64=""
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_file_too_large(self):
        # 51 MiB of base64-encoded data decodes to ~38 MiB,
        # so we need to construct 51+ MiB of actual decoded bytes
        # ~51 MiB of zeros
        large_content = b"\x00" * (51 * 1024 * 1024)
        b64 = base64.b64encode(large_content).decode("ascii")

        result = await upload_file(
            project_id=10,
            filename="huge.bin",
            content_base64=b64,
        )
        assert "error" in result
        assert "too large" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        b64 = base64.b64encode(b"x").decode("ascii")
        result = await upload_file(
            project_id=10, filename="test.txt", content_base64=b64
        )
        assert "error" in result
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_upload_project_not_found(self, mock_redmine):
        from redminelib.exceptions import ResourceNotFoundError

        b64 = base64.b64encode(b"x").decode("ascii")
        mock_redmine.upload.return_value = {"token": "tok"}
        mock_redmine.file.create.side_effect = ResourceNotFoundError()

        result = await upload_file(
            project_id=9999, filename="test.txt", content_base64=b64
        )
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_upload_forbidden(self, mock_redmine):
        from redminelib.exceptions import ForbiddenError

        b64 = base64.b64encode(b"x").decode("ascii")
        mock_redmine.upload.side_effect = ForbiddenError()

        result = await upload_file(
            project_id=10, filename="test.txt", content_base64=b64
        )
        assert "error" in result
        assert "Access denied" in result["error"]


# ---------------------------------------------------------------------------
# delete_file
# ---------------------------------------------------------------------------


class TestDeleteFile:
    def _mock_project_attachment(self, attachment_id=42):
        """Attachment whose container_type is Project (a real project file)."""
        att = Mock()
        att.id = attachment_id
        att.container_type = "Project"
        return att

    def _mock_issue_attachment(self, attachment_id=42):
        """Attachment whose container_type is Issue (NOT a project file)."""
        att = Mock()
        att.id = attachment_id
        att.container_type = "Issue"
        return att

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_delete_success_project_file(self, mock_redmine):
        mock_redmine.attachment.get.return_value = self._mock_project_attachment(42)
        mock_redmine.attachment.delete.return_value = True

        result = await delete_file(file_id=42)

        assert result == {"success": True, "deleted_file_id": 42}
        mock_redmine.attachment.get.assert_called_once_with(42)
        mock_redmine.attachment.delete.assert_called_once_with(42)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_delete_refuses_issue_attachment(self, mock_redmine):
        """Without the bypass flag, we refuse to delete issue attachments."""
        mock_redmine.attachment.get.return_value = self._mock_issue_attachment(42)

        result = await delete_file(file_id=42)

        assert "error" in result
        assert "Issue" in result["error"]
        assert "confirm_delete_any_attachment" in result["error"]
        mock_redmine.attachment.delete.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_delete_issue_attachment_with_confirm(self, mock_redmine):
        """Explicit bypass skips the scope check and deletes anyway."""
        mock_redmine.attachment.delete.return_value = True

        result = await delete_file(file_id=42, confirm_delete_any_attachment=True)

        assert result == {"success": True, "deleted_file_id": 42}
        # Verification skipped
        mock_redmine.attachment.get.assert_not_called()
        mock_redmine.attachment.delete.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_delete_read_only(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        result = await delete_file(file_id=42)
        assert "error" in result
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_delete_not_found_on_verify(self, mock_redmine):
        """Verification GET returns 404 before we even try to delete."""
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.attachment.get.side_effect = ResourceNotFoundError()
        result = await delete_file(file_id=9999)
        assert "error" in result
        mock_redmine.attachment.delete.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_delete_not_found_on_delete(self, mock_redmine):
        """Verification succeeds, but the attachment vanishes before delete."""
        from redminelib.exceptions import ResourceNotFoundError

        mock_redmine.attachment.get.return_value = self._mock_project_attachment(42)
        mock_redmine.attachment.delete.side_effect = ResourceNotFoundError()
        result = await delete_file(file_id=42)
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_delete_forbidden(self, mock_redmine):
        from redminelib.exceptions import ForbiddenError

        mock_redmine.attachment.get.return_value = self._mock_project_attachment(42)
        mock_redmine.attachment.delete.side_effect = ForbiddenError()
        result = await delete_file(file_id=42)
        assert "error" in result
        assert "Access denied" in result["error"]
