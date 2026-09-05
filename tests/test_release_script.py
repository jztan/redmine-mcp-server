"""Unit tests for scripts/release.py changelog parsing."""

import importlib.util
import subprocess
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
        f"## [0.0.1] - 2025-01-01\n### Added\n- seed\n",
        encoding="utf-8",
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


CHANGELOG_WITH_CREDITS = """# Changelog

## [Unreleased]
### Contributors
- @newest — reported a bug ([#99](https://example.com/99))

## [1.1.0] - 2020-02-01
### Fixed
- Something. Thanks @not-a-credit for the idea.

### Contributors
- @second, sent a PR ([#2](https://example.com/2))
- @first — diagnosed and fixed the failure ([#1](https://example.com/1))

## [1.0.0] - 2020-01-01
### Contributors
- @first — reported it first ([#0](https://example.com/0))
"""

README_WITH_MARKERS = """# Project

## Contributors

Thanks:

<!-- contributors:start -->
[@stale](https://github.com/stale)
<!-- contributors:end -->

## License
"""


def _write_contributor_fixtures(tmp_path: Path) -> None:
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG_WITH_CREDITS, encoding="utf-8")
    (tmp_path / "README.md").write_text(README_WITH_MARKERS, encoding="utf-8")


def test_readme_contributors_lists_every_changelog_credit(tmp_path):
    """Every handle credited in a `### Contributors` block belongs in the
    README list, whatever form the contribution took. Hand-maintaining it
    drifted: the list shipped for months missing six credited people."""
    _write_contributor_fixtures(tmp_path)

    release_script.update_readme_contributors(tmp_path, dry_run=False)

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "[@first](https://github.com/first)" in readme
    # Both credit punctuations in this changelog are recognised: "@x —" and "@x,".
    assert "[@second](https://github.com/second)" in readme
    assert "[@newest](https://github.com/newest)" in readme
    assert "not-a-credit" not in readme
    assert "@stale" not in readme
    assert "## License" in readme


def test_readme_contributors_are_oldest_first_and_deduped():
    """@first is credited in two releases: listed once, at the position of the
    earliest credit, so a new name never reshuffles the line."""
    assert release_script.collect_changelog_contributors(CHANGELOG_WITH_CREDITS) == [
        "first",
        "second",
        "newest",
    ]


def test_readme_contributors_keeps_hyphenated_handles_whole():
    """@stevehollis-orderflow is a real credit here; a handle regex that stops
    at the hyphen would link a non-existent account."""
    changelog = "## [1.0.0]\n### Contributors\n- @a-b-c — did a thing\n"
    assert release_script.collect_changelog_contributors(changelog) == ["a-b-c"]


def test_readme_contributors_dry_run_writes_nothing(tmp_path):
    _write_contributor_fixtures(tmp_path)

    release_script.update_readme_contributors(tmp_path, dry_run=True)

    assert (tmp_path / "README.md").read_text(encoding="utf-8") == README_WITH_MARKERS


def test_readme_contributors_fails_loudly_when_markers_go_missing(tmp_path):
    """If the section is reformatted away, the release must raise rather than
    silently stop crediting people."""
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG_WITH_CREDITS, encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "# Project\n\n## Contributors\n", encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="contributors:start"):
        release_script.update_readme_contributors(tmp_path, dry_run=False)


def test_version_bump_stages_the_readme():
    """README must be staged, or the regenerated line never reaches the
    release commit."""
    import inspect

    source = inspect.getsource(release_script.commit_version_bump)
    assert '"README.md"' in source


def test_committed_readme_contributors_match_the_changelog():
    """Guards the checked-in files: a credit added to the CHANGELOG without a
    release cut would otherwise sit unlisted until the next bump."""
    repo = Path(__file__).resolve().parent.parent
    expected = release_script.render_contributors_line(
        release_script.collect_changelog_contributors(
            (repo / "CHANGELOG.md").read_text(encoding="utf-8")
        )
    )
    assert expected in (repo / "README.md").read_text(encoding="utf-8"), (
        "README Contributors list is stale. Run:\n"
        "    python scripts/release.py --sync-contributors"
    )


def test_sync_contributors_flag_is_wired_up():
    """The remedy the failure above points at has to actually work, and it
    must not touch the tree when previewed."""
    repo = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "scripts/release.py", "--sync-contributors", "--dry-run"],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "[DRY-RUN] Would sync README.md Contributors list" in result.stdout


def test_sync_contributors_refuses_to_ride_along_with_a_release():
    repo = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "scripts/release.py", "patch", "--sync-contributors"],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "cannot be combined with a release run" in result.stderr


def test_no_separator_after_handle_is_credited(tmp_path):
    """Regression: v2.14.0 shipped with no Contributors block at all because
    the prose style writes the handle with no separator following it."""
    body = (
        "### Added\n- thing\n\n"
        "### Contributors\n"
        "- @andilem proposed and implemented the tool allow list ([#255](url))\n"
    )
    _write_changelog(tmp_path, "2.14.0", body)

    _, ack = release_script.extract_changelog_section(tmp_path, "2.14.0")

    assert "@andilem" in ack
    assert "proposed and implemented the tool allow list" in ack


def test_contributor_without_at_handle_is_credited(tmp_path):
    """An organisation credited by name has no @handle; v2.13.0 dropped
    RedmineUP for that reason."""
    body = (
        "### Added\n- thing\n\n"
        "### Contributors\n"
        "- RedmineUP, provided an evaluation copy of the CRM PRO plugin\n"
    )
    _write_changelog(tmp_path, "2.13.0", body)

    _, ack = release_script.extract_changelog_section(tmp_path, "2.13.0")

    assert "RedmineUP" in ack
    assert "evaluation copy" in ack


def test_wrapped_entry_keeps_its_continuation_lines(tmp_path):
    """Every shipped release truncated entries at the first line, losing the
    PR links the credit format requires."""
    body = (
        "### Added\n- thing\n\n"
        "### Contributors\n"
        "- @alice: requested MCP tool annotations so clients can distinguish\n"
        "  read-only calls from writes\n"
        "  ([#221](https://example.invalid/221))\n"
    )
    _write_changelog(tmp_path, "1.0.0", body)

    _, ack = release_script.extract_changelog_section(tmp_path, "1.0.0")

    assert "read-only calls from writes" in ack
    assert "[#221](https://example.invalid/221)" in ack


def test_unparsable_contributors_section_raises(tmp_path):
    """Credits must never be dropped silently. If the section exists but no
    entry parses, the release stops instead of publishing without credit."""
    body = "### Added\n- thing\n\n### Contributors\nnot a list item at all\n"
    _write_changelog(tmp_path, "1.0.0", body)

    with pytest.raises(ValueError, match="Contributors"):
        release_script.extract_changelog_section(tmp_path, "1.0.0")
