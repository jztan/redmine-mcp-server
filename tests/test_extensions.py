"""Tests for the out-of-tree extension hook (REDMINE_MCP_EXTENSIONS).

Everything an extension touches is a process-wide singleton: three tables,
the registry, and the FastMCP instance the tools land on. So each test here
builds its extension modules on disk, imports them for real, and hands every
one of those back afterwards through ``extension_sandbox``. A test that left
an extension behind would change what the anti-drift tests in
``test_tool_annotations.py`` and ``test_scope_enforcement.py`` count.
"""

import importlib
import logging
import os
import subprocess
import sys

import httpx
import pytest
from fastmcp import Client, FastMCP, settings

from redmine_mcp_server import _api_key_login, _auth, _oauth_proxy, extensions
from redmine_mcp_server import main as main_module
from redmine_mcp_server._annotations import TOOL_KINDS, ToolKind, annotations_for
from redmine_mcp_server._decorators import ACTION_SPECS
from redmine_mcp_server._env import get_extension_modules
from redmine_mcp_server._extension_registry import REGISTERED_EXTENSIONS
from redmine_mcp_server._plugin_visibility import (
    PLUGIN_FLAGS,
    apply_plugin_visibility,
)
from redmine_mcp_server.extensions import ExtensionSpec, register_extension
from redmine_mcp_server.main import _load_extensions
from redmine_mcp_server.oauth_scopes import (
    TOOL_SCOPES,
    advertised_scopes,
    configured_advertised_scopes,
)
from redmine_mcp_server.server import mcp, refresh_advertised_scopes

WIDGETS_FLAG = "REDMINE_ACME_WIDGETS_ENABLED"


def _source(
    family,
    tools,
    *,
    flag=WIDGETS_FLAG,
    read=(),
    write=(),
    kinds=None,
    scopes=None,
    untagged=(),
    actions=None,
    actionless=(),
):
    """Render an extension module: one registration, then one tool per name.

    ``kinds`` and ``scopes`` default to one entry per name in ``tools``; pass
    either explicitly to build the mismatched tables a bad extension would.
    Names in ``untagged`` are defined with a bare ``@mcp.tool()``, which is
    the extension that forgets the tag its family's visibility runs on.
    ``actions`` maps a tool name to the values of its ``action`` Literal; a
    tool not in it takes ``action: str``, and one named in ``actionless``
    takes no action parameter at all.
    """
    if kinds is None:
        kinds = {name: "ToolKind.WRITE_DESTRUCTIVE" for name in tools}
    if scopes is None:
        scopes = {name: 'frozenset({"edit_issues"})' for name in tools}
    actions = actions or {}
    lines = [
        '"""Fixture extension module built by tests/test_extensions.py."""',
        "",
        *(["from typing import Literal", ""] if actions else []),
        "from redmine_mcp_server.extensions import (",
        "    ExtensionSpec,",
        "    ToolKind,",
        "    is_true_env,",
        "    mcp,",
        "    plugin_tag,",
        "    register_extension,",
        ")",
        "",
        "SPEC = ExtensionSpec(",
        f"    family={family!r},",
        f"    enabled=lambda: is_true_env({flag!r}),",
        "    tool_kinds={" + ", ".join(f"{n!r}: {k}" for n, k in kinds.items()) + "},",
        "    tool_scopes={"
        + ", ".join(f"{n!r}: {s}" for n, s in scopes.items())
        + "},",
        f"    advertised_read_scopes={tuple(read)!r},",
        f"    advertised_write_scopes={tuple(write)!r},",
        ")",
        "",
        "register_extension(SPEC)",
    ]
    for name in tools:
        decorator = (
            "@mcp.tool()"
            if name in untagged
            else f"@mcp.tool(tags={{plugin_tag({family!r})}})"
        )
        if name in actionless:
            signature = "project_id: str"
            args = ["        project_id: Project id or identifier."]
            body = '    return {"project_id": project_id}'
        else:
            if name in actions:
                literal = ", ".join(repr(value) for value in actions[name])
                signature = f"action: Literal[{literal}], project_id: str"
            else:
                signature = "action: str, project_id: str"
            args = [
                "        action: What to do.",
                "        project_id: Project id or identifier.",
            ]
            body = '    return {"action": action, "project_id": project_id}'
        lines += [
            "",
            "",
            decorator,
            f"async def {name}({signature}) -> dict:",
            '    """Stand-in for a tool over an in-house Redmine plugin.',
            "",
            "    Args:",
            *args,
            "",
            "    Returns:",
            "        A dict echoing the arguments.",
            '    """',
            body,
        ]
    return "\n".join(lines) + "\n"


@pytest.fixture
def extension_sandbox(tmp_path, monkeypatch):
    """Write importable extension modules and undo every trace afterwards.

    Yields ``write(name, source)``, which puts a module on an importable
    path and returns its name. Teardown drops the tools the extensions
    registered, restores the four shared tables and the registry, and
    forgets the modules so a later test can reuse a name.

    Visibility is deliberately not touched. A family registered after
    ``apply_plugin_visibility`` has run carries no transform, so its tools
    are listed already, and every ``enable``/``disable`` adds another
    transform to a chain the server walks per lookup -- a few hundred of
    them, one per test, is a recursion error rather than a clean-up.
    """
    tables = (PLUGIN_FLAGS, TOOL_KINDS, TOOL_SCOPES, ACTION_SPECS)
    snapshots = [dict(table) for table in tables]
    registered_before = list(REGISTERED_EXTENSIONS)
    modules_before = set(sys.modules)
    monkeypatch.syspath_prepend(str(tmp_path))

    def write(name, source):
        (tmp_path / f"{name}.py").write_text(source, encoding="utf-8")
        importlib.invalidate_caches()
        return name

    yield write

    for spec in REGISTERED_EXTENSIONS[len(registered_before) :]:
        for tool_name in spec.tool_kinds:
            try:
                mcp._local_provider.remove_tool(tool_name)
            except Exception:  # pragma: no cover - tool was never defined
                pass
    REGISTERED_EXTENSIONS[:] = registered_before
    for table, snapshot in zip(tables, snapshots):
        table.clear()
        table.update(snapshot)
    for name in set(sys.modules) - modules_before:
        origin = getattr(getattr(sys.modules[name], "__spec__", None), "origin", "")
        if str(origin).startswith(str(tmp_path)):
            del sys.modules[name]


class TestGetExtensionModules:
    def test_unset_means_none(self, monkeypatch):
        monkeypatch.delenv("REDMINE_MCP_EXTENSIONS", raising=False)
        assert get_extension_modules() == []

    @pytest.mark.parametrize("value", ["", "   ", ",", " , , "])
    def test_blank_means_none(self, monkeypatch, value):
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", value)
        assert get_extension_modules() == []

    @pytest.mark.parametrize(
        "value",
        [
            "pkg.alpha,pkg.beta",
            "pkg.alpha pkg.beta",
            "pkg.alpha, pkg.beta",
            "  pkg.alpha ,, pkg.beta  ",
            "pkg.alpha\npkg.beta",
        ],
    )
    def test_comma_and_whitespace_separated(self, monkeypatch, value):
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", value)
        assert get_extension_modules() == ["pkg.alpha", "pkg.beta"]

    def test_order_is_preserved(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "pkg.beta,pkg.alpha")
        assert get_extension_modules() == ["pkg.beta", "pkg.alpha"]


class TestRegistration:
    def test_tables_merge(self, extension_sandbox):
        before_kinds = dict(TOOL_KINDS)
        before_scopes = dict(TOOL_SCOPES)
        name = extension_sandbox(
            "ext_widgets", _source("acme_widgets", ["manage_widget"])
        )
        importlib.import_module(name)

        assert PLUGIN_FLAGS["acme_widgets"]() is False
        assert TOOL_KINDS["manage_widget"] is extensions.ToolKind.WRITE_DESTRUCTIVE
        assert TOOL_SCOPES["manage_widget"] == frozenset({"edit_issues"})
        # Merging must add, never edit: a replaced scope entry is how an
        # extension would quietly widen access to a built-in tool.
        assert {k: before_kinds[k] for k in before_kinds} == {
            k: TOOL_KINDS[k] for k in before_kinds
        }
        assert {k: before_scopes[k] for k in before_scopes} == {
            k: TOOL_SCOPES[k] for k in before_scopes
        }

    @pytest.mark.asyncio
    async def test_tool_is_annotated_from_the_merged_table(self, extension_sandbox):
        """Registering before defining is what makes annotations resolve.

        ``_AnnotatingFastMCP.tool`` reads ``TOOL_KINDS`` at decoration time,
        so an extension that defined its tool first would ship it with no
        annotations at all and nothing would fail loudly.
        """
        name = extension_sandbox(
            "ext_annotated", _source("acme_widgets", ["manage_widget"])
        )
        importlib.import_module(name)

        expected = annotations_for("manage_widget")
        assert expected.read_only_hint is False
        listed = {tool.name: tool for tool in await mcp.list_tools()}
        assert listed["manage_widget"].annotations.model_dump(
            exclude_none=True
        ) == expected.model_dump(exclude_none=True)

    def test_modules_import_in_order(self, extension_sandbox, monkeypatch):
        extension_sandbox("ext_first", _source("acme_widgets", ["manage_widget"]))
        extension_sandbox(
            "ext_second",
            _source("acme_gadgets", ["manage_gadget"], flag="REDMINE_ACME_GADGETS"),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_second, ext_first")
        _load_extensions()

        assert [spec.family for spec in REGISTERED_EXTENSIONS] == [
            "acme_gadgets",
            "acme_widgets",
        ]

    def test_family_collision_raises(self, extension_sandbox):
        extension_sandbox("ext_one", _source("acme_widgets", ["manage_widget"]))
        extension_sandbox("ext_two", _source("acme_widgets", ["manage_sprocket"]))
        importlib.import_module("ext_one")

        with pytest.raises(RuntimeError, match="acme_widgets.*already registered"):
            importlib.import_module("ext_two")

    def test_collision_with_a_built_in_family_raises(self, extension_sandbox):
        extension_sandbox("ext_crm", _source("crm", ["manage_widget"]))

        with pytest.raises(RuntimeError, match="'crm' is already registered"):
            importlib.import_module("ext_crm")

    def test_tool_name_collision_between_extensions_raises(self, extension_sandbox):
        extension_sandbox("ext_a", _source("acme_widgets", ["manage_widget"]))
        extension_sandbox(
            "ext_b",
            _source("acme_gadgets", ["manage_widget"], flag="REDMINE_ACME_GADGETS"),
        )
        importlib.import_module("ext_a")

        with pytest.raises(RuntimeError, match="already in TOOL_KINDS: manage_widget"):
            importlib.import_module("ext_b")

    def test_tool_name_collision_with_a_built_in_tool_raises(self, extension_sandbox):
        extension_sandbox(
            "ext_shadow", _source("acme_widgets", ["list_redmine_issues"])
        )

        with pytest.raises(RuntimeError, match="already in TOOL_KINDS"):
            importlib.import_module("ext_shadow")

    def test_mismatched_key_sets_raise(self, extension_sandbox):
        extension_sandbox(
            "ext_mismatch",
            _source(
                "acme_widgets",
                ["manage_widget"],
                scopes={"manage_sprocket": "frozenset()"},
            ),
        )

        with pytest.raises(RuntimeError) as excinfo:
            importlib.import_module("ext_mismatch")
        message = str(excinfo.value)
        assert "only in tool_kinds: manage_widget" in message
        assert "only in tool_scopes: manage_sprocket" in message

    def test_a_tool_declared_only_in_tool_kinds_raises(self, extension_sandbox):
        """One direction of the mismatch on its own.

        A tool with a kind and no scopes is denied by the scope middleware
        for every token, which reads as a broken deployment rather than as
        a spec to fix.
        """
        extension_sandbox(
            "ext_kinds_only",
            _source(
                "acme_widgets",
                ["manage_widget"],
                scopes={},
            ),
        )

        with pytest.raises(RuntimeError) as excinfo:
            importlib.import_module("ext_kinds_only")
        message = str(excinfo.value)
        assert "only in tool_kinds: manage_widget" in message
        assert "only in tool_scopes: none" in message

    def test_a_tool_declared_only_in_tool_scopes_raises(self, extension_sandbox):
        """The other direction: scopes for a tool that is never annotated."""
        extension_sandbox(
            "ext_scopes_only",
            _source(
                "acme_widgets",
                ["manage_widget"],
                kinds={},
            ),
        )

        with pytest.raises(RuntimeError) as excinfo:
            importlib.import_module("ext_scopes_only")
        message = str(excinfo.value)
        assert "only in tool_kinds: none" in message
        assert "only in tool_scopes: manage_widget" in message

    def test_a_rejected_registration_changes_nothing(self, extension_sandbox):
        before_flags = dict(PLUGIN_FLAGS)
        before_kinds = dict(TOOL_KINDS)
        before_scopes = dict(TOOL_SCOPES)
        registered = list(REGISTERED_EXTENSIONS)
        extension_sandbox(
            "ext_bad",
            _source(
                "acme_widgets",
                ["manage_widget", "list_redmine_issues"],
            ),
        )

        with pytest.raises(RuntimeError):
            importlib.import_module("ext_bad")

        assert PLUGIN_FLAGS == before_flags
        assert TOOL_KINDS == before_kinds
        assert TOOL_SCOPES == before_scopes
        assert REGISTERED_EXTENSIONS == registered

    def test_registering_the_same_spec_twice_is_rejected(self, extension_sandbox):
        """Import caching means a repeat can only be a real conflict.

        ``importlib.import_module`` runs a module body once, so a second
        registration of a family is never the same module loading twice. It
        is two modules claiming one family, or a stray call -- and both are
        worth a startup failure rather than a silent second entry.
        """
        name = extension_sandbox(
            "ext_twice", _source("acme_widgets", ["manage_widget"])
        )
        module = importlib.import_module(name)

        with pytest.raises(RuntimeError, match="already registered"):
            register_extension(module.SPEC)
        assert len(REGISTERED_EXTENSIONS) == 1

    def test_importing_the_same_module_twice_registers_once(self, extension_sandbox):
        name = extension_sandbox("ext_idem", _source("acme_widgets", ["manage_widget"]))
        importlib.import_module(name)
        importlib.import_module(name)

        families = [spec.family for spec in REGISTERED_EXTENSIONS]
        assert families == ["acme_widgets"]


class TestStartupLoading:
    def test_misspelled_module_fails_startup(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "no_such_extension_module")

        with pytest.raises(RuntimeError, match="no_such_extension_module"):
            _load_extensions()

    def test_a_registration_conflict_fails_startup(
        self, extension_sandbox, monkeypatch
    ):
        extension_sandbox("ext_dup_a", _source("acme_widgets", ["manage_widget"]))
        extension_sandbox("ext_dup_b", _source("acme_widgets", ["manage_gadget"]))
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_dup_a ext_dup_b")

        with pytest.raises(RuntimeError, match="ext_dup_b"):
            _load_extensions()

    def test_log_line_names_family_state_and_tool_count(
        self, extension_sandbox, monkeypatch, caplog
    ):
        """The deployment's only tokenless account of what loaded.

        ``tools/list`` needs a token in the authenticated modes, so a
        verification script reads this line instead. Its shape is therefore
        part of the contract, not a debug convenience.
        """
        extension_sandbox(
            "ext_logged",
            _source("acme_widgets", ["manage_widget", "get_widget"]),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_logged")
        monkeypatch.setenv(WIDGETS_FLAG, "true")

        with caplog.at_level(logging.INFO, logger="redmine_mcp_server.main"):
            _load_extensions()

        assert "extension loaded: family=acme_widgets enabled=true tools=2" in [
            record.getMessage() for record in caplog.records
        ]

    def test_log_line_reports_a_disabled_family(
        self, extension_sandbox, monkeypatch, caplog
    ):
        extension_sandbox("ext_off", _source("acme_widgets", ["manage_widget"]))
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_off")
        monkeypatch.setenv(WIDGETS_FLAG, "false")

        with caplog.at_level(logging.INFO, logger="redmine_mcp_server.main"):
            _load_extensions()

        assert "extension loaded: family=acme_widgets enabled=false tools=1" in [
            record.getMessage() for record in caplog.records
        ]

    def test_one_line_per_family_of_the_module_that_registered_it(
        self, extension_sandbox, monkeypatch, caplog
    ):
        extension_sandbox("ext_l1", _source("acme_widgets", ["manage_widget"]))
        extension_sandbox(
            "ext_l2",
            _source("acme_gadgets", ["manage_gadget"], flag="REDMINE_ACME_GADGETS"),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_l1,ext_l2")

        with caplog.at_level(logging.INFO, logger="redmine_mcp_server.main"):
            _load_extensions()

        loaded = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith("extension loaded:")
        ]
        assert loaded == [
            "extension loaded: family=acme_widgets enabled=false tools=1",
            "extension loaded: family=acme_gadgets enabled=false tools=1",
        ]


class TestServerInfo:
    """``get_mcp_server_info`` is the account of the surface a client can read.

    The log line needs host access; ``plugin_flags`` needs a token. Between
    them every deployment has one way to see which families loaded.
    """

    @pytest.mark.asyncio
    async def test_plugin_flags_carry_the_family_and_its_state(
        self, extension_sandbox, monkeypatch
    ):
        extension_sandbox("ext_info", _source("acme_widgets", ["manage_widget"]))
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_info")
        _load_extensions()

        async def flags():
            async with Client(mcp) as client:
                result = await client.call_tool("get_mcp_server_info", {})
            return result.data["plugin_flags"]

        monkeypatch.setenv(WIDGETS_FLAG, "true")
        on = await flags()
        monkeypatch.setenv(WIDGETS_FLAG, "false")
        off = await flags()

        assert on["acme_widgets"] is True
        assert off["acme_widgets"] is False
        # Added next to the built-in keys, never in place of them.
        assert {"agile", "crm", "dmsf", "tags"} <= set(on)


class TestColdStartImport:
    """Importing the server for the first time, the way a deployment does.

    Everything else in this suite runs against modules pytest imported long
    ago, which hides anything that can only go wrong while a module body is
    still executing. ``advertised_scopes()`` is exactly that case: in the
    authenticated modes it runs from ``server.py``'s own body, building the
    auth provider's ``scopes_supported`` before ``server.mcp`` exists. A
    registry reachable only through :mod:`redmine_mcp_server.extensions`,
    which imports ``server`` for that ``mcp``, would close the cycle and
    fail every OAuth startup -- with no extension configured at all. So
    these go through a subprocess.
    """

    @pytest.mark.parametrize("auth_mode", ["oauth", "oauth-proxy", "legacy"])
    @pytest.mark.parametrize(
        "module", ["redmine_mcp_server.main", "redmine_mcp_server.server"]
    )
    def test_first_import_succeeds(self, auth_mode, module, tmp_path):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "REDMINE_AUTH_MODE": auth_mode,
            "REDMINE_URL": "https://redmine.example.com",
            "REDMINE_MCP_BASE_URL": "https://mcp.example.com",
            "REDMINE_INTROSPECT_CLIENT_ID": "probe-id",
            "REDMINE_INTROSPECT_CLIENT_SECRET": "probe-secret",
            "REDMINE_OAUTH_CLIENT_ID": "probe-id",
            "REDMINE_OAUTH_CLIENT_SECRET": "probe-secret",
            "REDMINE_MCP_JWT_SIGNING_KEY": "k" * 44,
            # cwd is a scratch dir so a .env beside the checkout cannot
            # decide what this asserts.
            "REDMINE_MCP_EXTENSIONS": "",
        }
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            env=env,
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, (
            f"{module} failed to import under REDMINE_AUTH_MODE={auth_mode}:\n"
            f"{result.stderr}"
        )
        assert "partially initialized" not in result.stderr

    @pytest.mark.parametrize("auth_mode", ["legacy", "oauth"])
    def test_first_import_of_main_loads_the_configured_extensions(
        self, auth_mode, tmp_path
    ):
        """Delete ``_load_extensions()`` from main's body and this goes red.

        The imports above only prove that the module bodies run. None of
        them notices if the one call that reads REDMINE_MCP_EXTENSIONS is
        gone -- the server would start with none of the deployment's tools
        and nothing in the log to say so. The refresh line is the same
        proof for the auth provider, which only the authenticated modes
        have.
        """
        (tmp_path / "ext_coldstart.py").write_text(
            _source("acme_widgets", ["manage_widget"], read=("view_acme_widgets",)),
            encoding="utf-8",
        )
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(tmp_path),
            "REDMINE_AUTH_MODE": auth_mode,
            "REDMINE_URL": "https://redmine.example.com",
            "REDMINE_MCP_BASE_URL": "https://mcp.example.com",
            "REDMINE_INTROSPECT_CLIENT_ID": "probe-id",
            "REDMINE_INTROSPECT_CLIENT_SECRET": "probe-secret",
            "REDMINE_MCP_EXTENSIONS": "ext_coldstart",
            WIDGETS_FLAG: "true",
        }
        result = subprocess.run(
            [sys.executable, "-c", "import redmine_mcp_server.main"],
            env=env,
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert (
            "extension loaded: family=acme_widgets enabled=true tools=1"
            in result.stderr
        )
        refreshed = "extensions: advertised scopes refreshed" in result.stderr
        assert refreshed is (auth_mode == "oauth")


class TestAdvertisedScopes:
    def _load_widgets(self, sandbox, *, read=(), write=()):
        sandbox(
            "ext_scoped",
            _source("acme_widgets", ["manage_widget"], read=read, write=write),
        )
        return importlib.import_module("ext_scoped")

    def test_enabled_extension_scopes_are_advertised(
        self, extension_sandbox, monkeypatch
    ):
        self._load_widgets(
            extension_sandbox,
            read=("view_acme_widgets",),
            write=("manage_acme_widgets",),
        )
        monkeypatch.setenv(WIDGETS_FLAG, "true")

        advertised = advertised_scopes()
        assert "view_acme_widgets" in advertised
        assert "manage_acme_widgets" in advertised

    def test_disabled_extension_scopes_are_not_advertised(
        self, extension_sandbox, monkeypatch
    ):
        self._load_widgets(
            extension_sandbox,
            read=("view_acme_widgets",),
            write=("manage_acme_widgets",),
        )
        monkeypatch.setenv(WIDGETS_FLAG, "false")

        advertised = advertised_scopes()
        assert "view_acme_widgets" not in advertised
        assert "manage_acme_widgets" not in advertised

    def test_read_only_mode_drops_the_write_list(self, extension_sandbox, monkeypatch):
        self._load_widgets(
            extension_sandbox,
            read=("view_acme_widgets",),
            write=("manage_acme_widgets",),
        )
        monkeypatch.setenv(WIDGETS_FLAG, "true")
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")

        advertised = advertised_scopes()
        assert "view_acme_widgets" in advertised
        assert "manage_acme_widgets" not in advertised

    def test_extension_scopes_come_last_in_registration_order(
        self, extension_sandbox, monkeypatch
    ):
        extension_sandbox(
            "ext_s1",
            _source("acme_widgets", ["manage_widget"], read=("view_acme_widgets",)),
        )
        extension_sandbox(
            "ext_s2",
            _source(
                "acme_gadgets",
                ["manage_gadget"],
                flag="REDMINE_ACME_GADGETS",
                read=("view_acme_gadgets",),
            ),
        )
        baseline = advertised_scopes()
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_s1 ext_s2")
        monkeypatch.setenv(WIDGETS_FLAG, "true")
        monkeypatch.setenv("REDMINE_ACME_GADGETS", "true")
        _load_extensions()

        assert advertised_scopes() == baseline + [
            "view_acme_widgets",
            "view_acme_gadgets",
        ]

    def test_a_scope_already_advertised_is_not_repeated(
        self, extension_sandbox, monkeypatch
    ):
        """An extension names the permissions its endpoints need.

        Nothing stops those from being permissions this server already
        advertises, and ``scopes_supported`` with a repeat in it is a
        malformed discovery document.
        """
        self._load_widgets(extension_sandbox, read=("view_issues",))
        monkeypatch.setenv(WIDGETS_FLAG, "true")

        advertised = advertised_scopes()
        assert advertised.count("view_issues") == 1
        assert advertised == list(dict.fromkeys(advertised))

    def test_two_extensions_naming_one_scope_advertise_it_once(
        self, extension_sandbox, monkeypatch
    ):
        extension_sandbox(
            "ext_d1",
            _source("acme_widgets", ["manage_widget"], read=("view_acme_things",)),
        )
        extension_sandbox(
            "ext_d2",
            _source(
                "acme_gadgets",
                ["manage_gadget"],
                flag="REDMINE_ACME_GADGETS",
                read=("view_acme_things",),
            ),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_d1,ext_d2")
        monkeypatch.setenv(WIDGETS_FLAG, "true")
        monkeypatch.setenv("REDMINE_ACME_GADGETS", "true")
        _load_extensions()

        assert advertised_scopes().count("view_acme_things") == 1

    def test_configured_scopes_can_still_narrow_to_an_extension_scope(
        self, extension_sandbox, monkeypatch
    ):
        """``REDMINE_MCP_SCOPES`` is unchanged and sees the merged list."""
        self._load_widgets(extension_sandbox, read=("view_acme_widgets",))
        monkeypatch.setenv(WIDGETS_FLAG, "true")
        monkeypatch.setenv("REDMINE_MCP_SCOPES", "view_issues view_acme_widgets")

        assert configured_advertised_scopes() == [
            "view_issues",
            "view_acme_widgets",
        ]

    def test_configured_scopes_still_reject_an_unadvertised_name(
        self, extension_sandbox, monkeypatch
    ):
        self._load_widgets(extension_sandbox, read=("view_acme_widgets",))
        monkeypatch.setenv(WIDGETS_FLAG, "false")
        monkeypatch.setenv("REDMINE_MCP_SCOPES", "view_acme_widgets")

        with pytest.raises(RuntimeError, match="view_acme_widgets"):
            configured_advertised_scopes()


class TestAntiDriftWithAnExtensionLoaded:
    """The guards in test_tool_annotations.py and test_scope_enforcement.py
    have to mean the same thing once a deployment loads an extension."""

    @pytest.fixture
    def widgets(self, extension_sandbox, monkeypatch, all_plugin_tools_visible):
        monkeypatch.setenv(WIDGETS_FLAG, "true")
        extension_sandbox(
            "ext_antidrift",
            _source(
                "acme_widgets",
                ["manage_widget"],
                read=("view_acme_widgets",),
                write=("manage_acme_widgets",),
                scopes={
                    "manage_widget": (
                        '{"list": frozenset({"view_acme_widgets"}), '
                        '"create": frozenset({"manage_acme_widgets"})}'
                    )
                },
            ),
        )
        importlib.import_module("ext_antidrift")
        yield

    @pytest.mark.asyncio
    async def test_every_registered_tool_is_classified_and_mapped(self, widgets):
        import redmine_mcp_server.apps  # noqa: F401  triggers registration
        import redmine_mcp_server.tools  # noqa: F401  triggers registration

        registered = {tool.name for tool in await mcp.list_tools()}
        conditional = {"cleanup_attachment_files"}

        assert "manage_widget" in registered
        assert not registered - set(TOOL_KINDS)
        assert not registered - set(TOOL_SCOPES)
        assert not set(TOOL_KINDS) - registered - conditional
        assert not set(TOOL_SCOPES) - registered - conditional

    def test_every_enforced_scope_is_advertised(self, widgets):
        enforced = set()
        for entry in TOOL_SCOPES.values():
            if isinstance(entry, dict):
                for required in entry.values():
                    enforced |= required
            else:
                enforced |= entry

        assert enforced <= set(advertised_scopes())

    def test_upstream_entries_are_untouched(self, extension_sandbox):
        """The size assertions stay a property of this tree, not the host."""
        before_kinds = dict(TOOL_KINDS)
        before_scopes = dict(TOOL_SCOPES)
        extension_sandbox("ext_counted", _source("acme_widgets", ["manage_widget"]))
        importlib.import_module("ext_counted")

        contributed = set(REGISTERED_EXTENSIONS[-1].tool_kinds)
        assert contributed == {"manage_widget"}
        assert {
            name: kind for name, kind in TOOL_KINDS.items() if name not in contributed
        } == before_kinds
        assert {
            name: entry
            for name, entry in TOOL_SCOPES.items()
            if name not in contributed
        } == before_scopes


class TestReExportedSurface:
    """An extension depends on these names, not on the private layout."""

    def test_every_advertised_name_exists(self):
        for name in extensions.__all__:
            assert hasattr(extensions, name), name

    def test_the_registry_is_not_part_of_the_surface(self):
        """``main.py`` reads it from ``_extension_registry``; extensions do not."""
        assert "REGISTERED_EXTENSIONS" not in extensions.__all__
        assert "extension_advertised_scopes" not in extensions.__all__

    def test_shared_objects_are_the_server_s_own(self):
        """Not a copy of the machinery, the machinery itself.

        Asserted by identity for the modules nothing in this suite reloads.
        ``_client``, ``_env`` and ``oauth_scopes`` are reloaded by other
        test modules, which rebinds their functions, so the aliases onto
        those are covered by behavior below instead -- exactly the
        staleness every built-in tool module already lives with, since they
        import the same helpers by name.
        """
        from redmine_mcp_server import (
            _annotations,
            _decorators,
            _errors,
            _offload,
            _plugin_visibility,
            _serialization,
            server,
        )

        assert extensions.mcp is server.mcp
        assert extensions.plugin_tag is _plugin_visibility.plugin_tag
        assert extensions.offloaded is _offload.offloaded
        assert extensions.in_thread is _offload.in_thread
        assert extensions.action_dispatch is _decorators.action_dispatch
        assert extensions.ActionMode is _decorators.ActionMode
        assert extensions.ToolKind is _annotations.ToolKind
        assert extensions.wrap_insecure_content is _serialization.wrap_insecure_content
        assert extensions.READ_ONLY_ERROR is _errors._READ_ONLY_ERROR

    def test_env_helpers_read_the_environment_at_call_time(self, monkeypatch):
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
        monkeypatch.setenv("REDMINE_CRM_ENABLED", "yes")
        monkeypatch.setenv(WIDGETS_FLAG, "on")

        assert extensions.is_read_only_mode() is True
        assert extensions.is_crm_enabled() is True
        assert extensions.is_true_env(WIDGETS_FLAG) is True
        assert extensions.is_true_env("REDMINE_NO_SUCH_FLAG") is False

    def test_validation_and_error_helpers_behave(self):
        assert extensions.is_positive_int(3) is True
        assert extensions.is_positive_int(0) is False
        assert "read-only mode" in extensions.READ_ONLY_ERROR["error"]
        assert "error" in extensions.handle_redmine_error(ValueError("x"), "probing")
        wrapped = extensions.wrap_insecure_content("hello")
        assert "hello" in wrapped and "insecure-content" in wrapped

    def test_get_redmine_client_is_the_one_the_built_in_tools_call(self):
        from redmine_mcp_server.tools import checklists

        assert extensions.get_redmine_client is checklists._get_redmine_client

    def test_redmine_url_is_read_at_call_time(self, monkeypatch):
        from redmine_mcp_server import _client

        monkeypatch.setattr(_client, "REDMINE_URL", "https://r.example.com")
        assert extensions.redmine_url() == "https://r.example.com"
        monkeypatch.setattr(_client, "REDMINE_URL", None)
        assert extensions.redmine_url() is None

    def test_spec_defaults_to_no_advertised_scopes(self):
        spec = ExtensionSpec(
            family="acme_probe",
            enabled=lambda: False,
            tool_kinds={},
            tool_scopes={},
        )
        assert spec.advertised_read_scopes == ()
        assert spec.advertised_write_scopes == ()


async def _listed() -> set:
    """Tool names a client sees, which is what visibility transforms change."""
    async with Client(mcp) as client:
        return {tool.name for tool in await client.list_tools()}


def _oauth_env(monkeypatch):
    """The environment the authenticated modes need to build a provider."""
    monkeypatch.setenv("REDMINE_URL", "https://r.example.com")
    monkeypatch.setenv("REDMINE_MCP_BASE_URL", "http://localhost:3040")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDMINE_INTROSPECT_CLIENT_SECRET", "csec")
    monkeypatch.setenv("REDMINE_MCP_JWT_SIGNING_KEY", "k" * 44)
    monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
    monkeypatch.delenv("REDMINE_MCP_SCOPES", raising=False)


def _build_provider(mode, monkeypatch, tmp_path):
    """A provider of the shape the given REDMINE_AUTH_MODE builds at startup."""
    _oauth_env(monkeypatch)
    if mode == "oauth":
        return _auth.build_remote_auth()
    monkeypatch.setattr(settings, "home", tmp_path)
    if mode == "api-key-login":
        # _oauth_env's base URL is http, which the mode refuses without this.
        monkeypatch.setenv("REDMINE_API_KEY_LOGIN_ALLOW_HTTP", "true")
        return _api_key_login.build_api_key_login()
    return _oauth_proxy.build_oauth_proxy()


async def _served_scopes(provider, name):
    """``scopes_supported`` as a client reads it off the served document.

    Built through a throwaway FastMCP instance, the way the other discovery
    tests do, because the routes snapshot the provider's list when the HTTP
    app is built. Reading it again therefore needs a new app, not a new
    request.
    """
    app = FastMCP(name, auth=provider).http_app(stateless_http=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    return response.json()["scopes_supported"]


class TestRefreshAdvertisedScopes:
    """The provider is built before the extensions load, so it has to be told.

    ``server.py`` builds ``AUTH_PROVIDER`` in its own module body and both
    builders copy the scope list into it. ``main.py`` imports the extension
    modules afterwards. Without the refresh, ``advertised_scopes()`` and the
    document served at ``/.well-known/`` disagree -- and the document is the
    one a client consents against.
    """

    def _register_widgets(self):
        register_extension(
            ExtensionSpec(
                family="acme_widgets",
                enabled=lambda: True,
                tool_kinds={"manage_widget": ToolKind.WRITE_DESTRUCTIVE},
                tool_scopes={"manage_widget": frozenset({"view_acme_widgets"})},
                advertised_read_scopes=("view_acme_widgets",),
                advertised_write_scopes=("manage_acme_widgets",),
            )
        )

    @pytest.mark.parametrize("mode", ["oauth", "oauth-proxy", "api-key-login"])
    def test_provider_gains_the_extension_scopes(
        self, mode, extension_sandbox, monkeypatch, tmp_path
    ):
        provider = _build_provider(mode, monkeypatch, tmp_path)
        before = list(provider.scopes_supported)
        assert "view_acme_widgets" not in before

        self._register_widgets()
        refresh_advertised_scopes(provider)

        after = provider.scopes_supported
        assert "view_acme_widgets" in after
        assert "manage_acme_widgets" in after
        # Widened, never replaced: the built-in permissions are still there
        # and still in their own order.
        assert after[: len(before)] == before

    def test_read_only_mode_still_suppresses_the_write_list(
        self, extension_sandbox, monkeypatch, tmp_path
    ):
        provider = _build_provider("oauth", monkeypatch, tmp_path)
        self._register_widgets()
        monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")

        refresh_advertised_scopes(provider)

        assert "view_acme_widgets" in provider.scopes_supported
        assert "manage_acme_widgets" not in provider.scopes_supported

    @pytest.mark.parametrize("mode", ["oauth", "api-key-login"])
    def test_configured_subset_still_narrows_the_provider(
        self, mode, extension_sandbox, monkeypatch, tmp_path
    ):
        """Each provider keeps the source its own builder used.

        ``build_remote_auth`` and ``build_api_key_login`` both pass
        ``configured_advertised_scopes()``, so the refresh has to as well or
        ``REDMINE_MCP_SCOPES`` would quietly stop applying the moment an
        extension loads.
        """
        provider = _build_provider(mode, monkeypatch, tmp_path)
        self._register_widgets()
        monkeypatch.setenv("REDMINE_MCP_SCOPES", "view_issues view_acme_widgets")

        refresh_advertised_scopes(provider)

        assert provider.scopes_supported == ["view_issues", "view_acme_widgets"]

    def test_api_key_login_grants_the_extension_scope_after_the_refresh(
        self, extension_sandbox, monkeypatch, tmp_path
    ):
        """Advertising is half of it: this provider also grants from its copy.

        ``_granted_scopes`` intersects the request with ``_advertised`` and
        the SDK's registration handler checks ``valid_scopes`` and fills from
        ``default_scopes``, three snapshots the constructor took. A refresh
        that moved only the served document would leave every scoped
        extension tool denied.
        """
        from mcp.server.auth.provider import AuthorizationParams
        from mcp.shared.auth import OAuthClientInformationFull
        from pydantic import AnyUrl

        provider = _build_provider("api-key-login", monkeypatch, tmp_path)
        redirect = AnyUrl("http://localhost:41999/callback")
        client = OAuthClientInformationFull(
            client_id="c1", redirect_uris=[redirect], scope="view_issues"
        )
        params = AuthorizationParams(
            state=None,
            scopes=["view_acme_widgets", "view_issues"],
            code_challenge="challenge",
            redirect_uri=redirect,
            redirect_uri_provided_explicitly=True,
        )
        assert provider._granted_scopes(client, params) == ["view_issues"]

        self._register_widgets()
        refresh_advertised_scopes(provider)

        assert provider._granted_scopes(client, params) == [
            "view_acme_widgets",
            "view_issues",
        ]
        options = provider.client_registration_options
        assert "view_acme_widgets" in options.valid_scopes
        assert "view_acme_widgets" in options.default_scopes

    def test_legacy_mode_has_nothing_to_refresh(self):
        assert refresh_advertised_scopes(None) is None

    def test_an_unknown_provider_is_left_alone_when_nothing_is_declared(
        self, extension_sandbox
    ):
        """No advertised scopes, nothing a foreign provider could be missing."""
        register_extension(
            ExtensionSpec(
                family="acme_widgets",
                enabled=lambda: True,
                tool_kinds={"manage_widget": ToolKind.WRITE_DESTRUCTIVE},
                tool_scopes={"manage_widget": frozenset({"edit_issues"})},
            )
        )

        class Foreign:
            scopes_supported = ["view_issues"]

        provider = Foreign()
        assert refresh_advertised_scopes(provider) is None
        assert provider.scopes_supported == ["view_issues"]

    def test_an_unknown_provider_fails_startup_once_scopes_are_declared(
        self, extension_sandbox
    ):
        """Fail closed: a provider left with its snapshot would deny the tools."""

        class Foreign:
            scopes_supported = ["view_issues"]

        self._register_widgets()

        with pytest.raises(RuntimeError) as excinfo:
            refresh_advertised_scopes(Foreign())
        message = str(excinfo.value)
        assert "Foreign" in message
        assert "manage_acme_widgets, view_acme_widgets" in message

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["oauth", "oauth-proxy", "api-key-login"])
    async def test_served_document_lists_the_extension_scope(
        self, mode, extension_sandbox, monkeypatch, tmp_path
    ):
        """End to end: the JSON a client actually fetches.

        The bug this covers is invisible to ``advertised_scopes()``, which
        was right all along. Only the served document was stale.
        """
        provider = _build_provider(mode, monkeypatch, tmp_path)
        before = await _served_scopes(provider, f"{mode}_before")
        assert "view_acme_widgets" not in before

        extension_sandbox(
            "ext_served",
            _source(
                "acme_widgets",
                ["manage_widget"],
                read=("view_acme_widgets",),
                write=("manage_acme_widgets",),
            ),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_served")
        monkeypatch.setenv(WIDGETS_FLAG, "true")
        monkeypatch.setattr(main_module, "AUTH_PROVIDER", provider)
        _load_extensions()

        after = await _served_scopes(provider, f"{mode}_after")
        assert "view_acme_widgets" in after
        assert "manage_acme_widgets" in after
        assert len(after) == len(before) + 2
        assert after == advertised_scopes()

    @pytest.mark.asyncio
    async def test_both_discovery_documents_agree_after_the_refresh(
        self, extension_sandbox, monkeypatch, tmp_path
    ):
        """The authorization-server document reads the same property now.

        It used to read the backing attribute, which meant a refresh would
        have moved one document and not the other.
        """
        provider = _build_provider("oauth", monkeypatch, tmp_path)
        extension_sandbox(
            "ext_two_docs",
            _source("acme_widgets", ["manage_widget"], read=("view_acme_widgets",)),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_two_docs")
        monkeypatch.setenv(WIDGETS_FLAG, "true")
        monkeypatch.setattr(main_module, "AUTH_PROVIDER", provider)
        _load_extensions()

        app = FastMCP("two_docs", auth=provider).http_app(stateless_http=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            pr = (await client.get("/.well-known/oauth-protected-resource/mcp")).json()
            asm = (
                await client.get("/.well-known/oauth-authorization-server/mcp")
            ).json()

        assert pr["scopes_supported"] == asm["scopes_supported"]
        assert "view_acme_widgets" in asm["scopes_supported"]

    @pytest.mark.asyncio
    async def test_the_two_documents_read_one_source(self, monkeypatch):
        """Both read the ``scopes_supported`` property, not the attribute.

        Nothing this server builds constructs the provider without a list,
        but the two are only equivalent while one is set: with the
        constructor argument left out the property falls back to the token
        verifier and the attribute stays ``None``, which is one document
        advertising a list and the other omitting the field.
        """
        from pydantic import AnyHttpUrl

        provider = _auth.RedmineAuthProvider(
            redmine_url=AnyHttpUrl("https://r.example.com"),
            base_url="http://localhost:3040",
            introspect_client_id="cid",
            introspect_client_secret="csec",
            scopes_supported=None,
        )
        app = FastMCP("one_source", auth=provider).http_app(stateless_http=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            pr = (await client.get("/.well-known/oauth-protected-resource/mcp")).json()
            asm = (
                await client.get("/.well-known/oauth-authorization-server/mcp")
            ).json()

        assert asm.get("scopes_supported") == pr["scopes_supported"]

    def test_a_stock_server_never_touches_its_provider(self, monkeypatch):
        """No extensions, no refresh, so a stock provider stays byte-identical."""
        monkeypatch.delenv("REDMINE_MCP_EXTENSIONS", raising=False)
        calls = []
        monkeypatch.setattr(main_module, "refresh_advertised_scopes", calls.append)

        _load_extensions()

        assert calls == []

    def test_loading_an_extension_refreshes_once(self, extension_sandbox, monkeypatch):
        extension_sandbox("ext_refreshed", _source("acme_widgets", ["manage_widget"]))
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_refreshed")
        calls = []
        monkeypatch.setattr(main_module, "refresh_advertised_scopes", calls.append)

        _load_extensions()

        assert calls == [main_module.AUTH_PROVIDER]

    def test_the_refresh_is_logged_with_a_count(
        self, extension_sandbox, monkeypatch, tmp_path, caplog
    ):
        provider = _build_provider("oauth", monkeypatch, tmp_path)
        expected = len(provider.scopes_supported) + 1
        extension_sandbox(
            "ext_logged_refresh",
            _source("acme_widgets", ["manage_widget"], read=("view_acme_widgets",)),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_logged_refresh")
        monkeypatch.setenv(WIDGETS_FLAG, "true")
        monkeypatch.setattr(main_module, "AUTH_PROVIDER", provider)

        with caplog.at_level(logging.INFO, logger="redmine_mcp_server.main"):
            _load_extensions()

        assert f"extensions: advertised scopes refreshed ({expected} scopes)" in [
            record.getMessage() for record in caplog.records
        ]


class TestImportMatchesItsSpecs:
    """What a module registers and what it defines have to be the same set.

    ``register_extension`` sees the spec; nothing else sees the tools. The
    two halves sit in different parts of the module and only the check
    around the import ties them together.
    """

    def test_fastmcp_duplicate_policy_is_warn_and_replace(self):
        """Why the replaced-tool rule below exists at all.

        ``server.py`` builds the instance without ``on_duplicate``, and
        FastMCP 4's default is ``warn``: a second registration of a name
        logs a line and takes it. Nothing raises, so deferring to the
        framework here would defer to a warning nobody reads.
        """
        assert mcp._on_duplicate == "warn"
        assert mcp._local_provider._on_duplicate == "warn"

    def test_an_undeclared_tool_fails_startup(self, extension_sandbox, monkeypatch):
        extension_sandbox(
            "ext_undeclared",
            _source(
                "acme_widgets",
                ["manage_widget", "manage_sprocket"],
                kinds={"manage_widget": "ToolKind.WRITE_DESTRUCTIVE"},
                scopes={"manage_widget": 'frozenset({"edit_issues"})'},
            ),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_undeclared")

        with pytest.raises(RuntimeError) as excinfo:
            _load_extensions()
        message = str(excinfo.value)
        assert "ext_undeclared" in message
        assert "no ExtensionSpec it registered declares: manage_sprocket" in message

    def test_a_declared_but_undefined_tool_fails_startup(
        self, extension_sandbox, monkeypatch
    ):
        extension_sandbox(
            "ext_phantom",
            _source(
                "acme_widgets",
                ["manage_widget"],
                kinds={
                    "manage_widget": "ToolKind.WRITE_DESTRUCTIVE",
                    "manage_sprocket": "ToolKind.READ",
                },
                scopes={
                    "manage_widget": 'frozenset({"edit_issues"})',
                    "manage_sprocket": 'frozenset({"view_issues"})',
                },
            ),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_phantom")

        with pytest.raises(RuntimeError, match="never defined: manage_sprocket"):
            _load_extensions()

    def test_replacing_an_existing_tool_fails_startup(
        self, extension_sandbox, monkeypatch
    ):
        """A name already on the surface, taken by a later module.

        ``register_extension`` refuses a name that is already in the
        tables, so the only way to reach a live tool object is to redefine
        a name the spec does not mention -- which is exactly what an
        extension shadowing a built-in would look like.
        """
        extension_sandbox("ext_owner", _source("acme_widgets", ["manage_widget"]))
        extension_sandbox(
            "ext_thief",
            _source(
                "acme_gadgets",
                ["manage_gadget", "manage_widget"],
                flag="REDMINE_ACME_GADGETS",
                kinds={"manage_gadget": "ToolKind.READ"},
                scopes={"manage_gadget": 'frozenset({"view_issues"})'},
            ),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_owner ext_thief")

        with pytest.raises(RuntimeError, match="replaced tool"):
            _load_extensions()

    def test_a_tool_without_its_family_tag_fails_startup(
        self, extension_sandbox, monkeypatch
    ):
        extension_sandbox(
            "ext_untagged",
            _source(
                "acme_widgets",
                ["manage_widget"],
                untagged=("manage_widget",),
            ),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_untagged")

        with pytest.raises(RuntimeError) as excinfo:
            _load_extensions()
        message = str(excinfo.value)
        assert "manage_widget" in message
        assert "plugin:acme_widgets" in message

    def test_a_well_formed_module_passes_every_check(
        self, extension_sandbox, monkeypatch
    ):
        extension_sandbox(
            "ext_wellformed",
            _source("acme_widgets", ["manage_widget", "get_widget"]),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_wellformed")

        _load_extensions()

        assert [spec.family for spec in REGISTERED_EXTENSIONS] == ["acme_widgets"]

    def test_an_unreadable_registry_fails_startup(self, extension_sandbox, monkeypatch):
        """Every check here fails closed, this one included.

        The allow list treats the same private registry as best-effort
        because it only spots typos with it. Here it is what ties a module's
        tools to its spec, so a registry that cannot be read leaves an
        import unverified, and an unverified import is not served.
        """
        extension_sandbox("ext_blind", _source("acme_widgets", ["manage_widget"]))
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_blind")
        monkeypatch.setattr(main_module, "registered_tool_names", lambda _mcp: set())

        with pytest.raises(RuntimeError, match="Cannot enumerate"):
            _load_extensions()

    def _per_action(self, *actions):
        """A scope map over ``actions``, in the source form ``_source`` takes."""
        return "{" + ", ".join(f"{a!r}: frozenset()" for a in actions) + "}"

    def test_per_action_scopes_matching_the_literal_pass(
        self, extension_sandbox, monkeypatch
    ):
        extension_sandbox(
            "ext_actions_ok",
            _source(
                "acme_widgets",
                ["manage_widget"],
                actions={"manage_widget": ("list", "create")},
                scopes={"manage_widget": self._per_action("list", "create")},
            ),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_actions_ok")

        _load_extensions()

        assert TOOL_SCOPES["manage_widget"] == {
            "list": frozenset(),
            "create": frozenset(),
        }

    def test_a_one_value_literal_is_read_as_a_const(
        self, extension_sandbox, monkeypatch
    ):
        """pydantic renders ``Literal["list"]`` as ``const``, not ``enum``."""
        extension_sandbox(
            "ext_one_action",
            _source(
                "acme_widgets",
                ["manage_widget"],
                actions={"manage_widget": ("list",)},
                scopes={"manage_widget": self._per_action("list")},
            ),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_one_action")

        _load_extensions()

        assert set(TOOL_SCOPES["manage_widget"]) == {"list"}

    def test_an_action_the_map_leaves_out_fails_startup(
        self, extension_sandbox, monkeypatch
    ):
        """The unmapped action is the one that would run with no scope check."""
        extension_sandbox(
            "ext_unmapped",
            _source(
                "acme_widgets",
                ["manage_widget"],
                actions={"manage_widget": ("list", "create", "delete")},
                scopes={"manage_widget": self._per_action("list", "create")},
            ),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_unmapped")

        with pytest.raises(RuntimeError) as excinfo:
            _load_extensions()
        message = str(excinfo.value)
        assert "manage_widget" in message
        assert "Accepted but not in tool_scopes: delete" in message
        assert "in tool_scopes but not accepted: none" in message

    def test_an_action_the_tool_does_not_accept_fails_startup(
        self, extension_sandbox, monkeypatch
    ):
        extension_sandbox(
            "ext_unaccepted",
            _source(
                "acme_widgets",
                ["manage_widget"],
                actions={"manage_widget": ("list", "create")},
                scopes={"manage_widget": self._per_action("list", "create", "delete")},
            ),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_unaccepted")

        with pytest.raises(RuntimeError, match="not accepted: delete"):
            _load_extensions()

    def test_per_action_scopes_on_a_plain_str_action_fail_startup(
        self, extension_sandbox, monkeypatch
    ):
        """``action: str`` accepts anything, so no map can cover it."""
        extension_sandbox(
            "ext_str_action",
            _source(
                "acme_widgets",
                ["manage_widget"],
                scopes={"manage_widget": self._per_action("list", "create")},
            ),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_str_action")

        with pytest.raises(RuntimeError, match="not a Literal|typed as a Literal"):
            _load_extensions()

    def test_per_action_scopes_on_a_tool_without_an_action_fail_startup(
        self, extension_sandbox, monkeypatch
    ):
        extension_sandbox(
            "ext_no_action",
            _source(
                "acme_widgets",
                ["manage_widget"],
                actionless=("manage_widget",),
                scopes={"manage_widget": self._per_action("list")},
            ),
        )
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_no_action")

        with pytest.raises(RuntimeError, match="no action parameter"):
            _load_extensions()

    def test_a_whole_tool_entry_needs_no_literal(self, extension_sandbox, monkeypatch):
        """A frozenset applies to every call, so ``action: str`` is fine."""
        extension_sandbox("ext_flat_scopes", _source("acme_widgets", ["manage_widget"]))
        monkeypatch.setenv("REDMINE_MCP_EXTENSIONS", "ext_flat_scopes")

        _load_extensions()

        assert TOOL_SCOPES["manage_widget"] == frozenset({"edit_issues"})


def _spec(**overrides):
    """A spec that would register cleanly, with one field replaced."""
    fields = {
        "family": "acme_widgets",
        "enabled": lambda: False,
        "tool_kinds": {"manage_widget": ToolKind.WRITE_DESTRUCTIVE},
        "tool_scopes": {"manage_widget": frozenset({"edit_issues"})},
        "advertised_read_scopes": ("view_acme_widgets",),
        "advertised_write_scopes": ("manage_acme_widgets",),
    }
    fields.update(overrides)
    return ExtensionSpec(**fields)


class TestSpecValidation:
    """A dataclass records what it was handed; it does not check it.

    Every field is read later and by something else -- the decorator, the
    middleware, the visibility pass, the discovery document -- so a wrong
    shape surfaces far from the line that wrote it. The worst of them, a
    bare ``str`` in an advertised list, surfaces as a plausible document
    full of single-letter scopes.
    """

    def test_construction_is_keyword_only(self):
        """Field order must never become something an extension depends on."""
        with pytest.raises(TypeError):
            ExtensionSpec(
                "acme_widgets",
                lambda: False,
                {"manage_widget": ToolKind.READ},
                {"manage_widget": frozenset()},
            )

    @pytest.mark.parametrize(
        "overrides,field",
        [
            ({"family": ""}, "family"),
            ({"family": None}, "family"),
            ({"family": 7}, "family"),
            ({"enabled": True}, "enabled"),
            ({"enabled": None}, "enabled"),
            (
                {
                    "tool_kinds": {"": ToolKind.READ},
                    "tool_scopes": {"": frozenset()},
                },
                "tool_kinds",
            ),
            (
                {
                    "tool_kinds": {None: ToolKind.READ},
                    "tool_scopes": {None: frozenset()},
                },
                "tool_kinds",
            ),
            ({"tool_kinds": {"manage_widget": "write"}}, "tool_kinds"),
            ({"tool_kinds": {"manage_widget": None}}, "tool_kinds"),
            (
                {"tool_scopes": {"manage_widget": {"edit_issues"}}},
                "tool_scopes['manage_widget']",
            ),
            (
                {"tool_scopes": {"manage_widget": ["edit_issues"]}},
                "tool_scopes['manage_widget']",
            ),
            (
                {"tool_scopes": {"manage_widget": frozenset({7})}},
                "tool_scopes['manage_widget']",
            ),
            (
                {"tool_scopes": {"manage_widget": frozenset({""})}},
                "tool_scopes['manage_widget']",
            ),
            (
                {"tool_scopes": {"manage_widget": {"list": {"view_issues"}}}},
                "tool_scopes['manage_widget']['list']",
            ),
            (
                {"tool_scopes": {"manage_widget": {"": frozenset()}}},
                "tool_scopes['manage_widget']",
            ),
            ({"advertised_read_scopes": "view_acme_widgets"}, "read"),
            ({"advertised_write_scopes": "manage_acme_widgets"}, "write"),
            ({"advertised_read_scopes": {"view_acme_widgets"}}, "read"),
            ({"advertised_read_scopes": None}, "read"),
            ({"advertised_read_scopes": ("",)}, "read"),
            ({"advertised_write_scopes": (7,)}, "write"),
        ],
    )
    def test_a_malformed_field_is_rejected_by_name(self, overrides, field):
        with pytest.raises(RuntimeError) as excinfo:
            register_extension(_spec(**overrides))
        assert field in str(excinfo.value)

    def test_a_bare_str_is_named_as_such(self):
        """The one shape that would otherwise produce a plausible document."""
        with pytest.raises(RuntimeError, match="bare str"):
            register_extension(_spec(advertised_read_scopes="view_acme_widgets"))

    def test_validation_runs_before_the_tables_are_read(self, extension_sandbox):
        """A rejected spec leaves every table exactly as it found it."""
        before_flags = dict(PLUGIN_FLAGS)
        before_kinds = dict(TOOL_KINDS)
        before_scopes = dict(TOOL_SCOPES)
        registered = list(REGISTERED_EXTENSIONS)

        with pytest.raises(RuntimeError):
            register_extension(_spec(advertised_read_scopes="view_acme_widgets"))

        assert PLUGIN_FLAGS == before_flags
        assert TOOL_KINDS == before_kinds
        assert TOOL_SCOPES == before_scopes
        assert REGISTERED_EXTENSIONS == registered

    def test_a_well_formed_spec_is_accepted(self, extension_sandbox):
        register_extension(_spec())

        assert PLUGIN_FLAGS["acme_widgets"]() is False
        assert TOOL_KINDS["manage_widget"] is ToolKind.WRITE_DESTRUCTIVE

    @pytest.mark.parametrize(
        "entry",
        [
            frozenset(),
            frozenset({"edit_issues"}),
            {"list": frozenset({"view_issues"})},
            {"list": frozenset()},
        ],
    )
    def test_both_tool_scopes_shapes_are_accepted(self, entry, extension_sandbox):
        """The two shapes TOOL_SCOPES itself uses, empty sets included."""
        register_extension(_spec(tool_scopes={"manage_widget": entry}))

        assert TOOL_SCOPES["manage_widget"] == entry

    def test_an_empty_advertised_list_is_accepted(self, extension_sandbox):
        """Most extensions need no new permission at all."""
        register_extension(_spec(advertised_read_scopes=(), advertised_write_scopes=[]))

        assert REGISTERED_EXTENSIONS[-1].advertised_read_scopes == ()


class TestPluginVisibilityForAnExtension:
    """A registered family is a family like any other to the visibility pass."""

    @pytest.mark.asyncio
    async def test_the_family_flag_hides_and_lists_its_tools(
        self, extension_sandbox, monkeypatch
    ):
        extension_sandbox("ext_visible", _source("acme_widgets", ["manage_widget"]))
        importlib.import_module("ext_visible")

        monkeypatch.setenv(WIDGETS_FLAG, "false")
        state = apply_plugin_visibility(mcp)
        assert state["acme_widgets"] is False
        assert "manage_widget" not in await _listed()

        # Left enabled on purpose rather than restored in teardown. Every
        # enable/disable appends another transform to a chain the server
        # walks per lookup, so undoing this would cost more than it buys --
        # and a later test registering this family again would otherwise
        # inherit a disabled surface from a transform it never asked for.
        monkeypatch.setenv(WIDGETS_FLAG, "true")
        state = apply_plugin_visibility(mcp)
        assert state["acme_widgets"] is True
        assert "manage_widget" in await _listed()
