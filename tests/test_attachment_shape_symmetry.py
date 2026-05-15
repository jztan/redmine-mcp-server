"""Cross-tool shape symmetry for attachment serialization (#118).

Before #118, ``manage_redmine_wiki_page(action='get', include_attachments=True)``
omitted ``content_url`` and ``author`` from each attachment dict,
while ``get_redmine_issue(include_attachments=True)`` returned both.
That asymmetry cost an agent a turn when handing off between the two
read paths -- "does this attachment have a URL? let me check the
other tool's response shape."

After #118, both paths route through ``_attachment_to_dict`` so the
shape is identical. These tests pin that contract.
"""

from types import SimpleNamespace

from redmine_mcp_server._serialization import _attachment_to_dict
from redmine_mcp_server.tools.issues import _attachments_to_list
from redmine_mcp_server.tools.wiki import _wiki_page_to_dict


def _make_attachment(att_id: int = 1, filename: str = "spec.pdf") -> SimpleNamespace:
    return SimpleNamespace(
        id=att_id,
        filename=filename,
        filesize=1234,
        content_type="application/pdf",
        description="A spec",
        content_url=f"https://example.com/attachments/{att_id}",
        author=SimpleNamespace(id=5, name="Alice"),
        created_on=None,
    )


_EXPECTED_KEYS = {
    "id",
    "filename",
    "filesize",
    "content_type",
    "description",
    "content_url",
    "author",
    "created_on",
}


class TestAttachmentToDictShape:
    def test_helper_returns_canonical_keys(self):
        out = _attachment_to_dict(_make_attachment())
        assert set(out.keys()) == _EXPECTED_KEYS

    def test_filename_is_verbatim(self):
        out = _attachment_to_dict(_make_attachment(filename="x.pdf"))
        assert out["filename"] == "x.pdf"
        assert not out["filename"].startswith("<insecure-content-")

    def test_description_is_wrapped(self):
        out = _attachment_to_dict(_make_attachment())
        assert out["description"].startswith("<insecure-content-")
        assert "A spec" in out["description"]

    def test_author_is_a_named_ref(self):
        out = _attachment_to_dict(_make_attachment())
        assert out["author"] == {"id": 5, "name": "Alice"}


class TestIssueAndWikiProduceSameShape:
    """The whole point of #118: round-tripping an attachment through
    either tool yields identical shapes."""

    def test_issue_attachments_have_canonical_keys(self):
        issue = SimpleNamespace(attachments=[_make_attachment()])
        result = _attachments_to_list(issue)
        assert len(result) == 1
        assert set(result[0].keys()) == _EXPECTED_KEYS

    def test_wiki_attachments_have_canonical_keys(self):
        # Pre-#118, this dict was missing `content_url` and `author`.
        # Post-#118 the wiki path routes through _attachment_to_dict
        # so it now exposes the same keys.
        wiki_page = SimpleNamespace(
            title="Home",
            text="hello",
            version=1,
            attachments=[_make_attachment()],
        )
        result = _wiki_page_to_dict(wiki_page, include_attachments=True)
        assert "attachments" in result
        assert len(result["attachments"]) == 1
        assert set(result["attachments"][0].keys()) == _EXPECTED_KEYS

    def test_identical_attachment_yields_identical_dict_modulo_nonce(self):
        # Same attachment, two paths. The dicts match key-for-key
        # everywhere except `description`, where wrap_insecure_content
        # generates a per-call nonce. Compare key sets and content
        # equality on each non-description field; assert description
        # carries the same inner payload.
        att = _make_attachment()
        issue_result = _attachments_to_list(SimpleNamespace(attachments=[att]))[0]
        wiki_result = _wiki_page_to_dict(
            SimpleNamespace(title="t", text="", version=1, attachments=[att]),
            include_attachments=True,
        )["attachments"][0]

        assert set(issue_result.keys()) == set(wiki_result.keys())
        for key in issue_result:
            if key == "description":
                # Both wrapped; both contain the same inner text.
                assert "A spec" in issue_result[key]
                assert "A spec" in wiki_result[key]
            else:
                assert (
                    issue_result[key] == wiki_result[key]
                ), f"{key} differs between issue and wiki paths"
