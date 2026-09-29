"""Keep the GitHub Pages demo true to the real server and to stock Redmine.

The demo (pages/index.html) scripts MCP tool calls and shows their JSON.
These tests evaluate the page's fixture and script section in Node and
check it against the server's own tool signatures and serializer, plus a
few static checks on the embedded Redmine markup.
"""

import hashlib
import inspect
import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from redmine_mcp_server.tools import files, issues
from redmine_mcp_server.tools.issues import _issue_to_dict

PAGE = Path(__file__).resolve().parents[1] / "pages" / "index.html"
HTML = PAGE.read_text(encoding="utf-8")

DATA_START = "const TODAY"
DATA_END = "// ── Redmine issue-table rendering"

TOOLS = {
    "list_redmine_issues": issues.list_redmine_issues,
    "get_redmine_issue": issues.get_redmine_issue,
    "update_redmine_issue": issues.update_redmine_issue,
    "get_redmine_attachment": files.get_redmine_attachment,
}

ISSUE_KEYS = list(
    _issue_to_dict(
        SimpleNamespace(id=1, subject="s", description="d", custom_fields=[]),
        include_custom_fields=True,
    )
)
JOURNAL_KEYS = [
    "id",
    "user",
    "notes",
    "notes_sha256",
    "created_on",
    "private_notes",
    "details",
]
WRAPPED = re.compile(
    r"^<insecure-content-([0-9a-f]{16})>\n(.*)\n</insecure-content-\1>$", re.S
)
NAIVE_TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
AWARE_TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00$")
TERMINAL_TITLE = "claude — ~/work/cartly-app"


def _evaluate_demo():
    if shutil.which("node") is None:
        pytest.skip("node is needed to evaluate the demo script")
    start, end = HTML.index(DATA_START), HTML.index(DATA_END)
    js = HTML[start:end] + (
        "\nconsole.log(JSON.stringify({"
        "issues: initialIssues(),"
        "steps: SCRIPT.filter(s => s.tool).map(s => "
        "({tool: s.tool, args: s.args, result: s.result()}))}));"
    )
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def demo():
    return _evaluate_demo()


def _unwrap(value):
    match = WRAPPED.match(value)
    assert match, f"not wrapped in insecure-content tags: {value!r}"
    return match.group(2)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _issue_results(demo):
    for step in demo["steps"]:
        if step["tool"] in ("get_redmine_issue", "update_redmine_issue"):
            yield step


# ── Tool calls and JSON ──────────────────────────────────────


def test_args_match_real_signatures(demo):
    for step in demo["steps"]:
        params = inspect.signature(TOOLS[step["tool"]]).parameters
        unknown = set(step["args"]) - set(params)
        assert not unknown, f"{step['tool']} does not accept {unknown}"


def test_list_call_scopes_to_the_sprint_and_filters_overdue(demo):
    args = demo["steps"][0]["args"]
    assert demo["steps"][0]["tool"] == "list_redmine_issues"
    assert args["status_id"] == "open"
    assert args["fixed_version_id"] == 31
    assert args["filters"] == {"due_date": "<=2026-06-19"}


def test_list_result_keys_are_the_requested_fields(demo):
    step = demo["steps"][0]
    for row in step["result"]:
        assert list(row) == step["args"]["fields"]


def test_list_result_is_what_the_fixture_would_return(demo):
    expected = sorted(
        (
            i["id"]
            for i in demo["issues"]
            if i["status"]["id"] != 5
            and i["fixed_version"]["id"] == 31
            and i["due_date"] <= "2026-06-19"
        ),
    )
    got = sorted(row["id"] for row in demo["steps"][0]["result"])
    assert got == expected


def test_issue_results_have_the_real_key_order(demo):
    for step in _issue_results(demo):
        keys = list(step["result"])
        assert keys[: len(ISSUE_KEYS)] == ISSUE_KEYS, step["tool"]
        extra = keys[len(ISSUE_KEYS) :]
        if step["tool"] == "get_redmine_issue":
            assert extra == ["description_sha256", "journals", "attachments"]
        else:
            assert extra == []


def test_tracker_and_version_are_objects(demo):
    for step in _issue_results(demo):
        result = step["result"]
        assert set(result["tracker"]) == {"id", "name"}
        assert result["fixed_version"] == {"id": 31, "name": "Sprint 14"}


def test_description_digest_is_of_the_raw_text(demo):
    for step in demo["steps"]:
        if step["tool"] != "get_redmine_issue":
            continue
        raw = _unwrap(step["result"]["description"])
        assert step["result"]["description_sha256"] == _sha(raw)


def test_journals_have_the_real_shape(demo):
    for step in demo["steps"]:
        if step["tool"] != "get_redmine_issue":
            continue
        for journal in step["result"]["journals"]:
            assert list(journal) == JOURNAL_KEYS
            assert journal["notes_sha256"] == _sha(_unwrap(journal["notes"]))


def test_timestamps_use_the_server_formats(demo):
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key.endswith("_on") and value is not None:
                    assert NAIVE_TS.match(value), (key, value)
                if key == "expires_at":
                    assert AWARE_TS.match(value), (key, value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for step in demo["steps"]:
        walk(step["result"])


def test_every_fixture_issue_matches_the_page_filter(demo):
    for issue in demo["issues"]:
        assert issue["status"]["id"] != 5
        assert issue["fixed_version"] == {"id": 31, "name": "Sprint 14"}
        assert issue["tracker"]["id"] in (1, 2, 3)


# ── Embedded Redmine markup ──────────────────────────────────


def test_filters_are_a_fieldset_not_chips():
    assert "chipf" not in HTML
    assert 'class="rm-filters"' in HTML and "<fieldset" in HTML
    assert "Target version" in HTML
    assert "Add filter" in HTML
    assert "Save custom query" in HTML


def test_header_matches_stock_redmine():
    assert "» Cartly" not in HTML
    assert "My account" in HTML and "Sign out" in HTML
    assert "rm-search" in HTML
    assert "New issue" in HTML


def test_embedded_app_pins_light_scheme():
    rule = HTML[HTML.index(".rm-app {") :]
    assert "color-scheme: light" in rule[: rule.index("}")]


def test_closed_rows_are_not_struck_through():
    assert "line-through" not in HTML
    assert "prio-urgent" not in HTML


def test_close_removes_row_without_animation_path():
    body = HTML[HTML.index("function dropIssue") :]
    body = body[: body.index("\n  }\n")]
    assert "REDUCED_MOTION" in body
    assert "board = board.filter" in body


def test_reset_restores_initial_board():
    body = HTML[HTML.index("function reset()") :]
    assert "board = initialIssues()" in body[: body.index("\n  }\n")]


# ── Copy ─────────────────────────────────────────────────────


def test_no_em_dashes_in_copy():
    assert HTML.replace(TERMINAL_TITLE, "").count("—") == 0


def test_callout_claim_stays():
    assert "field-for-field" in HTML


# ── Review fixes ─────────────────────────────────────────────


def test_writes_stamp_updated_on_at_save_time(demo):
    updates = [s for s in demo["steps"] if s["tool"] == "update_redmine_issue"]
    for step in updates:
        result = step["result"]
        assert result["updated_on"] > result["created_on"]
        if result["closed_on"] is not None:
            assert result["updated_on"] == result["closed_on"]
    stamps = [s["result"]["updated_on"] for s in updates]
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps)


def test_help_link_uses_stock_caption():
    topmenu = HTML[HTML.index('<div class="rm-topmenu">') :]
    topmenu = topmenu[: topmenu.index("</div>")]
    assert ">Help</a>" in topmenu
    assert ">?</a>" not in topmenu


def test_reset_cancels_a_pending_row_drop():
    drop = HTML[HTML.index("function dropIssue") :]
    assert "dropTimer = setTimeout(" in drop[: drop.index("\n  }\n")]
    body = HTML[HTML.index("function reset()") :]
    assert "clearTimeout(dropTimer)" in body[: body.index("\n  }\n")]


# ── Claude Code terminal mock ────────────────────────────────


def _cli_block():
    start = HTML.index('<div class="cli">')
    return HTML[start : HTML.index('<div class="scoreboard">', start)]


def test_tool_header_names_the_server_like_claude_code():
    # Claude Code titles an MCP call "<server> - <tool> (MCP)"; the README
    # registers this server as "redmine".
    assert "redmine - ${step.tool} (MCP)" in HTML


def test_tool_args_preview_keeps_every_argument():
    assert 'k !== "fields"' not in HTML


def test_pending_state_reads_like_claude_code():
    assert "Running…</span>" in HTML
    assert ">running…<" not in HTML


def test_tool_result_shows_the_real_output_not_a_summary():
    assert "step.summary" not in HTML
    assert re.search(r"^\s+summary: ", HTML, re.M) is None
    assert "JSON.stringify(result)" in HTML


def test_no_invented_claude_code_chrome():
    cli = _cli_block()
    assert "Welcome to" not in cli
    assert "tools available" not in cli
    assert "(MCP)</span></div>" not in cli
    assert "ctrl+o to collapse" not in HTML
    assert "Welcome to" not in HTML[HTML.index("const WELCOME_HTML") :][:400]


def test_prompt_uses_claude_codes_pointer_glyph():
    assert 'content: "> "' not in HTML
    assert HTML.count('content: "❯ "') == 2


# ── Page claims ──────────────────────────────────────────────


def test_page_claims_match_the_server():
    assert "The other 53 core tools" not in HTML
    assert "bulk-import a week of them with <code>manage_time_entry" not in HTML
    assert "<code>import_time_entries</code>" in HTML
    assert "wiki pages, projects, and news" not in HTML
    assert "appears automatically when those plugins are present" not in HTML
    assert "REDMINE_AGILE_ENABLED" in HTML and "REDMINE_TAGS_ENABLED" in HTML
    assert "in either mode" not in HTML
    assert "before anything irreversible happens" not in HTML
    assert "plugins,:" not in HTML
    assert "comment, log time, and close issues" not in HTML
    assert "Cursor and other clients use the generic HTTP" not in HTML


def test_network_claim_admits_url_uploads():
    # upload_file(source_url=...) fetches the URL an agent passes it.
    assert "talks to exactly two things" not in HTML
    assert "talks only to your Redmine and your MCP client." not in HTML


# ── Phone layout (Redmine's responsive view) ─────────────────


def _media_block(query):
    start = HTML.index(f"@media ({query})")
    depth, i = 0, HTML.index("{", start)
    for j in range(i, len(HTML)):
        depth += {"{": 1, "}": -1}.get(HTML[j], 0)
        if depth == 0:
            return HTML[start : j + 1]
    raise AssertionError(query)


def test_narrow_screens_get_redmines_mobile_header():
    # Redmine's responsive.css (max-width: 899px): top menu, tabs, title and
    # search hidden; a 64px bar with the project jump box and a menu button.
    assert 'class="rm-mbar"' in HTML and 'class="rm-burger"' in HTML
    block = _media_block("max-width: 899px")
    for sel in (".rm-topmenu", ".rm-menu", ".rm-headrow"):
        assert sel in block
    assert ".rm-mbar" in block


def test_phones_show_the_filters_collapsed():
    block = _media_block("max-width: 640px")
    assert ".rm-filterbox" in block and "display: none" in block
    assert 'class="rm-fold-closed"' in HTML
