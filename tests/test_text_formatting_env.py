"""REDMINE_TEXT_FORMATTING accessor (#440)."""

import pytest

from redmine_mcp_server._env import get_text_formatting


def test_default_is_auto(monkeypatch):
    monkeypatch.delenv("REDMINE_TEXT_FORMATTING", raising=False)
    assert get_text_formatting() == "auto"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("textile", "textile"),
        ("markdown", "markdown"),
        ("common_mark", "common_mark"),
        ("none", "none"),
        ("auto", "auto"),
        ("  Markdown ", "markdown"),
        ("", "auto"),
    ],
)
def test_valid_values(monkeypatch, raw, expected):
    monkeypatch.setenv("REDMINE_TEXT_FORMATTING", raw)
    assert get_text_formatting() == expected


def test_invalid_value_raises(monkeypatch):
    monkeypatch.setenv("REDMINE_TEXT_FORMATTING", "commonmark")
    with pytest.raises(RuntimeError, match="REDMINE_TEXT_FORMATTING"):
        get_text_formatting()
