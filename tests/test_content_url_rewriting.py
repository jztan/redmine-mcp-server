"""Tests for the content_url public-host rewriter (#110).

Redmine echoes back URLs that point at its own configured hostname.
In containerized deployments that hostname is usually the internal
service name (``http://redmine:3000/...``), which is unreachable from
MCP clients on the host or the open internet. The serializer-layer
helper ``_rewrite_to_public_url`` rewrites these to use
``REDMINE_PUBLIC_URL`` when configured, while leaving URLs that don't
match the internal origin (foreign CDN links, pre-rewritten values)
untouched.
"""

import pytest

from redmine_mcp_server._serialization import _rewrite_to_public_url


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("REDMINE_URL", "http://redmine:3000")
    monkeypatch.setenv("REDMINE_PUBLIC_URL", "https://redmine.example.com")


class TestRewriteToPublicUrl:
    def test_rewrites_internal_origin_to_public(self, configured):
        url = "http://redmine:3000/attachments/download/3/spec.pdf"
        out = _rewrite_to_public_url(url)
        assert out == "https://redmine.example.com/attachments/download/3/spec.pdf"

    def test_preserves_path_query_and_fragment(self, configured):
        url = "http://redmine:3000/attachments/3?token=abc#section-2"
        out = _rewrite_to_public_url(url)
        assert out == ("https://redmine.example.com/attachments/3?token=abc#section-2")

    def test_unset_public_url_leaves_input_untouched(self, monkeypatch):
        # When operators have not configured a public URL, the safer
        # default is to surface the raw internal URL so the caller is
        # at least aware of what Redmine returned. The companion
        # workaround is to use get_redmine_attachment for downloads.
        monkeypatch.setenv("REDMINE_URL", "http://redmine:3000")
        monkeypatch.delenv("REDMINE_PUBLIC_URL", raising=False)
        url = "http://redmine:3000/attachments/download/3"
        assert _rewrite_to_public_url(url) == url

    def test_unset_redmine_url_leaves_input_untouched(self, monkeypatch):
        monkeypatch.delenv("REDMINE_URL", raising=False)
        monkeypatch.setenv("REDMINE_PUBLIC_URL", "https://redmine.example.com")
        url = "http://redmine:3000/attachments/3"
        assert _rewrite_to_public_url(url) == url

    def test_foreign_origin_left_untouched(self, configured):
        # URLs whose scheme+host do not match the internal Redmine
        # origin must NOT be rewritten -- they might be a CDN-hosted
        # asset, a workaround-pre-rewritten value, or any other foreign
        # URL the operator wants to surface verbatim.
        external = "https://cdn.example.org/files/3.pdf"
        assert _rewrite_to_public_url(external) == external

        # Different scheme is treated as a different origin.
        plain_http = "http://redmine.example.com/attachments/3"
        assert _rewrite_to_public_url(plain_http) == plain_http

    def test_empty_and_non_string_inputs_pass_through(self, configured):
        assert _rewrite_to_public_url("") == ""
        assert _rewrite_to_public_url(None) is None
        assert _rewrite_to_public_url(123) == 123

    def test_port_difference_treated_as_foreign_origin(self, configured):
        # Internal is :3000; a URL on :8080 should not match.
        url = "http://redmine:8080/attachments/3"
        assert _rewrite_to_public_url(url) == url

    def test_no_double_rewrite(self, configured):
        # Calling twice must be a no-op on the second pass -- the
        # second URL no longer matches the internal origin.
        url = "http://redmine:3000/attachments/3"
        first = _rewrite_to_public_url(url)
        second = _rewrite_to_public_url(first)
        assert first == second == ("https://redmine.example.com/attachments/3")


class TestSerializersUseRewriter:
    """End-to-end: the user-visible serializers must route through
    the helper so a future caller that copies the pattern can't
    forget to rewrite (the bug class this issue closes).
    """

    def test_file_to_dict_rewrites_content_url(self, configured):
        from types import SimpleNamespace

        from redmine_mcp_server.tools.files import _file_to_dict

        f = SimpleNamespace(
            id=1,
            filename="x.pdf",
            filesize=10,
            content_type="application/pdf",
            description="",
            content_url="http://redmine:3000/attachments/download/1/x.pdf",
            digest="",
            downloads=0,
            author=None,
            version=None,
            created_on=None,
        )
        out = _file_to_dict(f)
        assert out["content_url"] == (
            "https://redmine.example.com/attachments/download/1/x.pdf"
        )

    def test_attachments_to_list_rewrites_content_url(self, configured):
        from types import SimpleNamespace

        from redmine_mcp_server.tools.issues import _attachments_to_list

        att = SimpleNamespace(
            id=3,
            filename="spec.csv",
            filesize=1010,
            content_type="text/csv",
            description="",
            content_url="http://redmine:3000/attachments/download/3/spec.csv",
            author=None,
            created_on=None,
        )
        issue = SimpleNamespace(attachments=[att])

        result = _attachments_to_list(issue)
        assert result[0]["content_url"] == (
            "https://redmine.example.com/attachments/download/3/spec.csv"
        )
