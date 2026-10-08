"""Tests for the ticketed upload route (#305).

The point of this path is that a caller's file reaches the server without
being retyped by the model, so the tests care about two things: that the
ticket is a real single-use capability, and that a staged file comes back
byte-for-byte on the way into ``uploads``.
"""

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from redmine_mcp_server import _caller, _upload_store
from redmine_mcp_server.tools.files import (
    _resolve_upload_content,
    _verify_integrity,
    create_upload_ticket,
)


@pytest.fixture
def attachments_dir(tmp_path, monkeypatch):
    path = tmp_path / "attachments"
    path.mkdir()
    monkeypatch.setenv("ATTACHMENTS_DIR", str(path))
    return path


@pytest.fixture
def app():
    from redmine_mcp_server.main import app

    return app


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _expire(attachments_dir, upload_id):
    """Backdate a record's expiry, the way time would."""
    path = attachments_dir / upload_id / "metadata.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    ).isoformat()
    path.write_text(json.dumps(record), encoding="utf-8")


@pytest.mark.unit
class TestTicketStore:
    def test_ticket_is_not_stored_in_the_clear(self, attachments_dir):
        ticket = _upload_store.create_ticket(filename="mockup.png")
        record = json.loads(
            (attachments_dir / ticket["upload_id"] / "metadata.json").read_text(
                encoding="utf-8"
            )
        )

        assert "ticket" not in record
        assert ticket["ticket"] not in json.dumps(record)
        assert (
            record["ticket_sha256"]
            == hashlib.sha256(ticket["ticket"].encode("utf-8")).hexdigest()
        )

    def test_filename_is_reduced_to_a_basename(self, attachments_dir):
        ticket = _upload_store.create_ticket(filename="../../etc/passwd")

        assert ticket["filename"] == "passwd"
        assert ".." not in ticket["filename"]

    def test_dotdot_filename_cannot_escape_the_attachments_dir(self, attachments_dir):
        """``os.path.basename("..")`` is ``".."`` -- a directory, not a file.

        It falls back to the generated name, and the staged bytes stay in the
        upload's own directory, inside the tree the cleanup manager sweeps.
        """
        ticket = _upload_store.create_ticket(filename="..")

        assert ticket["filename"] == f"upload_{ticket['upload_id']}"

        record = _upload_store._read_record(ticket["upload_id"])
        staged = _upload_store.staged_path(record).resolve()
        assert staged.parent == (attachments_dir / ticket["upload_id"]).resolve()

    def test_dot_filename_does_not_land_on_the_directory_itself(self, attachments_dir):
        ticket = _upload_store.create_ticket(filename=".")

        assert ticket["filename"] == f"upload_{ticket['upload_id']}"

        record = _upload_store._read_record(ticket["upload_id"])
        staged = _upload_store.staged_path(record).resolve()
        assert staged != (attachments_dir / ticket["upload_id"]).resolve()
        assert staged.parent == (attachments_dir / ticket["upload_id"]).resolve()

    def test_wrong_ticket_and_unknown_id_are_indistinguishable(self, attachments_dir):
        issued = _upload_store.create_ticket(filename="a.txt")

        _, wrong = _upload_store.redeem_ticket(issued["upload_id"], "not-the-ticket")
        _, unknown = _upload_store.redeem_ticket(str(uuid.uuid4()), issued["ticket"])

        # Same wording, so the endpoint cannot be used to probe which ids exist.
        assert wrong == unknown

    def test_expired_ticket_is_refused(self, attachments_dir):
        issued = _upload_store.create_ticket(filename="a.txt")
        _expire(attachments_dir, issued["upload_id"])

        record, reason = _upload_store.redeem_ticket(
            issued["upload_id"], issued["ticket"]
        )

        assert record is None
        assert "expired" in reason

    def test_a_ticket_is_good_for_one_upload(self, attachments_dir):
        issued = _upload_store.create_ticket(filename="a.txt")
        record, reason = _upload_store.redeem_ticket(
            issued["upload_id"], issued["ticket"]
        )
        assert reason is None

        path = _upload_store.staged_path(record)
        path.write_bytes(b"hello")
        _upload_store.mark_ready(issued["upload_id"], record, 5, "abc")

        again, reason = _upload_store.redeem_ticket(
            issued["upload_id"], issued["ticket"]
        )
        assert again is None
        assert "already been used" in reason


@pytest.mark.unit
class TestUploadRoute:
    @pytest.mark.asyncio
    async def test_raw_body_is_stored_byte_for_byte(self, app, attachments_dir):
        payload = bytes(range(256)) * 8
        issued = _upload_store.create_ticket(filename="blob.bin")

        async with _client(app) as client:
            response = await client.post(
                f"/uploads/{issued['upload_id']}",
                content=payload,
                headers={"X-Upload-Ticket": issued["ticket"]},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["size"] == len(payload)
        assert body["sha256"] == hashlib.sha256(payload).hexdigest()

        staged, name, error = _upload_store.read_staged(issued["upload_id"])
        assert error is None
        assert staged == payload
        assert name == "blob.bin"

    @pytest.mark.asyncio
    async def test_multipart_is_not_treated_as_a_form(self, app, attachments_dir):
        """Starlette's form() buffers the whole body before the cap can look.

        So there is no multipart branch: a multipart body is stored as the
        raw bytes it is, and the caller gets a file it did not mean to send
        rather than an unbounded write.
        """
        issued = _upload_store.create_ticket(filename="note.txt")

        async with _client(app) as client:
            response = await client.post(
                f"/uploads/{issued['upload_id']}",
                files={"file": ("note.txt", b"hello world", "text/plain")},
                headers={"X-Upload-Ticket": issued["ticket"]},
            )

        assert response.status_code == 200
        staged, _, error = _upload_store.read_staged(issued["upload_id"])
        assert error is None
        # The MIME envelope, not the part -- nothing unwrapped it.
        assert staged != b"hello world"
        assert b"hello world" in staged

    @pytest.mark.asyncio
    async def test_wrong_ticket_is_refused_and_stores_nothing(
        self, app, attachments_dir
    ):
        issued = _upload_store.create_ticket(filename="a.txt")

        async with _client(app) as client:
            response = await client.post(
                f"/uploads/{issued['upload_id']}",
                content=b"payload",
                headers={"X-Upload-Ticket": "wrong"},
            )

        assert response.status_code == 404
        _, _, error = _upload_store.read_staged(issued["upload_id"])
        assert error is not None

    @pytest.mark.asyncio
    async def test_second_upload_on_the_same_ticket_is_refused(
        self, app, attachments_dir
    ):
        issued = _upload_store.create_ticket(filename="a.txt")
        headers = {"X-Upload-Ticket": issued["ticket"]}

        async with _client(app) as client:
            first = await client.post(
                f"/uploads/{issued['upload_id']}", content=b"one", headers=headers
            )
            second = await client.post(
                f"/uploads/{issued['upload_id']}", content=b"two", headers=headers
            )

        assert first.status_code == 200
        assert second.status_code == 410

        staged, _, _ = _upload_store.read_staged(issued["upload_id"])
        assert staged == b"one"

    @pytest.mark.asyncio
    async def test_oversize_body_is_refused(self, app, attachments_dir, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_UPLOAD_MAX_BYTES", "16")
        issued = _upload_store.create_ticket(filename="big.bin")

        async with _client(app) as client:
            response = await client.post(
                f"/uploads/{issued['upload_id']}",
                content=b"x" * 64,
                headers={"X-Upload-Ticket": issued["ticket"]},
            )

        assert response.status_code == 413

    @pytest.mark.asyncio
    async def test_empty_body_is_refused(self, app, attachments_dir):
        issued = _upload_store.create_ticket(filename="empty.bin")

        async with _client(app) as client:
            response = await client.post(
                f"/uploads/{issued['upload_id']}",
                content=b"",
                headers={"X-Upload-Ticket": issued["ticket"]},
            )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_upload_id_is_not_a_server_error(self, app, attachments_dir):
        async with _client(app) as client:
            response = await client.post(
                f"/uploads/{uuid.uuid4()}",
                content=b"payload",
                headers={"X-Upload-Ticket": "anything"},
            )

        assert response.status_code == 404


class _NoDiscoveryAuth:
    """Stands in for the auth provider; these tests are about the routes."""

    def get_well_known_routes(self, mcp_path=None):
        return []


@pytest.fixture
def authenticated_app(monkeypatch):
    """The app the authenticated modes serve, with a path in the base URL.

    There the MCP app is mounted under that path, so a route it registers
    for itself answers under the path too, not where ``upload_url`` points.
    """
    monkeypatch.setenv("REDMINE_MCP_BASE_URL", "http://test/redmine")
    monkeypatch.setenv("FASTMCP_STREAMABLE_HTTP_PATH", "/mcp")

    from redmine_mcp_server.main import build_authenticated_app
    from redmine_mcp_server.server import mcp

    return build_authenticated_app(mcp, _NoDiscoveryAuth())


@pytest.mark.unit
class TestUploadRouteInAuthenticatedApp:
    @pytest.mark.asyncio
    async def test_upload_url_is_served_when_the_base_url_has_a_path(
        self, authenticated_app, attachments_dir, monkeypatch
    ):
        """The ``upload_url`` a ticket hands out must reach the route.

        It is built at the root of the public origin, like ``/files/{id}``,
        so the authenticated app has to serve ``/uploads/{id}`` there as
        well as under the mount (#393).
        """
        monkeypatch.setenv("PUBLIC_HOST", "test")
        monkeypatch.setenv("PUBLIC_PORT", "80")
        monkeypatch.delenv("PUBLIC_SCHEME", raising=False)
        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
        payload = b"hello world"

        issued = await create_upload_ticket(filename="note.txt")

        async with _client(authenticated_app) as client:
            response = await client.post(
                issued["upload_url"],
                content=payload,
                headers={"X-Upload-Ticket": issued["ticket"]},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["upload_id"] == issued["upload_id"]
        assert body["size"] == len(payload)
        assert body["sha256"] == hashlib.sha256(payload).hexdigest()

    @pytest.mark.asyncio
    async def test_unknown_upload_id_at_the_root_reaches_the_route(
        self, authenticated_app, attachments_dir
    ):
        """A refusal from the route itself, not Starlette's bare Not Found."""
        async with _client(authenticated_app) as client:
            response = await client.post(
                f"/uploads/{uuid.uuid4()}",
                content=b"payload",
                headers={"X-Upload-Ticket": "anything"},
            )

        assert response.status_code == 404
        assert response.json() == {"error": "Unknown upload_id or invalid ticket."}


@pytest.mark.unit
class TestStagedUploadsAreNotServed:
    @pytest.mark.asyncio
    async def test_files_route_refuses_a_staged_upload(self, app, attachments_dir):
        """A staged upload must not be downloadable by its upload_id.

        Both live in the same UUID directories, but the ids do not carry the
        same weight: an upload_id travels in the upload URL and so reaches
        proxy logs, while a downloaded attachment's id is only ever handed to
        the caller.
        """
        issued = _upload_store.create_ticket(filename="secret.png")
        async with _client(app) as client:
            posted = await client.post(
                f"/uploads/{issued['upload_id']}",
                content=b"the staged bytes",
                headers={"X-Upload-Ticket": issued["ticket"]},
            )
            served = await client.get(f"/files/{issued['upload_id']}")

        assert posted.status_code == 200
        assert served.status_code == 404
        assert b"the staged bytes" not in served.content


@pytest.mark.unit
class TestStagedNameIsChosenByTheServer:
    """The caller's filename is a display name, never a path on this server.

    The staged bytes share a directory with the slot's own ``metadata.json``.
    Had the caller's name been used for them, ``filename="metadata.json"``
    would stage the upload *onto* the record: ``read_staged`` would then hand
    back the record instead of the file, and in the moment between the bytes
    landing and ``mark_ready`` rewriting the record, a body shaped like a
    ready record would be taken for one -- with a ``file_path`` of its
    choosing.
    """

    HOSTILE_NAMES = [
        "metadata.json",
        "metadata.json.tmp",
        "./metadata.json",
        "../x/metadata.json",
        "",
        ".",
        "..",
    ]

    @pytest.mark.parametrize("filename", HOSTILE_NAMES)
    def test_staged_path_never_lands_on_the_record(self, attachments_dir, filename):
        issued = _upload_store.create_ticket(filename=filename)
        upload_id = issued["upload_id"]
        uuid_dir = (attachments_dir / upload_id).resolve()
        record = _upload_store._read_record(upload_id)

        staged = _upload_store.staged_path(record).resolve()
        # What receive_upload streams into before the rename.
        staged_temp = staged.with_suffix(staged.suffix + ".tmp")
        record_files = {
            _upload_store._record_path(upload_id).resolve(),
            uuid_dir / "metadata.json.tmp",
        }

        assert staged == uuid_dir / f"upload_{upload_id}"
        assert staged not in record_files
        assert staged_temp not in record_files

    @pytest.mark.asyncio
    @pytest.mark.parametrize("filename", ["metadata.json", "metadata.json.tmp"])
    async def test_record_named_upload_round_trips(
        self, app, attachments_dir, filename
    ):
        payload = b"not a record, just a file called " + filename.encode("ascii")
        issued = _upload_store.create_ticket(filename=filename)
        upload_id = issued["upload_id"]

        async with _client(app) as client:
            response = await client.post(
                f"/uploads/{upload_id}",
                content=payload,
                headers={"X-Upload-Ticket": issued["ticket"]},
            )

        assert response.status_code == 200
        assert issued["filename"] == filename
        assert response.json()["filename"] == filename

        staged, name, error = _upload_store.read_staged(upload_id)
        assert error is None
        assert staged == payload
        assert name == filename

        record = json.loads(
            (attachments_dir / upload_id / "metadata.json").read_text(encoding="utf-8")
        )
        assert record["kind"] == "upload"
        assert record["state"] == "ready"
        assert record["sha256"] == hashlib.sha256(payload).hexdigest()

    @pytest.mark.asyncio
    async def test_a_forged_record_in_the_body_is_never_followed(
        self, app, attachments_dir, tmp_path, monkeypatch
    ):
        """Read the slot in the window between the rename and ``mark_ready``.

        That is where a concurrent ``*_upload_id`` consumer could land. The
        body is a ready record pointing at a file outside the attachments
        tree; it must come back as the bytes that were sent, and the secret
        must not come back at all.
        """
        secret = tmp_path / "secret.txt"
        secret.write_bytes(b"server-side secret")
        forged = json.dumps(
            {
                "kind": "upload",
                "state": "ready",
                "file_path": str(secret),
                "original_filename": "secret.txt",
            }
        ).encode("utf-8")

        issued = _upload_store.create_ticket(filename="metadata.json")
        upload_id = issued["upload_id"]

        seen_in_window = []
        real_mark_ready = _upload_store.mark_ready

        def mark_ready_after_a_concurrent_read(*args, **kwargs):
            seen_in_window.append(_upload_store.read_staged(upload_id))
            return real_mark_ready(*args, **kwargs)

        monkeypatch.setattr(
            _upload_store, "mark_ready", mark_ready_after_a_concurrent_read
        )

        async with _client(app) as client:
            response = await client.post(
                f"/uploads/{upload_id}",
                content=forged,
                headers={"X-Upload-Ticket": issued["ticket"]},
            )

        assert response.status_code == 200
        assert len(seen_in_window) == 1
        in_window, _, window_error = seen_in_window[0]
        assert b"server-side secret" not in in_window
        # The record is still the server's own, so the slot is not ready yet.
        assert window_error is not None

        staged, name, error = _upload_store.read_staged(upload_id)
        assert error is None
        assert staged == forged
        assert name == "metadata.json"

    @pytest.mark.asyncio
    async def test_a_slot_reserved_with_the_callers_name_still_round_trips(
        self, app, attachments_dir
    ):
        """A ticket issued before the change can still be pending afterwards.

        Its record names the caller's file -- here the record itself, as the
        old code wrote it for ``filename="metadata.json"``. The upload must
        land at the computed path regardless, and the record must survive.
        """
        payload = b"bytes for a slot reserved the old way"
        issued = _upload_store.create_ticket(filename="metadata.json")
        upload_id = issued["upload_id"]
        record_file = attachments_dir / upload_id / "metadata.json"
        record = json.loads(record_file.read_text(encoding="utf-8"))
        record["file_path"] = str(record_file.resolve())
        record_file.write_text(json.dumps(record), encoding="utf-8")

        async with _client(app) as client:
            response = await client.post(
                f"/uploads/{upload_id}",
                content=payload,
                headers={"X-Upload-Ticket": issued["ticket"]},
            )

        assert response.status_code == 200

        staged, name, error = _upload_store.read_staged(upload_id)
        assert error is None
        assert staged == payload
        assert name == "metadata.json"

        record = json.loads(record_file.read_text(encoding="utf-8"))
        assert record["kind"] == "upload"
        assert record["state"] == "ready"
        assert record["file_path"] == str(
            (attachments_dir / upload_id).resolve() / f"upload_{upload_id}"
        )

    @pytest.mark.asyncio
    async def test_an_expired_slot_is_swept_with_its_file(self, app, attachments_dir):
        from redmine_mcp_server.file_manager import AttachmentFileManager

        issued = _upload_store.create_ticket(filename="metadata.json")
        upload_id = issued["upload_id"]
        async with _client(app) as client:
            await client.post(
                f"/uploads/{upload_id}",
                content=b"bytes",
                headers={"X-Upload-Ticket": issued["ticket"]},
            )
        _expire(attachments_dir, upload_id)

        stats = AttachmentFileManager(str(attachments_dir)).cleanup_expired_files()

        assert stats["cleaned_files"] == 1
        assert stats["cleaned_bytes"] == len(b"bytes")
        assert not (attachments_dir / upload_id).exists()


@pytest.mark.unit
class TestUploadIdAsContentSource:
    @pytest.mark.asyncio
    async def test_staged_file_resolves(self, app, attachments_dir):
        payload = b"\x89PNG\r\n\x1a\n" + bytes(range(64))
        issued = _upload_store.create_ticket(filename="mockup.png")
        async with _client(app) as client:
            await client.post(
                f"/uploads/{issued['upload_id']}",
                content=payload,
                headers={"X-Upload-Ticket": issued["ticket"]},
            )

        content, name, error = await _resolve_upload_content(
            filename=None, upload_id=issued["upload_id"]
        )

        assert error is None
        assert content == payload
        assert name == "mockup.png"

    @pytest.mark.asyncio
    async def test_explicit_filename_wins(self, app, attachments_dir):
        issued = _upload_store.create_ticket(filename="staged.png")
        async with _client(app) as client:
            await client.post(
                f"/uploads/{issued['upload_id']}",
                content=b"bytes",
                headers={"X-Upload-Ticket": issued["ticket"]},
            )

        _, name, error = await _resolve_upload_content(
            filename="renamed.png", upload_id=issued["upload_id"]
        )

        assert error is None
        assert name == "renamed.png"

    @pytest.mark.asyncio
    async def test_reserved_but_never_sent_is_an_error(self, attachments_dir):
        issued = _upload_store.create_ticket(filename="a.txt")

        _, _, error = await _resolve_upload_content(
            filename=None, upload_id=issued["upload_id"]
        )

        assert error is not None
        assert "never received a file" in error["error"]

    @pytest.mark.asyncio
    async def test_expired_staged_file_is_an_error(self, app, attachments_dir):
        issued = _upload_store.create_ticket(filename="a.txt")
        async with _client(app) as client:
            await client.post(
                f"/uploads/{issued['upload_id']}",
                content=b"bytes",
                headers={"X-Upload-Ticket": issued["ticket"]},
            )
        _expire(attachments_dir, issued["upload_id"])

        _, _, error = await _resolve_upload_content(
            filename=None, upload_id=issued["upload_id"]
        )

        assert error is not None
        assert "expired" in error["error"]

    @pytest.mark.asyncio
    async def test_upload_id_is_exclusive_with_the_other_sources(self, attachments_dir):
        _, _, error = await _resolve_upload_content(
            filename="a.txt", upload_id=str(uuid.uuid4()), content_base64="eA=="
        )

        assert error is not None
        assert "exactly ONE" in error["error"]


@pytest.mark.unit
class TestIntegrityVerification:
    def test_matching_checksum_passes(self):
        payload = b"the bytes that were meant"

        assert (
            _verify_integrity(payload, hashlib.sha256(payload).hexdigest(), None)
            is None
        )

    def test_mismatched_checksum_is_refused_and_names_the_alternative(self):
        error = _verify_integrity(
            b"what arrived", hashlib.sha256(b"what was meant").hexdigest(), None
        )

        assert error is not None
        assert "sha256 mismatch" in error["error"]
        assert "create_upload_ticket" in error["error"]

    def test_size_mismatch_is_refused(self):
        error = _verify_integrity(b"1234", None, 9)

        assert error is not None
        assert "size_bytes mismatch" in error["error"]

    def test_size_accepts_a_numeric_string(self):
        assert _verify_integrity(b"1234", None, "4") is None

    def test_nonsense_size_is_reported_rather_than_ignored(self):
        error = _verify_integrity(b"1234", None, "four")

        assert error is not None
        assert "not a number" in error["error"]

    def test_no_claim_means_no_check(self):
        assert _verify_integrity(b"anything", None, None) is None

    def test_the_corruption_this_guards_against(self):
        """The real case from #305: a payload that lost characters in transit."""
        intended = bytes(range(256)) * 4
        mangled = intended[:900] + intended[924:]

        assert (
            _verify_integrity(mangled, hashlib.sha256(intended).hexdigest(), None)
            is not None
        )


@pytest.mark.unit
class TestCreateUploadTicketTool:
    @pytest.mark.asyncio
    async def test_returns_a_url_the_caller_can_post_to(
        self, attachments_dir, monkeypatch
    ):
        monkeypatch.setenv("PUBLIC_HOST", "mcp.example.com")
        monkeypatch.setenv("PUBLIC_PORT", "443")
        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)

        result = await create_upload_ticket(filename="mockup.png")

        assert result["upload_url"] == (
            f"https://mcp.example.com/uploads/{result['upload_id']}"
        )
        assert result["ticket"]
        assert result["max_bytes"] > 0

    @pytest.mark.asyncio
    async def test_without_a_public_address_it_says_so(
        self, attachments_dir, monkeypatch
    ):
        monkeypatch.delenv("PUBLIC_HOST", raising=False)
        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
        monkeypatch.setenv("SERVER_HOST", "0.0.0.0")

        result = await create_upload_ticket(filename="mockup.png")

        assert "error" in result
        assert "file_path" in result["error"]

    @pytest.mark.asyncio
    async def test_stdio_transport_has_no_url_even_with_public_host(
        self, attachments_dir, monkeypatch
    ):
        # No HTTP server is listening under stdio, so PUBLIC_HOST must not
        # turn into an upload_url that leads nowhere.
        monkeypatch.setenv("REDMINE_MCP_TRANSPORT", "stdio")
        monkeypatch.setenv("PUBLIC_HOST", "mcp.example.com")
        monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)

        result = await create_upload_ticket(filename="mockup.png")

        assert "upload_url" not in result
        assert "stdio" in result["error"]
        assert "file_path" in result["error"]

    @pytest.mark.asyncio
    async def test_read_only_mode_refuses(self, attachments_dir, monkeypatch):
        monkeypatch.setenv("PUBLIC_HOST", "mcp.example.com")
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")

        result = await create_upload_ticket(filename="mockup.png")

        assert "error" in result
        assert "upload_url" not in result


@pytest.mark.unit
class TestBase64Cap:
    @pytest.mark.asyncio
    async def test_cap_points_at_the_upload_route(self, monkeypatch):
        import base64

        monkeypatch.setenv("REDMINE_MCP_CONTENT_BASE64_MAX_BYTES", "8")
        payload = base64.b64encode(b"x" * 64).decode("ascii")

        _, _, error = await _resolve_upload_content(
            filename="big.bin", content_base64=payload
        )

        assert error is not None
        assert "create_upload_ticket" in error["error"]

    @pytest.mark.asyncio
    async def test_unset_cap_changes_nothing(self, monkeypatch):
        import base64

        monkeypatch.delenv("REDMINE_MCP_CONTENT_BASE64_MAX_BYTES", raising=False)
        payload = base64.b64encode(b"x" * 64).decode("ascii")

        content, _, error = await _resolve_upload_content(
            filename="small.bin", content_base64=payload
        )

        assert error is None
        assert content == b"x" * 64


# ---------------------------------------------------------------------------
# A staged upload belongs to the caller that created its ticket.
#
# The upload_id is the path of the upload_url, so it is in every proxy access
# log the POST passed through. Before slots were bound, anyone signed in who
# read such a log could attach that file as their own.
# ---------------------------------------------------------------------------


def _unknown(upload_id):
    """The error an id nobody ever reserved gets, word for word."""
    return {
        "error": (
            f"No staged upload {upload_id}. Create one with create_upload_ticket "
            "and POST the file to the returned upload_url before attaching it."
        )
    }


def _signed_in_as(user_id):
    """Run as an api-key-login caller whose binding names ``user_id``.

    The mode where the server knows the caller without asking Redmine, so
    these tests need nothing but the token.
    """
    from contextlib import ExitStack

    from redmine_mcp_server import _client

    token = Mock()
    token.claims = {"redmine_user_id": user_id}
    stack = ExitStack()
    stack.enter_context(patch.object(_client, "REDMINE_AUTH_MODE", "api-key-login"))
    stack.enter_context(
        patch("redmine_mcp_server._caller.get_access_token", return_value=token)
    )
    return stack


async def _post(app, issued, payload=b"bytes"):
    async with _client(app) as client:
        response = await client.post(
            f"/uploads/{issued['upload_id']}",
            content=payload,
            headers={"X-Upload-Ticket": issued["ticket"]},
        )
    assert response.status_code == 200
    return response


@pytest.fixture
def public_address(monkeypatch):
    monkeypatch.setenv("PUBLIC_HOST", "mcp.example.com")
    monkeypatch.setenv("PUBLIC_PORT", "443")
    monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)


@pytest.mark.unit
class TestStagedUploadOwner:
    def test_the_record_names_the_owner(self, attachments_dir):
        issued = _upload_store.create_ticket(filename="a.txt", owner="redmine-user:5")

        record = _upload_store._read_record(issued["upload_id"])

        assert record["owner"] == "redmine-user:5"
        assert "owner" not in issued

    @pytest.mark.asyncio
    async def test_the_owner_reads_it_back(self, app, attachments_dir):
        issued = _upload_store.create_ticket(filename="a.txt", owner="redmine-user:5")
        await _post(app, issued, b"mine")

        content, name, error = _upload_store.read_staged(
            issued["upload_id"], owner="redmine-user:5"
        )

        assert error is None
        assert content == b"mine"
        assert name == "a.txt"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", ["ready", "pending", "expired"])
    @pytest.mark.parametrize("stranger", ["redmine-user:6", None])
    async def test_a_stranger_cannot_tell_it_from_an_unknown_id(
        self, app, attachments_dir, state, stranger
    ):
        """Another caller, or one the server could not identify, gets the
        words an id nobody reserved gets, so the refusal cannot be used to
        learn which ids are real.

        The owner check comes before the state and expiry messages. Those say
        "reserved but never received a file" and "has expired", which would
        confirm to anyone that the id exists.
        """
        issued = _upload_store.create_ticket(filename="a.txt", owner="redmine-user:5")
        upload_id = issued["upload_id"]
        if state != "pending":
            await _post(app, issued)
        if state == "expired":
            _expire(attachments_dir, upload_id)

        assert _upload_store.read_staged(upload_id, owner=stranger) == (
            b"",
            None,
            _unknown(upload_id),
        )

    @pytest.mark.asyncio
    async def test_leaving_the_owner_out_is_refused_a_bound_slot(
        self, app, attachments_dir
    ):
        issued = _upload_store.create_ticket(filename="a.txt", owner="redmine-user:5")
        await _post(app, issued)

        _, _, error = _upload_store.read_staged(issued["upload_id"])

        assert error == _unknown(issued["upload_id"])

    def test_the_owner_still_hears_why_a_pending_slot_is_not_ready(
        self, attachments_dir
    ):
        issued = _upload_store.create_ticket(filename="a.txt", owner="redmine-user:5")

        _, _, owner = _upload_store.read_staged(
            issued["upload_id"], owner="redmine-user:5"
        )

        assert "never received a file" in owner["error"]

    @pytest.mark.asyncio
    async def test_an_unbound_slot_is_open_to_anyone(self, app, attachments_dir):
        """Legacy mode, and slots reserved before slots were bound."""
        issued = _upload_store.create_ticket(filename="a.txt")
        await _post(app, issued, b"shared")

        for owner in (None, "redmine-user:5", "api-key:" + "0" * 64):
            content, _, error = _upload_store.read_staged(
                issued["upload_id"], owner=owner
            )
            assert error is None
            assert content == b"shared"

    @pytest.mark.asyncio
    async def test_an_owner_outside_ascii_still_compares(self, app, attachments_dir):
        """``compare_digest`` refuses a non-ASCII ``str``; a ``sub`` can be one."""
        issued = _upload_store.create_ticket(
            filename="a.txt", owner="redmine-user:jürgen"
        )
        upload_id = issued["upload_id"]
        await _post(app, issued)

        _, _, mine = _upload_store.read_staged(upload_id, owner="redmine-user:jürgen")
        _, _, other = _upload_store.read_staged(upload_id, owner="redmine-user:jurgen")

        assert mine is None
        assert other == _unknown(upload_id)

    @pytest.mark.asyncio
    async def test_the_post_stays_ticket_only(self, app, attachments_dir):
        """Whoever holds the ticket may send the bytes; reading is what binds."""
        issued = _upload_store.create_ticket(filename="a.txt", owner="redmine-user:5")

        response = await _post(app, issued)

        assert "owner" not in response.json()
        record = _upload_store._read_record(issued["upload_id"])
        assert record["state"] == "ready"
        assert record["owner"] == "redmine-user:5"


@pytest.mark.unit
class TestCallerIdentity:
    """What the server can name the caller by, mode by mode."""

    @staticmethod
    def _token(subject=None, claims=None):
        token = Mock()
        token.subject = subject
        token.claims = claims if claims is not None else {}
        return token

    @staticmethod
    def _mode(mode):
        from redmine_mcp_server import _client

        return patch.object(_client, "REDMINE_AUTH_MODE", mode)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "mode, token, expected",
        [
            ("api-key-login", {"claims": {"redmine_user_id": 7}}, "redmine-user:7"),
            ("oauth", {"subject": "5"}, "redmine-user:5"),
            ("oauth-proxy", {"subject": "5"}, "redmine-user:5"),
            # Without a token the client would fall back to the configured
            # account, so there is no one to look up.
            ("oauth", None, None),
            ("legacy", None, None),
        ],
    )
    async def test_answers_without_asking_redmine(self, mode, token, expected):
        token = self._token(**token) if token is not None else None
        with (
            self._mode(mode),
            patch.object(_caller, "get_access_token", return_value=token),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            assert _caller.staged_upload_owner() == expected
            assert await _caller.resolve_staged_upload_owner() == expected
            mock_redmine.user.get.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["oauth", "oauth-proxy"])
    async def test_oauth_without_a_subject_asks_redmine_who_it_is(self, mode):
        """Doorkeeper's introspection has no ``sub`` unless it is configured."""
        with (
            self._mode(mode),
            patch.object(_caller, "get_access_token", return_value=self._token()),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            mock_redmine.user.get.return_value.id = 5

            assert _caller.staged_upload_owner() is None
            assert await _caller.resolve_staged_upload_owner() == "redmine-user:5"
            mock_redmine.user.get.assert_called_once_with("current")

    @pytest.mark.asyncio
    async def test_the_blocking_form_asks_the_same_question(self):
        """For a tool body that is already in a worker thread."""
        import asyncio

        with (
            self._mode("oauth-proxy"),
            patch.object(_caller, "get_access_token", return_value=self._token()),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            mock_redmine.user.get.return_value.id = 5

            owner = await asyncio.to_thread(
                _caller.resolve_staged_upload_owner_blocking
            )

        assert owner == "redmine-user:5"

    @pytest.mark.asyncio
    async def test_a_failed_lookup_leaves_the_caller_unidentified(self):
        with (
            self._mode("oauth-proxy"),
            patch.object(_caller, "get_access_token", return_value=self._token()),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            mock_redmine.user.get.side_effect = ConnectionError("down")

            assert await _caller.resolve_staged_upload_owner() is None

    @pytest.mark.asyncio
    async def test_legacy_per_user_uses_a_digest_of_the_key(self):
        from types import SimpleNamespace

        key = "a1b2c3d4e5" * 4
        request = SimpleNamespace(headers={"X-Redmine-API-Key": key})
        with (
            self._mode("legacy-per-user"),
            patch.object(_caller, "get_http_request", return_value=request),
        ):
            owner = await _caller.resolve_staged_upload_owner()

        assert owner == "api-key:" + hashlib.sha256(key.encode()).hexdigest()
        assert key not in owner

    @pytest.mark.parametrize(
        "headers",
        [
            {"X-Redmine-API-Key": "not a key!"},
            {"X-Redmine-API-Key": "a1b2c3d4e5" * 4, "X-Forwarded-Proto": "http"},
            {},
        ],
        ids=["malformed", "plaintext", "missing"],
    )
    def test_legacy_per_user_binds_only_a_header_the_call_would_accept(self, headers):
        """The checks every tool call makes first; a slot bound to the digest
        of a header that call refuses would belong to nobody."""
        from types import SimpleNamespace

        request = SimpleNamespace(headers=headers)
        with (
            self._mode("legacy-per-user"),
            patch.object(_caller, "get_http_request", return_value=request),
        ):
            assert _caller.staged_upload_owner() is None

    def test_legacy_per_user_outside_a_request_is_unidentified(self):
        with (
            self._mode("legacy-per-user"),
            patch.object(
                _caller, "get_http_request", side_effect=RuntimeError("no request")
            ),
        ):
            assert _caller.staged_upload_owner() is None

    @pytest.mark.parametrize(
        "mode, has_token, expected",
        [
            ("api-key-login", True, True),
            ("legacy-per-user", False, True),
            ("oauth", True, True),
            ("oauth-proxy", True, True),
            ("oauth", False, False),
            ("oauth-proxy", False, False),
            ("legacy", False, False),
        ],
    )
    def test_where_an_identity_is_expected(self, mode, has_token, expected):
        """Where it is, a ticket nobody can be bound to is refused."""
        token = self._token() if has_token else None
        with (
            self._mode(mode),
            patch.object(_caller, "get_access_token", return_value=token),
        ):
            assert _caller.identity_expected() is expected


@pytest.mark.unit
@pytest.mark.usefixtures("public_address")
class TestCreateUploadTicketBindsTheCaller:
    @pytest.mark.asyncio
    async def test_the_slot_records_who_asked(self, attachments_dir):
        with _signed_in_as(5):
            result = await create_upload_ticket(filename="mockup.png")

        record = _upload_store._read_record(result["upload_id"])
        assert record["owner"] == "redmine-user:5"

    @pytest.mark.asyncio
    async def test_the_answer_does_not_change(self, attachments_dir):
        with _signed_in_as(5):
            result = await create_upload_ticket(filename="mockup.png")

        assert set(result) == {
            "upload_url",
            "upload_id",
            "ticket",
            "filename",
            "expires_at",
            "max_bytes",
        }

    @pytest.mark.asyncio
    async def test_an_unidentified_caller_gets_no_ticket(self, attachments_dir):
        """Fail closed, as a read does: an unbound slot in a per-user mode
        would be one anyone could read, with nothing to say so."""
        from redmine_mcp_server import _client

        token = Mock()
        token.subject = None
        with (
            patch.object(_client, "REDMINE_AUTH_MODE", "oauth-proxy"),
            patch("redmine_mcp_server._caller.get_access_token", return_value=token),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            mock_redmine.user.get.side_effect = ConnectionError("down")
            result = await create_upload_ticket(filename="mockup.png")

        assert result == {
            "error": (
                "Could not identify the caller to bind this upload to. Try "
                "again; if it persists, check that the token can read "
                "GET /users/current.json."
            )
        }
        assert list(attachments_dir.iterdir()) == []

    @pytest.mark.asyncio
    async def test_api_key_login_without_a_user_says_to_sign_in_again(
        self, attachments_dir
    ):
        from redmine_mcp_server import _client

        token = Mock()
        token.claims = {}
        with (
            patch.object(_client, "REDMINE_AUTH_MODE", "api-key-login"),
            patch("redmine_mcp_server._caller.get_access_token", return_value=token),
        ):
            result = await create_upload_ticket(filename="mockup.png")

        assert result == {
            "error": (
                "Could not identify the caller to bind this upload to. The "
                "session is not bound to a Redmine user. Reconnect to sign in "
                "again."
            )
        }
        assert list(attachments_dir.iterdir()) == []

    @pytest.mark.asyncio
    async def test_legacy_per_user_with_a_bad_header_names_the_header(
        self, attachments_dir
    ):
        """Not "try again": the next request would carry the same header."""
        from types import SimpleNamespace

        from redmine_mcp_server import _client

        request = SimpleNamespace(headers={"X-Redmine-API-Key": "not a key!"})
        with (
            patch.object(_client, "REDMINE_AUTH_MODE", "legacy-per-user"),
            patch.object(_caller, "get_http_request", return_value=request),
        ):
            result = await create_upload_ticket(filename="mockup.png")

        assert result == {
            "error": (
                "Could not identify the caller to bind this upload to. Send "
                "your Redmine API key in the X-Redmine-API-Key header, over TLS."
            )
        }
        assert "Try again" not in result["error"]
        assert list(attachments_dir.iterdir()) == []

    @pytest.mark.asyncio
    async def test_legacy_leaves_the_slot_unbound(self, attachments_dir):
        from redmine_mcp_server import _client

        with patch.object(_client, "REDMINE_AUTH_MODE", "legacy"):
            result = await create_upload_ticket(filename="mockup.png")

        assert _upload_store._read_record(result["upload_id"])["owner"] is None


@pytest.mark.unit
@pytest.mark.usefixtures("public_address")
class TestAnotherUsersUploadId:
    """The tools refuse someone else's upload_id as if it did not exist."""

    async def _staged_by(self, app, user_id, payload=b"bytes"):
        with _signed_in_as(user_id):
            issued = await create_upload_ticket(filename="report.pdf")
        await _post(app, issued, payload)
        return issued["upload_id"]

    @pytest.mark.asyncio
    async def test_upload_file_refuses_it(self, app, attachments_dir):
        from redmine_mcp_server.tools.files import upload_file

        upload_id = await self._staged_by(app, 5)

        with (
            _signed_in_as(6),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            result = await upload_file(project_id="web", upload_id=upload_id)

        assert result == _unknown(upload_id)
        mock_redmine.upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_upload_file_takes_the_owner_s_own(self, app, attachments_dir):
        from redmine_mcp_server.tools.files import upload_file

        upload_id = await self._staged_by(app, 5, b"%PDF-1.7")

        with (
            _signed_in_as(5),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            mock_redmine.upload.return_value = {"token": "tok-1"}
            result = await upload_file(project_id="web", upload_id=upload_id)

        assert "error" not in result
        sent = mock_redmine.upload.call_args
        assert sent.args[0].getvalue() == b"%PDF-1.7"

    @pytest.mark.asyncio
    async def test_an_uploads_entry_refuses_it(self, app, attachments_dir):
        from redmine_mcp_server.tools.files import _build_upload_descriptors

        upload_id = await self._staged_by(app, 5)

        with (
            _signed_in_as(6),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            descriptors, error = await _build_upload_descriptors(
                [{"upload_id": upload_id}]
            )

        assert descriptors == []
        assert error["error"] == f"uploads[0]: {_unknown(upload_id)['error']}"
        mock_redmine.upload.assert_not_called()

    @staticmethod
    def _local(attachments_dir, upload_id, name):
        """The path a stranger would try, relative to the working directory
        the way a caller reading an access log would write it."""
        return os.path.relpath(attachments_dir / upload_id / name)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", ["upload_{id}", "metadata.json"])
    async def test_upload_file_cannot_take_it_by_path(self, app, attachments_dir, name):
        """``ATTACHMENTS_DIR`` is an upload root, so without this a staged
        file or its record was one ``file_path`` away from anyone."""
        from redmine_mcp_server.tools.files import upload_file

        upload_id = await self._staged_by(app, 5)
        path = self._local(attachments_dir, upload_id, name.format(id=upload_id))
        missing = self._local(attachments_dir, str(uuid.uuid4()), "upload_x")

        with (
            _signed_in_as(6),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            result = await upload_file(project_id="web", file_path=path)
            nothing = await upload_file(project_id="web", file_path=missing)

        assert result == {"error": f"file_path does not exist: {path}"}
        # Worded as for a file that is not there, so the path is no oracle.
        assert nothing == {"error": f"file_path does not exist: {missing}"}
        mock_redmine.upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_uploads_entry_cannot_take_it_by_path(self, app, attachments_dir):
        from redmine_mcp_server.tools.files import _build_upload_descriptors

        upload_id = await self._staged_by(app, 5)
        path = self._local(attachments_dir, upload_id, f"upload_{upload_id}")

        with (
            _signed_in_as(6),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            descriptors, error = await _build_upload_descriptors([{"file_path": path}])

        assert descriptors == []
        assert error == {"error": f"uploads[0]: file_path does not exist: {path}"}
        mock_redmine.upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_slot_directory_reads_as_missing_too(self, app, attachments_dir):
        from redmine_mcp_server.tools.files import upload_file

        upload_id = await self._staged_by(app, 5)
        path = os.path.relpath(attachments_dir / upload_id)

        with _signed_in_as(6), patch("redmine_mcp_server._client.redmine"):
            result = await upload_file(project_id="web", file_path=path)

        assert result == {"error": f"file_path does not exist: {path}"}

    @pytest.mark.asyncio
    async def test_a_downloaded_attachment_still_uploads_by_path(self, attachments_dir):
        """Downloads are why ``ATTACHMENTS_DIR`` is a root in the first place."""
        from redmine_mcp_server.tools.files import upload_file

        file_id = str(uuid.uuid4())
        (attachments_dir / file_id).mkdir()
        target = attachments_dir / file_id / f"attachment_{file_id}.txt"
        target.write_bytes(b"downloaded")
        (attachments_dir / file_id / "metadata.json").write_text("{}")

        with (
            _signed_in_as(6),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            mock_redmine.upload.return_value = {"token": "tok-1"}
            result = await upload_file(project_id="web", file_path=str(target))

        assert "error" not in result
        sent = mock_redmine.upload.call_args
        assert sent.args[0].getvalue() == b"downloaded"
        assert sent.kwargs["filename"] == f"attachment_{file_id}.txt"

    @pytest.mark.asyncio
    async def test_no_staged_file_means_no_lookup(self, attachments_dir):
        """The lookup costs a Redmine request in the OAuth modes; a list of
        base64 payloads has no use for it."""
        import base64
        from redmine_mcp_server import _client
        from redmine_mcp_server.tools.files import _build_upload_descriptors

        token = Mock()
        token.subject = None
        with (
            patch.object(_client, "REDMINE_AUTH_MODE", "oauth-proxy"),
            patch("redmine_mcp_server._caller.get_access_token", return_value=token),
            patch("redmine_mcp_server._client.redmine") as mock_redmine,
        ):
            mock_redmine.upload.return_value = {"token": "tok-1"}
            descriptors, error = await _build_upload_descriptors(
                [
                    {
                        "filename": "a.csv",
                        "content_base64": base64.b64encode(b"id").decode("ascii"),
                    }
                ]
            )

        assert error is None
        assert descriptors == [{"token": "tok-1", "filename": "a.csv"}]
        mock_redmine.user.get.assert_not_called()
