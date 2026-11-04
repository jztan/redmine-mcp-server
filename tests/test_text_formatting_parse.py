"""Reading Redmine's text formatting from an issue page (#440).

The fixtures are hand-written minimal pages modelled on what each Redmine
generation emits, not pages captured from a real server.
"""

from pathlib import Path

import pytest

from redmine_mcp_server._text_formatting import (
    FORMATS,
    FORMATTED_TEXT_TOOLS,
    SERVER_INSTRUCTIONS,
    TEXT_BLOCKS,
    parse_format_from_html,
)

FIXTURES = Path(__file__).parent / "fixtures" / "text_formatting"


@pytest.mark.parametrize(
    "fixture,expected",
    [
        ("textile_7x.html", "textile"),
        ("common_mark_6x.html", "common_mark"),
        ("markdown_4x.html", "markdown"),
        ("textile_34.html", "textile"),
        ("textile_26.html", "textile"),
        ("no_toolbar.html", None),
        ("login.html", None),
    ],
)
def test_parse_fixture(fixture, expected):
    html = (FIXTURES / fixture).read_text()
    assert parse_format_from_html(html) == expected


def test_data_attribute_beats_script():
    html = (
        '<script src="/assets/jstoolbar/textile-1.js"></script>'
        '<textarea data-list-autofill-text-formatting-param="common_mark"></textarea>'
    )
    assert parse_format_from_html(html) == "common_mark"


def test_marker_in_body_text_is_ignored():
    html = (
        '<html><body><div class="wiki">see jstoolbar/textile.js and '
        "wiki_syntax_markdown.html and setHelpLink(&#39;x&#39;)</div></body></html>"
    )
    assert parse_format_from_html(html) is None


def test_unknown_data_attribute_value_falls_through():
    html = (
        '<textarea data-list-autofill-text-formatting-param="bogus"></textarea>'
        '<script src="/assets/jstoolbar/common_mark-1.js"></script>'
    )
    assert parse_format_from_html(html) == "common_mark"


def test_blocks_cover_every_result():
    assert set(TEXT_BLOCKS) == set(FORMATS) | {"unknown"}
    assert "1. item" in TEXT_BLOCKS["markdown"]
    assert "1. item" in TEXT_BLOCKS["common_mark"]
    assert "# item" in TEXT_BLOCKS["textile"]
    assert TEXT_BLOCKS["markdown"].startswith("Text formatting on this Redmine: Markdown.")
    assert TEXT_BLOCKS["common_mark"].startswith(
        "Text formatting on this Redmine: CommonMark Markdown."
    )
    assert "could not be determined" in TEXT_BLOCKS["unknown"]
    assert "plain text" in TEXT_BLOCKS["none"]


def test_server_instructions_mention_tool_descriptions():
    assert "description" in SERVER_INSTRUCTIONS


async def test_formatted_tools_are_registered(all_plugin_tools_visible):
    from redmine_mcp_server import server as _server
    from redmine_mcp_server import tools  # noqa: F401

    registered = {t.name for t in await _server.mcp.list_tools()}
    assert FORMATTED_TEXT_TOOLS <= registered, FORMATTED_TEXT_TOOLS - registered
