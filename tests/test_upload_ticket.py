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

import pytest
from httpx import ASGITransport, AsyncClient

from redmine_mcp_server import _upload_store
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
        assert record["ticket_sha256"] == hashlib.sha256(
            ticket["ticket"].encode("utf-8")
        ).hexdigest()

    def test_filename_is_reduced_to_a_basename(self, attachments_dir):
        ticket = _upload_store.create_ticket(filename="../../etc/passwd")

        assert ticket["filename"] == "passwd"
        assert ".." not in ticket["filename"]

    def test_dotdot_filename_cannot_escape_the_attachments_dir(
        self, attachments_dir
    ):
        """``os.path.basename("..")`` is ``".."`` -- a directory, not a file.

        It falls back to the generated name, and the staged bytes stay in the
        upload's own directory, inside the tree the cleanup manager sweeps.
        """
        ticket = _upload_store.create_ticket(filename="..")

        assert ticket["filename"] == f"upload_{ticket['upload_id']}"

        record = _upload_store._read_record(ticket["upload_id"])
        staged = _upload_store.staged_path(record).resolve()
        assert staged.parent == (attachments_dir / ticket["upload_id"]).resolve()

    def test_dot_filename_does_not_land_on_the_directory_itself(
        self, attachments_dir
    ):
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
