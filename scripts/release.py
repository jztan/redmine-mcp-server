#!/usr/bin/env python3
"""
Release automation script for redmine-mcp-server using gitflow.

Usage:
    python scripts/release.py [patch|minor|major] [--dry-run]

Examples:
    python scripts/release.py patch           # 0.12.1 -> 0.12.2
    python scripts/release.py minor           # 0.12.1 -> 0.13.0
    python scripts/release.py major           # 0.12.1 -> 1.0.0
    python scripts/release.py patch --dry-run # Preview changes

Gitflow:
    1. Start from develop branch
    2. Pre-flight: clean tree, tests pass, dependency audit clean
    3. Create release/vX.Y.Z branch and bump versions
    4. Merge to master, push tag (triggers publish-pypi.yml)
    5. Wait for publish-pypi workflow to finish (poll gh run status)
    6. Wait for the version to appear on PyPI (JSON API)
    7. Create GitHub release (only after `pip install` will actually work)
    8. Publish to MCP Registry
    9. Merge back to develop, delete release branch
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PACKAGE_NAME = "redmine-mcp-server"
GITHUB_REPO = "jztan/redmine-mcp-server"


@dataclass
class ReleaseConfig:
    """Configuration for release automation."""

    bump_type: str
    dry_run: bool
    project_root: Path
    hotfix: bool = False


def run_command(
    cmd: list[str],
    *,
    check: bool = True,
    capture_output: bool = True,
    dry_run: bool = False,
    dry_run_msg: str | None = None,
    env: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a shell command with optional dry-run support."""
    if dry_run and dry_run_msg:
        print(f"  [DRY-RUN] Would run: {' '.join(cmd)}")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    result = subprocess.run(
        cmd, capture_output=capture_output, text=True, check=False, env=env
    )
    if check and result.returncode != 0:
        print(f"Error running command: {' '.join(cmd)}")
        print(f"  stdout: {result.stdout}")
        print(f"  stderr: {result.stderr}")
        sys.exit(1)
    return result


def get_current_version(project_root: Path) -> str:
    """Read current version from pyproject.toml."""
    pyproject = project_root / "pyproject.toml"
    content = pyproject.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        print("Error: Could not find version in pyproject.toml")
        sys.exit(1)
    return match.group(1)


def calculate_new_version(current: str, bump_type: str) -> str:
    """Calculate new version based on bump type."""
    parts = current.split(".")
    if len(parts) != 3:
        print(f"Error: Invalid version format: {current}")
        sys.exit(1)

    major, minor, patch = map(int, parts)

    if bump_type == "major":
        return f"{major + 1}.0.0"
    if bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    # patch
    return f"{major}.{minor}.{patch + 1}"


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def preflight_checks(config: ReleaseConfig) -> None:
    """Verify prerequisites for release."""
    print("\n=== Pre-flight Checks ===\n")

    # Check git status is clean
    print("Checking git status...")
    result = run_command(["git", "status", "--porcelain"])
    if result.stdout.strip():
        print("Error: Working directory is not clean. Please commit or stash changes.")
        print(result.stdout)
        sys.exit(1)
    print("  ✓ Working directory is clean")

    # Check we're on the correct branch
    print("Checking current branch...")
    result = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    branch = result.stdout.strip()

    if config.hotfix:
        if not branch.startswith("hotfix/"):
            print(
                f"Error: --hotfix requires a hotfix/* branch, "
                f"currently on '{branch}'"
            )
            sys.exit(1)
        print(f"  ✓ On hotfix branch: {branch}")

        # Pull latest master
        print("Pulling latest changes from master...")
        run_command(["git", "pull", "origin", "master"])
        print("  ✓ Up to date with origin/master")
    else:
        if branch != "develop":
            print(
                f"Error: Must be on 'develop' branch to start release, "
                f"currently on '{branch}'"
            )
            sys.exit(1)
        print("  ✓ On develop branch")

        # Pull latest changes
        print("Pulling latest changes...")
        run_command(["git", "pull", "origin", "develop"])
        print("  ✓ Up to date with origin/develop")

    # Check code formatting
    print("Checking code formatting...")
    result = run_command(
        ["uv", "run", "black", "--check", "src/"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        print("Error: Code formatting check failed. Run: uv run black src/")
        print(result.stdout)
        sys.exit(1)
    print("  ✓ Code formatting OK")

    # Check linting
    print("Checking linting...")
    result = run_command(
        ["uv", "run", "flake8", "src/", "--max-line-length=88"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        print("Error: Linting failed. Run: uv run flake8 src/ --max-line-length=88")
        print(result.stdout)
        sys.exit(1)
    print("  ✓ Linting OK")

    # Check tests pass
    print("Running tests...")
    result = run_command(
        ["python", "tests/run_tests.py", "--all"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        print("Error: Tests failed. Please fix before releasing.")
        print(result.stdout)
        print(result.stderr)
        sys.exit(1)
    print("  ✓ All tests pass")

    # Dependency audit -- same script CI runs (dependency-audit.yml and the
    # publish-pypi.yml pre-test step both call scripts/audit.sh). A green
    # preflight means a green publish-pypi audit step, so we catch the
    # failure mode where pip-audit blocks the release after the tag has
    # already been pushed.
    print("Auditing dependencies...")
    audit_script = config.project_root / "scripts" / "audit.sh"
    requirements_path = "/tmp/requirements-audit.txt"
    export_result = run_command(
        ["uv", "export", "--no-hashes", "--no-emit-project"],
        check=False,
        capture_output=True,
    )
    if export_result.returncode != 0:
        print("Error: uv export failed; cannot run dependency audit.")
        print(export_result.stdout)
        print(export_result.stderr)
        sys.exit(1)
    Path(requirements_path).write_text(export_result.stdout)
    result = run_command(
        ["bash", str(audit_script), "-r", requirements_path, "--strict"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        print(
            "Error: Dependency audit failed. "
            "Fix or update the ignore list in scripts/audit.sh before releasing."
        )
        print(result.stdout)
        print(result.stderr)
        sys.exit(1)
    print("  ✓ No vulnerabilities (or all are in the ignore list)")

    # Check gh CLI is available and authenticated
    print("Checking gh CLI...")
    result = run_command(["which", "gh"], check=False)
    if result.returncode != 0:
        print("Error: 'gh' CLI not found. Install with: brew install gh")
        sys.exit(1)
    result = run_command(["gh", "auth", "status"], check=False, capture_output=True)
    if result.returncode != 0:
        print("  ⚠ gh CLI not authenticated. Starting login...")
        login_result = subprocess.run(["gh", "auth", "login"], check=False)
        if login_result.returncode != 0:
            print("Error: gh authentication failed")
            sys.exit(1)
    print("  ✓ gh CLI available and authenticated")

    # Check mcp-publisher is available
    print("Checking mcp-publisher...")
    result = run_command(["which", "mcp-publisher"], check=False)
    if result.returncode != 0:
        print(
            "Warning: 'mcp-publisher' not found. "
            "MCP Registry publish will be skipped."
        )
        print("         Install with: brew install mcp-publisher")
    else:
        result = run_command(
            ["mcp-publisher", "validate"],
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            print("  ⚠ mcp-publisher not authenticated. Starting login...")
            login_result = subprocess.run(
                ["mcp-publisher", "login", "github"], check=False
            )
            if login_result.returncode != 0:
                print("Warning: mcp-publisher authentication failed.")
                print("         MCP Registry publish may be skipped.")
            else:
                print("  ✓ mcp-publisher authenticated")
        else:
            print("  ✓ mcp-publisher available")


# ---------------------------------------------------------------------------
# Version bump helpers
# ---------------------------------------------------------------------------


def update_pyproject_toml(project_root: Path, new_version: str, dry_run: bool) -> None:
    """Update version in pyproject.toml."""
    pyproject = project_root / "pyproject.toml"
    content = pyproject.read_text()
    new_content = re.sub(
        r'^(version\s*=\s*)"[^"]+"',
        f'\\1"{new_version}"',
        content,
        flags=re.MULTILINE,
    )

    if dry_run:
        print(f"  [DRY-RUN] Would update pyproject.toml version to {new_version}")
    else:
        pyproject.write_text(new_content)
        print("  ✓ Updated pyproject.toml")


def update_server_json(project_root: Path, new_version: str, dry_run: bool) -> None:
    """Update version in server.json (both occurrences)."""
    server_json = project_root / "server.json"
    content = json.loads(server_json.read_text())

    content["version"] = new_version
    if "packages" in content and len(content["packages"]) > 0:
        content["packages"][0]["version"] = new_version

    if dry_run:
        print(f"  [DRY-RUN] Would update server.json version to {new_version}")
    else:
        server_json.write_text(json.dumps(content, indent=2) + "\n")
        print("  ✓ Updated server.json")


def update_changelog(project_root: Path, new_version: str, dry_run: bool) -> None:
    """Update CHANGELOG.md: convert [Unreleased] to new version with date.

    Requires an [Unreleased] section with real content. Auto-stamping a
    "Version bump" placeholder produces vacuous GitHub release notes; fail
    loud instead so the user fills it in before the release goes out.
    """
    changelog = project_root / "CHANGELOG.md"
    content = changelog.read_text()
    today = date.today().strftime("%Y-%m-%d")

    # Require an [Unreleased] section that exists and has real content.
    unreleased_body_pattern = r"## \[Unreleased\]\s*\n(.*?)(?=^## \[|\Z)"
    body_match = re.search(
        unreleased_body_pattern, content, re.IGNORECASE | re.DOTALL | re.MULTILINE
    )
    if not body_match:
        print(
            "Error: CHANGELOG.md has no [Unreleased] section.\n"
            "Add one with the changes for this release before running the script."
        )
        sys.exit(1)

    unreleased_body = body_match.group(1).strip()
    if not unreleased_body or unreleased_body in (
        "### Changed",
        "### Added",
        "### Fixed",
        "### Security",
    ):
        print(
            "Error: [Unreleased] section in CHANGELOG.md is empty.\n"
            "Document the changes for this release before running the script."
        )
        sys.exit(1)

    # Replace [Unreleased] with new version, add fresh [Unreleased] above.
    new_content = re.sub(
        r"## \[Unreleased\]\s*\n",
        f"## [Unreleased]\n\n## [{new_version}] - {today}\n",
        content,
        count=1,
        flags=re.IGNORECASE,
    )

    # Append reference link at the bottom if not already present
    ref_link = (
        f"[{new_version}]: "
        f"https://github.com/{GITHUB_REPO}/releases/tag/v{new_version}"
    )
    if ref_link not in new_content:
        # Insert before the first existing reference link line
        first_ref_match = re.search(r"^\[[\d.]+\]: https://", new_content, re.MULTILINE)
        if first_ref_match:
            insert_pos = first_ref_match.start()
            new_content = (
                new_content[:insert_pos] + ref_link + "\n" + new_content[insert_pos:]
            )
        else:
            new_content = new_content.rstrip() + "\n" + ref_link + "\n"

    if dry_run:
        print(f"  [DRY-RUN] Would update CHANGELOG.md with version {new_version}")
    else:
        changelog.write_text(new_content)
        print("  ✓ Updated CHANGELOG.md")


def update_uv_lock(project_root: Path, dry_run: bool) -> None:
    """Run uv lock to update uv.lock with the new version."""
    if dry_run:
        print("  [DRY-RUN] Would run: uv lock")
    else:
        subprocess.run(
            ["uv", "lock"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )
        print("  ✓ Updated uv.lock")


def extract_changelog_section(project_root: Path, version: str) -> str:
    """Extract the changelog section for a specific version.

    Returns a tuple-like pair: (main_body, acknowledgements).
    The Contributors subsection is split out and reformatted as an
    Acknowledgements block that matches the existing release style.
    """
    changelog = project_root / "CHANGELOG.md"
    content = changelog.read_text()

    pattern = rf"## \[{re.escape(version)}\][^\n]*\n(.*?)(?=\n## \[|\Z)"
    match = re.search(pattern, content, re.DOTALL)

    if not match:
        return "Release " + version, ""

    section = match.group(1).strip()

    # Split out ### Contributors into a separate acknowledgements block
    contrib_pattern = r"### Contributors\s*\n(.*?)(?=\n###\s|\Z)"
    contrib_match = re.search(contrib_pattern, section, re.DOTALL)

    if not contrib_match:
        return section, ""

    # Remove ### Contributors from main body
    body = re.sub(
        r"\n*### Contributors\s*\n.*?(?=\n###\s|\Z)",
        "",
        section,
        flags=re.DOTALL,
    ).strip()

    # Build acknowledgements: group contributions by author
    contrib_text = contrib_match.group(1).strip()
    authors: dict[str, list[str]] = {}
    for line in contrib_text.split("\n"):
        line = line.strip()
        if not line.startswith("- "):
            continue
        # Format: "- @username: description ([#PR](url))"
        # Accept colon (current style, per the no-em-dash writing rule), as well
        # as em dash / en dash / hyphen for older CHANGELOG entries.
        author_match = re.match(r"-\s+(@\S+)\s*[—–\-:]\s*(.*)", line)
        if author_match:
            author = author_match.group(1)
            desc = author_match.group(2).strip()
            authors.setdefault(author, []).append(desc)

    if not authors:
        return body, ""

    ack_lines = []
    for author, contribs in authors.items():
        ack_lines.append(f"Thanks to **{author}** for contributing:")
        for c in contribs:
            ack_lines.append(f"- {c}")
        ack_lines.append("")

    return body, "\n".join(ack_lines).strip()


# ---------------------------------------------------------------------------
# Release workflow steps
# ---------------------------------------------------------------------------


def create_release_branch(new_version: str, dry_run: bool) -> str:
    """Create release branch from develop."""
    print("\n=== Create Release Branch ===\n")

    branch_name = f"release/v{new_version}"

    if dry_run:
        print(f"  [DRY-RUN] Would create branch: {branch_name}")
    else:
        run_command(["git", "checkout", "-b", branch_name])
        print(f"  ✓ Created and switched to: {branch_name}")

    return branch_name


def bump_version(config: ReleaseConfig) -> tuple[str, str]:
    """Update version in all files."""
    print("\n=== Version Bump ===\n")

    current_version = get_current_version(config.project_root)
    new_version = calculate_new_version(current_version, config.bump_type)

    print(f"Version: {current_version} -> {new_version}")
    print()

    update_pyproject_toml(config.project_root, new_version, config.dry_run)
    update_server_json(config.project_root, new_version, config.dry_run)
    update_changelog(config.project_root, new_version, config.dry_run)
    update_uv_lock(config.project_root, config.dry_run)

    return current_version, new_version


def commit_version_bump(config: ReleaseConfig, new_version: str) -> None:
    """Commit version bump changes on release branch."""
    print("\n=== Commit Version Bump ===\n")

    files = ["pyproject.toml", "server.json", "CHANGELOG.md", "uv.lock"]
    for f in files:
        run_command(
            ["git", "add", f],
            dry_run=config.dry_run,
            dry_run_msg=f"git add {f}",
        )
    if config.dry_run:
        print(f"  [DRY-RUN] Would stage: {', '.join(files)}")
    else:
        print("  ✓ Staged changes")

    commit_msg = f"chore: bump version to v{new_version}"
    run_command(
        ["git", "commit", "-m", commit_msg],
        dry_run=config.dry_run,
        dry_run_msg=f"git commit -m '{commit_msg}'",
        env={**os.environ, "PRE_COMMIT_ALLOW_NO_CONFIG": "1"},
    )
    if config.dry_run:
        print(f"  [DRY-RUN] Would commit: {commit_msg}")
    else:
        print("  ✓ Committed changes")


def merge_to_master_and_tag(
    config: ReleaseConfig, new_version: str, release_branch: str
) -> None:
    """Merge release branch to master and create tag."""
    print("\n=== Merge to Master & Tag ===\n")

    tag = f"v{new_version}"

    if config.dry_run:
        print("  [DRY-RUN] Would checkout master")
        print(f"  [DRY-RUN] Would merge {release_branch} into master")
        print(f"  [DRY-RUN] Would create tag: {tag}")
        print("  [DRY-RUN] Would push master with tags")
    else:
        run_command(["git", "checkout", "master"])
        run_command(["git", "pull", "origin", "master"])
        print("  ✓ Checked out master")

        run_command(["git", "merge", release_branch, "--no-edit"])
        print(f"  ✓ Merged {release_branch}")

        run_command(["git", "tag", "-a", tag, "-m", f"Release {tag}"])
        print(f"  ✓ Created tag: {tag}")

        # Push master with tags (triggers PyPI workflow)
        run_command(["git", "push", "origin", "master", "--tags"])
        print("  ✓ Pushed master with tags")


def create_github_release(config: ReleaseConfig, new_version: str) -> None:
    """Create GitHub release with changelog notes."""
    print("\n=== GitHub Release ===\n")

    tag = f"v{new_version}"
    body, acknowledgements = extract_changelog_section(config.project_root, new_version)

    ack_block = (
        f"\n\n## Acknowledgements\n\n{acknowledgements}" if acknowledgements else ""
    )

    notes = f"""## What's New in {tag}

{body}{ack_block}

## Installation

```bash
pip install {PACKAGE_NAME}=={new_version}
```

## Links
- [PyPI Package](https://pypi.org/project/{PACKAGE_NAME}/{new_version}/)
- [MCP Registry](https://registry.modelcontextprotocol.io/v0/servers?search=redmine)
- [Full Changelog](https://github.com/{GITHUB_REPO}/blob/master/CHANGELOG.md)
"""

    if config.dry_run:
        print(f"  [DRY-RUN] Would create GitHub release: {tag}")
        print("  [DRY-RUN] Release notes preview:")
        for line in notes.split("\n")[:10]:
            print(f"    {line}")
        print("    ...")
    else:
        run_command(
            ["gh", "release", "create", tag, "--title", tag, "--notes", notes],
        )
        print(f"  ✓ Created GitHub release: {tag}")


def wait_for_publish_workflow(new_version: str, max_wait: int = 900) -> bool:
    """Poll the publish-pypi.yml run triggered by the tag push.

    Returns True only if the workflow run on the tag's SHA completes with
    conclusion=success. Returns False on any other terminal conclusion or
    on timeout. Prints the run URL so a failure is easy to investigate.
    """
    tag = f"v{new_version}"
    print("\n=== Publish Workflow ===\n")

    # CRITICAL: annotated tags (git tag -a) have their own object SHA;
    # GitHub Actions reports the commit SHA in headSha. Dereference with
    # ^{commit} so the match works. Comparing the raw tag SHA never
    # matches and the poller spins forever.
    sha_result = run_command(["git", "rev-parse", f"{tag}^{{commit}}"])
    tag_sha = sha_result.stdout.strip()
    print(f"  Watching publish-pypi.yml for tag {tag} ({tag_sha[:7]})...")

    start_time = time.time()
    check_interval = 15
    last_status: str | None = None

    while time.time() - start_time < max_wait:
        elapsed = int(time.time() - start_time)
        result = run_command(
            [
                "gh",
                "run",
                "list",
                "--workflow=publish-pypi.yml",
                "--limit",
                "10",
                "--json",
                "databaseId,status,conclusion,headSha,url",
            ],
            check=False,
        )
        if result.returncode != 0:
            print(f"  ⚠ gh run list failed: {result.stderr.strip()}; retrying...")
            time.sleep(check_interval)
            continue

        try:
            runs = json.loads(result.stdout)
        except json.JSONDecodeError:
            time.sleep(check_interval)
            continue

        match = next((r for r in runs if r.get("headSha") == tag_sha), None)
        if match is None:
            print(f"  Run not yet registered... ({elapsed}s elapsed)")
            time.sleep(10)
            continue

        status = match.get("status")
        conclusion = match.get("conclusion")
        url = match.get("url", "")
        run_id = match.get("databaseId")

        if status == "completed":
            if conclusion == "success":
                print(f"  ✓ publish-pypi run succeeded ({url})")
                return True
            print(f"  ✗ publish-pypi run finished with conclusion={conclusion}")
            print(f"    URL: {url}")
            print(f"    Logs: gh run view {run_id} --log-failed")
            return False

        if status != last_status:
            print(f"  Run {run_id} status={status}... ({elapsed}s elapsed)")
            last_status = status
        else:
            print(f"  Still {status}... ({elapsed}s elapsed)")
        time.sleep(check_interval)

    print(f"  ⚠ Timeout after {max_wait}s waiting for publish-pypi workflow")
    return False


def print_recovery_instructions(
    new_version: str, release_branch: str, hotfix: bool
) -> None:
    """Print actionable recovery steps when publish fails after tagging."""
    tag = f"v{new_version}"
    branch_kind = "hotfix" if hotfix else "release"
    print("\n" + "=" * 60)
    print(f"  RELEASE {tag} INCOMPLETE")
    print("=" * 60)
    print()
    print("  Current state:")
    print(f"    - Tag {tag} is pushed to origin")
    print(f"    - master has the version-bump commit for {tag}")
    print("    - GitHub release was NOT created")
    print("    - MCP Registry was NOT updated")
    print(
        f"    - develop is unchanged; {branch_kind} branch "
        f"{release_branch} still exists locally"
    )
    print()
    print("  Investigate:")
    print("    gh run list --workflow=publish-pypi.yml --limit 5")
    print("    gh run view <run-id> --log-failed")
    print()
    print("  After diagnosing, choose one:")
    print("    A) Fix the cause on develop, then rerun the existing tag's workflow:")
    print("         gh run rerun <run-id>")
    print("       On success, finish the remaining steps manually:")
    print(f"         gh release create {tag} --title {tag} --notes-file <notes.md>")
    print("         mcp-publisher publish")
    print(f"         git checkout develop && git merge {release_branch} && git push")
    print(f"         git branch -d {release_branch}")
    print("    B) Burn this version and ship the next patch from develop")
    print("       (requires deleting tag + reverting the master commit -- destructive,")
    print(f"        only do this if nobody has pulled {tag}).")
    print("=" * 60)


def wait_for_pypi(new_version: str, max_wait: int = 600) -> bool:
    """Wait for package to be available on PyPI.

    Checks the JSON API endpoint that the MCP Registry actually validates
    against. ``pip index versions`` can return false positives because the
    simple index updates before the JSON API does, and MCP publish would
    then fail with a not-found error.
    """
    import urllib.error
    import urllib.request

    print("\n=== Waiting for PyPI ===\n")

    url = f"https://pypi.org/pypi/{PACKAGE_NAME}/{new_version}/json"
    start_time = time.time()
    check_interval = 15

    while time.time() - start_time < max_wait:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                if resp.status == 200:
                    print(f"  ✓ Version {new_version} is available on PyPI")
                    return True
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"  Unexpected status {e.code}, retrying...")
        except urllib.error.URLError as e:
            print(f"  Network error: {e.reason}, retrying...")

        elapsed = int(time.time() - start_time)
        print(f"  Waiting for PyPI... ({elapsed}s elapsed)")
        time.sleep(check_interval)

    print("  ⚠ Timeout waiting for PyPI. Package may not be available yet.")
    return False


def publish_mcp_registry(config: ReleaseConfig) -> None:
    """Publish to MCP Registry."""
    print("\n=== MCP Registry ===\n")

    result = run_command(["which", "mcp-publisher"], check=False)
    if result.returncode != 0:
        print("  ⚠ mcp-publisher not found. Skipping MCP Registry publish.")
        print("  Install with: brew install mcp-publisher")
        return

    if config.dry_run:
        print("  [DRY-RUN] Would run: mcp-publisher publish")
    else:
        result = run_command(
            ["mcp-publisher", "publish"],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            print("  ✓ Published to MCP Registry")
        else:
            print(f"  ⚠ MCP Registry publish failed: {result.stderr}")
            print("  You may need to run 'mcp-publisher login github' first")


def merge_back_to_develop(config: ReleaseConfig, release_branch: str) -> None:
    """Merge release branch back to develop and cleanup."""
    print("\n=== Merge Back to Develop ===\n")

    if config.dry_run:
        print("  [DRY-RUN] Would checkout develop")
        print(f"  [DRY-RUN] Would merge {release_branch} into develop")
        print("  [DRY-RUN] Would push develop")
        print(f"  [DRY-RUN] Would delete branch {release_branch}")
    else:
        run_command(["git", "checkout", "develop"])
        run_command(["git", "pull", "origin", "develop"])
        print("  ✓ Checked out develop")

        result = run_command(
            ["git", "merge", release_branch, "--no-edit"],
            check=False,
        )
        if result.returncode != 0:
            print(f"\n  ✗ Merge conflict when merging {release_branch} into develop.")
            print("\n  Resolve conflicts manually:")
            print("    git status                        # see conflicting files")
            print("    # edit files to resolve")
            print("    git add <resolved-files>")
            print("    git commit                        # complete the merge")
            print(f"    git branch -d {release_branch}   # cleanup branch when done")
            sys.exit(1)
        print(f"  ✓ Merged {release_branch}")

        run_command(["git", "push", "origin", "develop"])
        print("  ✓ Pushed develop")

        # Delete release branch locally and remotely
        run_command(["git", "branch", "-d", release_branch])
        run_command(["git", "push", "origin", "--delete", release_branch], check=False)
        print(f"  ✓ Deleted branch: {release_branch}")


def _check_hotfix_version_sanity(branch: str, new_version: str) -> None:
    """Warn if hotfix branch name version doesn't match calculated bump."""
    # Extract version from branch name e.g. hotfix/v1.2.1 -> 1.2.1
    parts = branch.split("/")
    if len(parts) < 2:
        return
    branch_version = parts[-1].lstrip("v")
    if branch_version != new_version:
        print(
            f"  ⚠ Warning: branch name suggests v{branch_version} "
            f"but version bump produces v{new_version}."
        )
        print(
            "    Verify pyproject.toml is correct. "
            "Use --dry-run to inspect before proceeding."
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Main entry point for release automation."""
    parser = argparse.ArgumentParser(
        description="Release automation for redmine-mcp-server (gitflow)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/release.py patch           # 0.12.1 -> 0.12.2
  python scripts/release.py minor           # 0.12.1 -> 0.13.0
  python scripts/release.py major           # 0.12.1 -> 1.0.0
  python scripts/release.py patch --dry-run # Preview changes

Gitflow:
  develop -> release/vX.Y.Z -> master (tagged) -> merge back to develop
        """,
    )
    parser.add_argument(
        "bump_type",
        choices=["patch", "minor", "major"],
        nargs="?",
        default=None,
        help="Version bump type (required unless --hotfix is set)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without executing",
    )
    parser.add_argument(
        "--hotfix",
        action="store_true",
        help="Finish the current hotfix/* branch (patch bump implied)",
    )

    args = parser.parse_args()

    # Validate: bump_type required unless --hotfix
    if args.hotfix:
        bump_type = "patch"
    elif args.bump_type is None:
        parser.error("bump_type is required unless --hotfix is set")
    else:
        bump_type = args.bump_type

    # Determine project root (parent of scripts directory)
    project_root = Path(__file__).parent.parent.resolve()

    config = ReleaseConfig(
        bump_type=bump_type,
        dry_run=args.dry_run,
        project_root=project_root,
        hotfix=args.hotfix,
    )

    print("=" * 60)
    print("  redmine-mcp-server Release Automation (Gitflow)")
    print("=" * 60)

    if config.dry_run:
        print("\n  ⚠️  DRY-RUN MODE - No changes will be made\n")

    # Step 1: Pre-flight checks
    preflight_checks(config)

    # Step 2: Calculate new version
    current_version = get_current_version(config.project_root)
    new_version = calculate_new_version(current_version, config.bump_type)

    # Step 3: Create release branch (skipped in hotfix mode)
    if config.hotfix:
        result = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        release_branch = result.stdout.strip()
        print(f"\n=== Hotfix Branch: {release_branch} ===\n")
    else:
        release_branch = create_release_branch(new_version, config.dry_run)

    # Step 4: Bump version in files
    print("\n=== Version Bump ===\n")
    print(f"Version: {current_version} -> {new_version}")
    print()

    # Hotfix sanity check: warn if branch name doesn't match calculated version
    if config.hotfix:
        _check_hotfix_version_sanity(release_branch, new_version)
    update_pyproject_toml(config.project_root, new_version, config.dry_run)
    update_server_json(config.project_root, new_version, config.dry_run)
    update_changelog(config.project_root, new_version, config.dry_run)
    update_uv_lock(config.project_root, config.dry_run)

    # Step 5: Commit version bump on release branch
    commit_version_bump(config, new_version)

    # Step 6: Merge to master and tag (this push triggers publish-pypi.yml)
    merge_to_master_and_tag(config, new_version, release_branch)

    # Step 7: Watch the publish-pypi workflow, then wait for PyPI to expose
    # the version via its JSON API. The GitHub release is created AFTER both
    # confirm -- otherwise the release notes would ship a `pip install` line
    # that does not yet (or may never) work.
    if not config.dry_run:
        if not wait_for_publish_workflow(new_version):
            print_recovery_instructions(new_version, release_branch, config.hotfix)
            sys.exit(1)

        if not wait_for_pypi(new_version):
            print_recovery_instructions(new_version, release_branch, config.hotfix)
            sys.exit(1)
    else:
        print("\n=== Publish Workflow ===\n")
        print("  [DRY-RUN] Would poll publish-pypi.yml run to completion")
        print("\n=== Waiting for PyPI ===\n")
        print("  [DRY-RUN] Would wait for PyPI availability")

    # Step 8: Create GitHub release -- now safe to advertise the PyPI install
    create_github_release(config, new_version)

    # Step 9: Publish to MCP Registry
    if not config.dry_run:
        publish_mcp_registry(config)
    else:
        print("\n=== MCP Registry ===\n")
        print("  [DRY-RUN] Would run: mcp-publisher publish")

    # Step 10: Merge back to develop and cleanup
    merge_back_to_develop(config, release_branch)

    # Done!
    print("\n" + "=" * 60)
    if config.dry_run:
        print("  DRY-RUN COMPLETE - No changes were made")
    else:
        print(f"  RELEASE v{new_version} COMPLETE!")
        print()
        print("  Verify at:")
        pypi_url = f"https://pypi.org/project/{PACKAGE_NAME}/{new_version}/"
        print(f"    - PyPI: {pypi_url}")
        gh_url = f"https://github.com/{GITHUB_REPO}/releases/tag/v{new_version}"
        print(f"    - GitHub: {gh_url}")
        mcp_url = "https://registry.modelcontextprotocol.io/v0/servers?search=redmine"
        print(f"    - MCP Registry: {mcp_url}")
    print("=" * 60)


if __name__ == "__main__":
    main()
