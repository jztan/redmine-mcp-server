"""Unit tests for the DMSF (redmine_dmsf plugin) `manage_document` tool."""

import base64
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server._env import _is_dmsf_enabled  # noqa: E402
from redmine_mcp_server.tools.documents import manage_document  # noqa: E402


def _make_doc(doc_id: int = 1, filename: str = "spec.pdf") -> dict:
    return {
        "id": doc_id,
        "type": "file",
        "filename": filename,
        "title": f"Title {doc_id}",
        "name": filename,
        "description": "A document",
        "version": "1.0",
        "size": 1234,
        "content_type": "application/pdf",
        "folder_id": None,
        "project_id": 5,
        "author": {"id": 7, "name": "Alice"},
        "created_on": "2026-05-01T10:00:00Z",
        "updated_on": "2026-05-02T11:00:00Z",
    }


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


class TestIsDmsfEnabled:
    def test_false_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDMINE_DMSF_ENABLED", None)
            assert _is_dmsf_enabled() is False

    def test_true_when_env_set(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            assert _is_dmsf_enabled() is True


# ---------------------------------------------------------------------------
# Dispatch + feature flag gating
# ---------------------------------------------------------------------------


class TestManageDocumentDispatch:
    @pytest.mark.asyncio
    async def test_disabled_returns_error(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "false"}):
            result = await manage_document(action="list", project_id="proj")
        assert "error" in result
        assert "REDMINE_DMSF_ENABLED" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_action(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="bogus", project_id="proj")
        assert "error" in result
        assert "Invalid action" in result["error"]


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def _dmsf_list_response(*docs: dict, total_count: int = None) -> dict:
    """Build a response in the **real** DMSF list shape, as verified
    against a live `redmine_dmsf` instance:

        {"dmsf": {"dmsf_nodes": [...], "total_count": N}}

    The previous test fixtures used ``{"dmsf": [...]}`` and missed a
    real-world bug where the inner ``dmsf`` value is a *dict*, not a
    list, and our parser silently emptied the result.
    """
    return {
        "dmsf": {
            "dmsf_nodes": list(docs),
            "total_count": total_count if total_count is not None else len(docs),
        }
    }


class TestManageDocumentList:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_list_success(self, mock_redmine):
        mock_redmine.engine.request.return_value = _dmsf_list_response(
            _make_doc(1), _make_doc(2, "design.pdf")
        )
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="list", project_id="proj")

        assert isinstance(result, list)
        assert len(result) == 2
        assert "spec.pdf" in result[0]["filename"]
        # User-controlled field wrapped in insecure-content boundary tags
        assert "<insecure-content-" in result[0]["filename"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_list_regression_real_dmsf_shape(self, mock_redmine):
        """Regression test for the bug where ``payload["dmsf"]`` is a dict
        (the real DMSF shape) but the parser assumed a list and emptied
        the result. Verifies that both documents survive parsing."""
        mock_redmine.engine.request.return_value = {
            "dmsf": {
                "dmsf_nodes": [_make_doc(1, "spec.pdf"), _make_doc(2, "design.pdf")],
                "total_count": 2,
            }
        }
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="list", project_id="web")

        assert isinstance(result, list)
        assert len(result) == 2, (
            "Both documents must be returned. If only 0 are returned, the "
            "parser is silently dropping the real DMSF response shape."
        )
        assert "spec.pdf" in result[0]["filename"]
        assert "design.pdf" in result[1]["filename"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_list_with_folder_filter(self, mock_redmine):
        mock_redmine.engine.request.return_value = _dmsf_list_response()
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            await manage_document(
                action="list", project_id="proj", folder_id=42, limit=25
            )

        call_kwargs = mock_redmine.engine.request.call_args.kwargs
        assert call_kwargs["params"]["folder_id"] == 42
        assert call_kwargs["params"]["limit"] == 25

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_list_handles_bare_array_response(self, mock_redmine):
        """Some DMSF versions may return a bare list at the top level."""
        mock_redmine.engine.request.return_value = [_make_doc(1)]
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="list", project_id="proj")
        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_list_handles_dmsf_value_as_list(self, mock_redmine):
        """Defensive: older plugin builds may put a bare list directly
        under the ``dmsf`` key. Tolerate both shapes."""
        mock_redmine.engine.request.return_value = {"dmsf": [_make_doc(1)]}
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="list", project_id="proj")
        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_clamps_limit_to_100(self, mock_redmine):
        mock_redmine.engine.request.return_value = _dmsf_list_response()
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            await manage_document(action="list", project_id="proj", limit=500)
        call_kwargs = mock_redmine.engine.request.call_args.kwargs
        assert call_kwargs["params"]["limit"] == 100

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_slices_oversized_response(self, mock_redmine):
        many = [_make_doc(i) for i in range(200)]
        mock_redmine.engine.request.return_value = _dmsf_list_response(*many)
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="list", project_id="proj", limit=50)
        assert len(result) == 50

    @pytest.mark.asyncio
    async def test_rejects_missing_project_id(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="list")
        assert "error" in result
        assert "project_id" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_empty_project_id(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="list", project_id="")
        assert "error" in result
        assert "project_id" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_invalid_folder_id(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(
                action="list", project_id="proj", folder_id=-1
            )
        assert "error" in result
        assert "folder_id" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_invalid_limit(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="list", project_id="proj", limit=0)
        assert "error" in result
        assert "limit" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_handles_api_error(self, mock_redmine):
        mock_redmine.engine.request.side_effect = Exception("boom")
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="list", project_id="proj")
        assert "error" in result


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestManageDocumentGet:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_get_success(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"dmsf_file": _make_doc(42)}
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="get", document_id=42)
        assert result["id"] == 42
        assert "spec.pdf" in result["filename"]
        mock_redmine.engine.request.assert_called_once_with(
            "get", "http://localhost:3000/dmsf_files/42.json"
        )

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_get_not_found(self, mock_redmine):
        mock_redmine.engine.request.return_value = {}
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="get", document_id=999)
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_get_handles_nested_dmsf_wrapper(self, mock_redmine):
        """Defensive: tolerate ``{"dmsf": {"dmsf_file": {...}}}`` in case a
        plugin version applies the same outer wrapping to single-resource
        responses that it does to list responses."""
        mock_redmine.engine.request.return_value = {"dmsf": {"dmsf_file": _make_doc(7)}}
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="get", document_id=7)
        assert result["id"] == 7

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_get_handles_document_key_variant(self, mock_redmine):
        """Defensive: tolerate ``{"document": {...}}`` from older builds."""
        mock_redmine.engine.request.return_value = {"document": _make_doc(8)}
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="get", document_id=8)
        assert result["id"] == 8

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_get_real_dmsf_shape_merges_revision(self, mock_redmine):
        """Regression: DMSF's GET /dmsf_files/{id}.json wraps the document
        in ``{"dmsf_file": {...}}`` and nests almost all metadata
        (``description``, ``size``, ``mime_type``, ``user_id``,
        ``created_at``, ``updated_at``) under the latest entry of
        ``dmsf_file_revisions``. The filename is exposed as ``name``,
        not ``filename``.

        Earlier serializer read everything as flat top-level keys and
        silently dropped description, version, size, content_type,
        author, and timestamps. This test asserts that all of those
        fields surface correctly when given the real shape."""
        real_dmsf_response = {
            "dmsf_file": {
                "id": 1,
                "title": "first-file",
                "name": "ai-366-plan.md",
                "project_id": 1,
                "dmsf_file_revisions": [
                    {
                        "id": 1,
                        "version": "0.1",
                        "size": 13005,
                        "description": "File number one!",
                        "mime_type": "text/markdown",
                        "user_id": 1,
                        "created_at": "2026-05-12T10:00:00Z",
                        "updated_at": "2026-05-12T10:05:00Z",
                    }
                ],
            }
        }
        mock_redmine.engine.request.return_value = real_dmsf_response
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="get", document_id=1)

        assert result["id"] == 1
        assert "first-file" in result["title"]
        # Filename surfaces from `name` (DMSF get shape, not `filename`)
        assert "ai-366-plan.md" in result["filename"]
        assert "ai-366-plan.md" in result["name"]
        # Metadata pulled from latest revision
        assert "File number one!" in result["description"]
        assert result["version"] == "0.1"
        assert result["size"] == 13005
        assert result["content_type"] == "text/markdown"
        # Author is reconstructed from user_id when no nested dict is present
        assert result["author"] == {"id": 1, "name": None}
        # Timestamps come from revision's created_at / updated_at
        assert result["created_on"] == "2026-05-12T10:00:00Z"
        assert result["updated_on"] == "2026-05-12T10:05:00Z"
        assert result["project_id"] == 1

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_get_uses_latest_revision_when_multiple(self, mock_redmine):
        """When a document has several revisions, the latest one (last in
        the array per DMSF's ascending order) supplies the current
        metadata."""
        response = {
            "dmsf_file": {
                "id": 5,
                "title": "spec",
                "name": "spec.pdf",
                "project_id": 1,
                "dmsf_file_revisions": [
                    {
                        "id": 1,
                        "version": "0.1",
                        "size": 100,
                        "description": "initial draft",
                        "mime_type": "application/pdf",
                        "user_id": 1,
                        "created_at": "2026-05-10T10:00:00Z",
                        "updated_at": "2026-05-10T10:00:00Z",
                    },
                    {
                        "id": 2,
                        "version": "1.0",
                        "size": 200,
                        "description": "release version",
                        "mime_type": "application/pdf",
                        "user_id": 2,
                        "created_at": "2026-05-12T10:00:00Z",
                        "updated_at": "2026-05-12T10:00:00Z",
                    },
                ],
            }
        }
        mock_redmine.engine.request.return_value = response
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="get", document_id=5)

        assert result["version"] == "1.0"
        assert result["size"] == 200
        assert "release version" in result["description"]
        assert result["author"]["id"] == 2

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_get_no_revisions_field_still_works(self, mock_redmine):
        """If a response somehow has no ``dmsf_file_revisions`` (e.g.,
        the mock fixture in existing tests), the serializer must still
        return the top-level fields without crashing."""
        mock_redmine.engine.request.return_value = {"dmsf_file": _make_doc(99)}
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="get", document_id=99)
        assert result["id"] == 99
        # Top-level fields from the flat fixture still surface
        assert "spec.pdf" in result["filename"]

    @pytest.mark.asyncio
    async def test_rejects_invalid_document_id(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="get", document_id=-1)
        assert "error" in result
        assert "document_id" in result["error"]


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def _b64(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


class TestManageDocumentCreate:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_create_success(self, mock_redmine):
        # Step 1 (client.upload) returns {"token": ...}; Step 2 returns dmsf_file
        mock_redmine.upload.return_value = {"token": "tok-abc"}
        mock_redmine.engine.request.return_value = {"dmsf_file": _make_doc(99)}

        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(
                action="create",
                project_id="proj",
                filename="spec.pdf",
                content_base64=_b64(b"%PDF-fake-content"),
                title="Spec",
                description="The spec",
            )

        assert result["id"] == 99
        # Step 1: upload called
        assert mock_redmine.upload.called
        # Step 2: POST to dmsf/commit_files.json with token + filename
        call_args = mock_redmine.engine.request.call_args
        assert call_args.args[0] == "post"
        assert call_args.args[1].endswith("/projects/proj/dmsf/commit_files.json")
        body = json.loads(call_args.kwargs["data"])
        assert body["dmsf_file"]["token"] == "tok-abc"
        assert body["dmsf_file"]["filename"] == "spec.pdf"
        assert body["dmsf_file"]["title"] == "Spec"
        assert body["dmsf_file"]["description"] == "The spec"

    @pytest.mark.asyncio
    async def test_blocked_in_read_only_mode(self):
        with patch.dict(
            os.environ,
            {"REDMINE_MCP_READ_ONLY": "true", "REDMINE_DMSF_ENABLED": "true"},
        ):
            result = await manage_document(
                action="create",
                project_id="proj",
                filename="f.txt",
                content_base64=_b64(b"x"),
            )
        assert "error" in result
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_missing_filename(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(
                action="create",
                project_id="proj",
                content_base64=_b64(b"x"),
            )
        assert "error" in result
        assert "filename" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_missing_content(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(
                action="create",
                project_id="proj",
                filename="f.txt",
            )
        assert "error" in result
        assert "content_base64" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_invalid_base64(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(
                action="create",
                project_id="proj",
                filename="f.txt",
                content_base64="!!! not base64 !!!",
            )
        assert "error" in result
        assert "base64" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_empty_decoded_content(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(
                action="create",
                project_id="proj",
                filename="f.txt",
                content_base64=_b64(b""),
            )
        assert "error" in result
        assert "empty" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_oversized_content(self):
        big = b"x" * (50 * 1024 * 1024 + 1)
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(
                action="create",
                project_id="proj",
                filename="f.bin",
                content_base64=_b64(big),
            )
        assert "error" in result
        assert "too large" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_missing_project_id(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(
                action="create",
                filename="f.txt",
                content_base64=_b64(b"x"),
            )
        assert "error" in result
        assert "project_id" in result["error"]


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestManageDocumentUpdate:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_update_success(self, mock_redmine):
        mock_redmine.engine.request.return_value = True
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(
                action="update",
                document_id=42,
                fields={"title": "New", "description": "Updated"},
            )
        assert result["success"] is True
        assert set(result["updated_fields"]) == {"title", "description"}
        call_args = mock_redmine.engine.request.call_args
        assert call_args.args[0] == "post"
        assert call_args.args[1].endswith("/dmsf_files/42/revision/create.json")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_filters_unknown_fields(self, mock_redmine):
        mock_redmine.engine.request.return_value = True
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(
                action="update",
                document_id=42,
                fields={"title": "New", "evil": "bad", "filename": "x"},
            )
        # filename should be filtered (immutable in DMSF)
        assert result["updated_fields"] == ["title"]
        body = json.loads(mock_redmine.engine.request.call_args.kwargs["data"])
        assert "evil" not in body["dmsf_file_revision"]
        assert "filename" not in body["dmsf_file_revision"]

    @pytest.mark.asyncio
    async def test_blocked_in_read_only_mode(self):
        with patch.dict(
            os.environ,
            {"REDMINE_MCP_READ_ONLY": "true", "REDMINE_DMSF_ENABLED": "true"},
        ):
            result = await manage_document(
                action="update", document_id=1, fields={"title": "X"}
            )
        assert "error" in result
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_invalid_document_id(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(
                action="update", document_id=-1, fields={"title": "X"}
            )
        assert "error" in result
        assert "document_id" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_empty_fields(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(action="update", document_id=1, fields={})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_no_writable_fields(self):
        with patch.dict(os.environ, {"REDMINE_DMSF_ENABLED": "true"}):
            result = await manage_document(
                action="update",
                document_id=1,
                fields={"filename": "X", "rogue": "y"},
            )
        assert "error" in result
        assert "writable" in result["error"].lower()


# ---------------------------------------------------------------------------
# Suppress unused-mock warning when MagicMock isn't actually referenced below
# ---------------------------------------------------------------------------

_ = MagicMock
