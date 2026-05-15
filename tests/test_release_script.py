"""Unit tests for scripts/release.py changelog parsing."""

import importlib.util
import sys
from pathlib import Path

import pytest


_RELEASE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "release.py"
_spec = importlib.util.spec_from_file_location("release_script", _RELEASE_PATH)
release_script = importlib.util.module_from_spec(_spec)
sys.modules["release_script"] = release_script
_spec.loader.exec_module(release_script)


def _write_changelog(tmp_path: Path, version: str, body: str) -> Path:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        f"# Changelog\n\n## [{version}] - 2026-05-16\n{body}\n\n"
        f"## [0.0.1] - 2025-01-01\n### Added\n- seed\n"
    )
    return changelog


@pytest.mark.parametrize(
    "separator,description",
    [
        (":", "added the foo tool ([#1](url))"),
        ("—", "added the foo tool ([#1](url))"),
        ("–", "added the foo tool ([#1](url))"),
        ("-", "added the foo tool ([#1](url))"),
    ],
)
def test_contributors_extracted_for_each_separator(tmp_path, separator, description):
    """Each separator the writing rules allow must parse into the Ack block."""
    body = (
        "### Added\n- thing\n\n"
        f"### Contributors\n- @alice {separator} {description}\n"
    )
    _write_changelog(tmp_path, "9.9.9", body)

    main_body, ack = release_script.extract_changelog_section(tmp_path, "9.9.9")

    assert "### Contributors" not in main_body
    assert "Thanks to **@alice**" in ack
    assert description in ack


def test_colon_separator_does_not_silently_drop_contributors(tmp_path):
    """Regression: v2.0.0 shipped without credits because the regex did not
    accept the colon separator the no-em-dash writing rule forces."""
    body = (
        "### Added\n- thing\n\n"
        "### Contributors\n"
        "- @mihajlovicjj: added `manage_document` tool ([#104](url))\n"
    )
    _write_changelog(tmp_path, "2.0.0", body)

    _, ack = release_script.extract_changelog_section(tmp_path, "2.0.0")

    assert ack != ""
    assert "@mihajlovicjj" in ack
    assert "manage_document" in ack


def test_multiple_authors_grouped(tmp_path):
    body = (
        "### Added\n- thing\n\n"
        "### Contributors\n"
        "- @alice: first contribution ([#1](url))\n"
        "- @bob: second contribution ([#2](url))\n"
        "- @alice: third contribution ([#3](url))\n"
    )
    _write_changelog(tmp_path, "1.0.0", body)

    _, ack = release_script.extract_changelog_section(tmp_path, "1.0.0")

    assert ack.count("Thanks to **@alice**") == 1
    assert ack.count("Thanks to **@bob**") == 1
    assert "first contribution" in ack
    assert "third contribution" in ack


def test_no_contributors_section_returns_empty_ack(tmp_path):
    body = "### Added\n- thing\n"
    _write_changelog(tmp_path, "1.0.0", body)

    main_body, ack = release_script.extract_changelog_section(tmp_path, "1.0.0")

    assert ack == ""
    assert "thing" in main_body
