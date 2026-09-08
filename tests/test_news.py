"""News tools: reading, writing, and the places this API misleads.

Every news write answers 204 with no body, so python-redmine reconstructs
the result of a create by re-reading, scoped to the project that was
posted to. And two failures arrive as bare HTTP codes that mean something
specific here: 403 for a project with the news module off, 404 on create
for a Redmine without the write endpoint. All three are places where a tool
can look successful, or fail for the wrong stated reason, so all three are
pinned.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from redminelib.exceptions import ResourceNotFoundError, ResourceSetIndexError

from redmine_mcp_server.tools import news as news_mod
from redmine_mcp_server.tools.news import (
    _news_to_dict,
    delete_redmine_news,
    get_redmine_news,
    list_redmine_news,
)


def _news(**extra):
    """A python-redmine-ish News object."""
    base = dict(
        id=7,
        project=SimpleNamespace(id=1291, name="FTTA Maintenance & Support"),
        author=SimpleNamespace(id=108, name="Andreas Lemmer"),
        title="Release 2.4 is out",
        summary="Ships the new self-registration flow.",
        description="<p>Rolled out to prod on Saturday.</p>",
        created_on="2026-09-05T08:00:00Z",
    )
    base.update(extra)
    obj = SimpleNamespace(**base)
    obj.raw = lambda: dict(base)
    return obj


def _client(**managers):
    return SimpleNamespace(news=SimpleNamespace(**managers))


@pytest.fixture(autouse=True)
def _writes_allowed(monkeypatch):
    monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)


# --- serialization ------------------------------------------------------


def test_prose_is_wrapped_and_the_title_is_not():
    """The title is label-shaped, like an issue's subject."""
    result = _news_to_dict(_news())
    assert result["title"] == "Release 2.4 is out"
    assert result["summary"].startswith("<insecure-content-")
    assert result["description"].startswith("<insecure-content-")
    assert "self-registration" in result["summary"]


def test_refs_are_id_and_name():
    result = _news_to_dict(_news())
    assert result["project"] == {"id": 1291, "name": "FTTA Maintenance & Support"}
    assert result["author"] == {"id": 108, "name": "Andreas Lemmer"}


def test_comments_and_attachments_are_absent_unless_present():
    assert "comments" not in _news_to_dict(_news())
    assert "attachments" not in _news_to_dict(_news())


def test_comment_content_is_wrapped():
    comment = SimpleNamespace(
        id=3,
        author=SimpleNamespace(id=13, name="Andreas Streit"),
        content="Bitte auch auf INT ausrollen",
        created_on="2026-09-05T09:00:00Z",
    )
    result = _news_to_dict(_news(comments=[comment]))
    assert len(result["comments"]) == 1
    assert result["comments"][0]["content"].startswith("<insecure-content-")
    assert result["comments"][0]["author"] == {"id": 13, "name": "Andreas Streit"}


# --- listing ------------------------------------------------------------


@pytest.mark.asyncio
async def test_listing_serializes_every_item():
    with patch.object(
        news_mod,
        "_get_redmine_client",
        return_value=_client(filter=lambda **kw: [_news(), _news(id=8)]),
    ):
        result = await list_redmine_news()
    assert [item["id"] for item in result] == [7, 8]


@pytest.mark.asyncio
async def test_the_project_filter_is_forwarded():
    seen = {}

    def _filter(**kw):
        seen.update(kw)
        return [_news()]

    with patch.object(
        news_mod, "_get_redmine_client", return_value=_client(filter=_filter)
    ):
        await list_redmine_news(project_id=1291, limit=5, offset=10)
    assert seen["project_id"] == 1291
    assert seen["limit"] == 5
    assert seen["offset"] == 10


@pytest.mark.asyncio
async def test_a_string_project_identifier_works():
    items = [_news()]
    with patch.object(
        news_mod, "_get_redmine_client", return_value=_client(filter=lambda **kw: items)
    ):
        result = await list_redmine_news(project_id="FTTA Maintenance & Support")
    assert [item["id"] for item in result] == [7]


@pytest.mark.asyncio
async def test_an_unknown_project_is_reported_as_not_found():
    """Redmine answers a bad project_id with a hard 404, not an empty list."""

    def _filter(**kw):
        raise ResourceNotFoundError

    with patch.object(
        news_mod, "_get_redmine_client", return_value=_client(filter=_filter)
    ):
        result = await list_redmine_news(project_id=999999)
    assert result["code"] == "NOT_FOUND"
    assert result["project_id"] == 999999


# --- reading one --------------------------------------------------------


@pytest.mark.asyncio
async def test_get_requests_both_includes_by_default():
    seen = {}

    def _get(news_id, **kw):
        seen["id"] = news_id
        seen.update(kw)
        return _news()

    with patch.object(news_mod, "_get_redmine_client", return_value=_client(get=_get)):
        await get_redmine_news(7)
    assert seen["id"] == 7
    assert set(seen["include"].split(",")) == {"comments", "attachments"}


@pytest.mark.asyncio
async def test_get_can_drop_the_includes():
    seen = {}

    def _get(news_id, **kw):
        seen.update(kw)
        return _news()

    with patch.object(news_mod, "_get_redmine_client", return_value=_client(get=_get)):
        await get_redmine_news(7, include_comments=False, include_attachments=False)
    assert seen["include"] is None


@pytest.mark.asyncio
async def test_a_missing_item_is_reported_as_missing():
    def _get(news_id, **kw):
        raise ResourceNotFoundError

    with patch.object(news_mod, "_get_redmine_client", return_value=_client(get=_get)):
        result = await get_redmine_news(404)
    assert result["code"] == "NOT_FOUND"
    assert result["upstream_status"] == 404


@pytest.mark.asyncio
async def test_a_bad_id_never_reaches_redmine():
    with patch.object(news_mod, "_get_redmine_client") as client:
        result = await get_redmine_news(0)
    assert "positive integer" in result["error"]
    client.assert_not_called()


# --- creating -----------------------------------------------------------


@pytest.mark.asyncio
async def test_create_returns_the_item_when_the_read_back_matches():
    seen = {}

    def _create(**kw):
        seen.update(kw)
        return _news(title=kw["title"])

    with patch.object(
        news_mod, "_get_redmine_client", return_value=_client(create=_create)
    ):
        result = await news_mod.manage_redmine_news(
            action="create",
            project_id=1291,
            title="Wartungsfenster Samstag",
            description="20:00 bis 23:00",
        )
    assert result["title"] == "Wartungsfenster Samstag"
    assert seen["project_id"] == 1291


@pytest.mark.asyncio
async def test_a_read_back_with_a_different_title_is_not_confirmed():
    """201 carries no body, so python-redmine returns the newest news item.

    Right after a create that is *probably* ours -- but a neighbour's record
    with a plausible id is worse than saying so.
    """
    with patch.object(
        news_mod,
        "_get_redmine_client",
        return_value=_client(create=lambda **kw: _news(title="jemand anderes")),
    ):
        result = await news_mod.manage_redmine_news(
            action="create", project_id=1291, title="Meine Meldung", description="x"
        )
    assert result["success"] is True
    assert result["confirmed"] is False
    assert result["code"] == "CREATE_UNCONFIRMED"
    assert result["sent"]["title"] == "Meine Meldung"
    assert "id" not in result


@pytest.mark.asyncio
async def test_a_failed_read_back_is_not_a_failed_create():
    """The 201 already happened; reporting an error would be wrong."""

    def _create(**kw):
        raise ResourceSetIndexError

    with patch.object(
        news_mod, "_get_redmine_client", return_value=_client(create=_create)
    ):
        result = await news_mod.manage_redmine_news(
            action="create", project_id=1291, title="T", description="D"
        )
    assert result["success"] is True
    assert result["code"] == "CREATE_UNCONFIRMED"
    assert "error" not in result


@pytest.mark.asyncio
async def test_create_names_the_field_redmine_would_have_rejected():
    for missing, field in (
        ({"project_id": 1291, "description": "d"}, "title"),
        ({"project_id": 1291, "title": "t"}, "description"),
        ({"title": "t", "description": "d"}, "project_id"),
    ):
        with patch.object(news_mod, "_get_redmine_client") as client:
            result = await news_mod.manage_redmine_news(action="create", **missing)
        assert field in result["error"], field
        client.assert_not_called()


@pytest.mark.asyncio
async def test_a_blank_title_is_not_a_title():
    with patch.object(news_mod, "_get_redmine_client") as client:
        result = await news_mod.manage_redmine_news(
            action="create", project_id=1291, title="   ", description="d"
        )
    assert "title" in result["error"]
    client.assert_not_called()


# --- updating -----------------------------------------------------------


@pytest.mark.asyncio
async def test_update_sends_only_what_was_given_and_reads_back():
    seen = {}

    def _update(news_id, **kw):
        seen["id"] = news_id
        seen.update(kw)
        return True

    client = _client(update=_update, get=lambda news_id, **kw: _news(title="neu"))
    with patch.object(news_mod, "_get_redmine_client", return_value=client):
        result = await news_mod.manage_redmine_news(
            action="update", news_id=7, title="neu"
        )
    assert seen == {"id": 7, "title": "neu"}
    assert result["title"] == "neu"


@pytest.mark.asyncio
async def test_an_empty_summary_clears_it_rather_than_being_dropped():
    seen = {}

    def _update(news_id, **kw):
        seen.update(kw)
        return True

    client = _client(update=_update, get=lambda news_id, **kw: _news())
    with patch.object(news_mod, "_get_redmine_client", return_value=client):
        await news_mod.manage_redmine_news(action="update", news_id=7, summary="")
    assert seen == {"summary": ""}


@pytest.mark.asyncio
async def test_an_update_with_nothing_to_change_is_refused():
    with patch.object(news_mod, "_get_redmine_client") as client:
        result = await news_mod.manage_redmine_news(action="update", news_id=7)
    assert "Nothing to update" in result["error"]
    client.assert_not_called()


@pytest.mark.asyncio
async def test_an_unreadable_update_still_reports_success():
    def _get(news_id, **kw):
        raise Exception("gone in the meantime")

    client = _client(update=lambda news_id, **kw: True, get=_get)
    with patch.object(news_mod, "_get_redmine_client", return_value=client):
        result = await news_mod.manage_redmine_news(
            action="update", news_id=7, title="neu"
        )
    assert result["success"] is True
    assert result["code"] == "UPDATE_UNCONFIRMED"
    assert result["updated_fields"] == ["title"]


# --- read-only mode -----------------------------------------------------


@pytest.mark.asyncio
async def test_writes_are_blocked_in_read_only_mode(monkeypatch):
    monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
    with patch.object(news_mod, "_get_redmine_client") as client:
        created = await news_mod.manage_redmine_news(
            action="create", project_id=1291, title="t", description="d"
        )
        updated = await news_mod.manage_redmine_news(
            action="update", news_id=7, title="t"
        )
        deleted = await delete_redmine_news(news_id=7, confirm_delete=True)
    for result in (created, updated, deleted):
        assert "error" in result
    client.assert_not_called()


@pytest.mark.asyncio
async def test_reads_still_work_in_read_only_mode(monkeypatch):
    monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
    with patch.object(
        news_mod,
        "_get_redmine_client",
        return_value=_client(get=lambda n, **kw: _news()),
    ):
        assert (await get_redmine_news(7))["id"] == 7


# --- deleting -----------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_refuses_without_confirmation_and_previews_the_loss():
    comment = SimpleNamespace(id=1, author=None, content="c", created_on=None)
    client = _client(get=lambda n, **kw: _news(comments=[comment], attachments=[]))
    with patch.object(news_mod, "_get_redmine_client", return_value=client):
        result = await delete_redmine_news(news_id=7)
    assert result["code"] == "CONFIRMATION_REQUIRED"
    assert result["impact"]["title"] == "Release 2.4 is out"
    assert result["impact"]["comments"] == 1


@pytest.mark.asyncio
async def test_delete_does_not_call_redmine_without_confirmation():
    deleted = []
    client = _client(
        get=lambda n, **kw: _news(), delete=lambda n: deleted.append(n) or True
    )
    with patch.object(news_mod, "_get_redmine_client", return_value=client):
        await delete_redmine_news(news_id=7)
    assert deleted == []


@pytest.mark.asyncio
async def test_delete_with_confirmation_reports_what_went_with_it():
    comment = SimpleNamespace(id=1, author=None, content="c", created_on=None)
    deleted = []
    client = _client(
        get=lambda n, **kw: _news(comments=[comment]),
        delete=lambda n: deleted.append(n) or True,
    )
    with patch.object(news_mod, "_get_redmine_client", return_value=client):
        result = await delete_redmine_news(news_id=7, confirm_delete=True)
    assert deleted == [7]
    assert result["success"] is True
    assert result["deleted_news_id"] == 7
    assert result["cascade_deleted"]["comments"] == 1


@pytest.mark.asyncio
async def test_deleting_something_absent_says_so():
    def _get(news_id, **kw):
        raise ResourceNotFoundError

    with patch.object(news_mod, "_get_redmine_client", return_value=_client(get=_get)):
        result = await delete_redmine_news(news_id=404, confirm_delete=True)
    assert result["code"] == "NOT_FOUND"


# --- the named failures ------------------------------------------------


def _client_with_project(modules, **managers):
    """A client whose project read reports ``modules`` as enabled."""
    project = SimpleNamespace(id=1093, name="ZEUS", enabled_modules=list(modules))
    return SimpleNamespace(
        news=SimpleNamespace(**managers),
        project=SimpleNamespace(get=lambda pid, **kw: project),
    )


@pytest.mark.asyncio
async def test_a_403_with_the_module_off_names_the_module():
    from redminelib.exceptions import ForbiddenError

    def _create(**kw):
        raise ForbiddenError

    with patch.object(
        news_mod,
        "_get_redmine_client",
        return_value=_client_with_project(["issue_tracking"], create=_create),
    ):
        result = await news_mod.manage_redmine_news(
            action="create", project_id=1093, title="t", description="d"
        )
    assert result["code"] == "NEWS_MODULE_DISABLED"
    assert result["upstream_status"] == 403


@pytest.mark.asyncio
async def test_a_403_with_the_module_on_is_a_permission_denial():
    """The module is enabled, so the role is what is missing.

    Claiming a disabled module here would send the operator to switch on
    something that is already on.
    """
    from redminelib.exceptions import ForbiddenError

    def _create(**kw):
        raise ForbiddenError

    with patch.object(
        news_mod,
        "_get_redmine_client",
        return_value=_client_with_project(["issue_tracking", "news"], create=_create),
    ):
        result = await news_mod.manage_redmine_news(
            action="create", project_id=1093, title="t", description="d"
        )
    assert result.get("code") != "NEWS_MODULE_DISABLED"
    assert "error" in result


@pytest.mark.asyncio
async def test_an_unreadable_module_list_claims_nothing():
    from redminelib.exceptions import ForbiddenError

    def _create(**kw):
        raise ForbiddenError

    def _project_get(pid, **kw):
        raise Exception("no access to the project either")

    client = SimpleNamespace(
        news=SimpleNamespace(create=_create),
        project=SimpleNamespace(get=_project_get),
    )
    with patch.object(news_mod, "_get_redmine_client", return_value=client):
        result = await news_mod.manage_redmine_news(
            action="create", project_id=1093, title="t", description="d"
        )
    assert result.get("code") != "NEWS_MODULE_DISABLED"


@pytest.mark.asyncio
async def test_a_read_names_the_module_when_the_project_is_known():
    """A 403 on a read is the same module gate, not a write-only concern."""
    from redminelib.exceptions import ForbiddenError

    def _filter(**kw):
        raise ForbiddenError

    with patch.object(
        news_mod,
        "_get_redmine_client",
        return_value=_client_with_project(["issue_tracking"], filter=_filter),
    ):
        result = await list_redmine_news(project_id=1093)
    assert result["code"] == "NEWS_MODULE_DISABLED"


@pytest.mark.asyncio
async def test_a_single_read_refused_outright_claims_nothing():
    """Without a readable item there is no project to check the module on.

    ``get_redmine_news`` knows only the news id, so when reading the item is
    itself refused the module state is unknowable -- and an unknowable state
    is not claimed. In practice Redmine answers 404 rather than 403 here,
    because a news item in a module-less project is simply not visible.
    """
    from redminelib.exceptions import ForbiddenError

    def _get(news_id, **kw):
        raise ForbiddenError

    with patch.object(
        news_mod,
        "_get_redmine_client",
        return_value=_client_with_project(["issue_tracking"], get=_get),
    ):
        result = await get_redmine_news(7)
    assert result.get("code") != "NEWS_MODULE_DISABLED"
    assert "error" in result


@pytest.mark.asyncio
async def test_a_single_read_names_the_module_when_the_item_still_reads():
    """The update path is the realistic case: read allowed, write refused."""
    from redminelib.exceptions import ForbiddenError

    def _update(news_id, **kw):
        raise ForbiddenError

    project = SimpleNamespace(id=1093, name="ZEUS", enabled_modules=["issue_tracking"])
    client = SimpleNamespace(
        news=SimpleNamespace(get=lambda n, **kw: _news(), update=_update),
        project=SimpleNamespace(get=lambda pid, **kw: project),
    )
    with patch.object(news_mod, "_get_redmine_client", return_value=client):
        result = await news_mod.manage_redmine_news(
            action="update", news_id=7, title="neu"
        )
    assert result["code"] == "NEWS_MODULE_DISABLED"


@pytest.mark.asyncio
async def test_a_404_on_create_with_a_readable_project_names_the_endpoint():
    """python-redmine raises no version error, so the 404 has to be read.

    ``News.redmine_version`` is (1, 1, 0) for the whole resource, so a
    server without the write endpoint just 404s the POST. If the project
    reads back fine, the endpoint is what is missing -- not the project.
    """

    def _create(**kw):
        raise ResourceNotFoundError

    with patch.object(
        news_mod,
        "_get_redmine_client",
        return_value=_client_with_project(["news"], create=_create),
    ):
        result = await news_mod.manage_redmine_news(
            action="create", project_id=1093, title="t", description="d"
        )
    assert result["code"] == "NEWS_WRITE_UNSUPPORTED"
    assert "endpoint" in result["error"]
    # The floor belongs in the hint, not in the diagnosis: a 404 here says
    # the endpoint is absent, which no core version explains on its own.
    assert "4.1" in result["hint"]
    assert "4.1" not in result["error"]


@pytest.mark.asyncio
async def test_a_404_with_an_unreadable_project_is_not_blamed_on_the_endpoint():
    def _create(**kw):
        raise ResourceNotFoundError

    def _project_get(pid, **kw):
        raise ResourceNotFoundError

    client = SimpleNamespace(
        news=SimpleNamespace(create=_create),
        project=SimpleNamespace(get=_project_get),
    )
    with patch.object(news_mod, "_get_redmine_client", return_value=client):
        result = await news_mod.manage_redmine_news(
            action="create", project_id=999999, title="t", description="d"
        )
    assert result.get("code") != "NEWS_WRITE_UNSUPPORTED"


@pytest.mark.asyncio
async def test_a_404_on_a_read_is_never_blamed_on_the_version():
    """Reading news works on every Redmine, so that branch is write-only."""

    def _get(news_id, **kw):
        raise ResourceNotFoundError

    with patch.object(
        news_mod,
        "_get_redmine_client",
        return_value=_client_with_project(["news"], get=_get),
    ):
        result = await get_redmine_news(7)
    assert result["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_a_forbidden_delete_names_the_module_from_the_item_it_read():
    from redminelib.exceptions import ForbiddenError

    def _delete(news_id):
        raise ForbiddenError

    project = SimpleNamespace(id=1093, name="ZEUS", enabled_modules=["issue_tracking"])
    client = SimpleNamespace(
        news=SimpleNamespace(get=lambda n, **kw: _news(), delete=_delete),
        project=SimpleNamespace(get=lambda pid, **kw: project),
    )
    with patch.object(news_mod, "_get_redmine_client", return_value=client):
        result = await delete_redmine_news(news_id=7, confirm_delete=True)
    assert result["code"] == "NEWS_MODULE_DISABLED"
