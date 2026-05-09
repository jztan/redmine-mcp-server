"""Wiki page tool: list/get/create/update/delete/rename actions."""

from typing import Any, Dict, List, Optional, Union

from .._client import _get_redmine_client
from .._decorators import ActionMode, action_dispatch
from .._errors import _handle_redmine_error
from .._serialization import (
    _iter_capped,
    _safe_isoformat,
    wrap_insecure_content,
)
from ..server import mcp


def _wiki_page_to_dict(
    wiki_page: Any, include_attachments: bool = True
) -> Dict[str, Any]:
    """Convert a wiki page object to a dictionary.

    Args:
        wiki_page: Redmine wiki page object
        include_attachments: Whether to include attachment metadata

    Returns:
        Dictionary with wiki page data
    """
    result: Dict[str, Any] = {
        "title": wiki_page.title,
        "text": wrap_insecure_content(wiki_page.text),
        "version": wiki_page.version,
    }

    # Add optional timestamp fields
    if hasattr(wiki_page, "created_on"):
        result["created_on"] = (
            str(wiki_page.created_on) if wiki_page.created_on else None
        )
    else:
        result["created_on"] = None

    if hasattr(wiki_page, "updated_on"):
        result["updated_on"] = (
            str(wiki_page.updated_on) if wiki_page.updated_on else None
        )
    else:
        result["updated_on"] = None

    # Add author info
    if hasattr(wiki_page, "author"):
        result["author"] = {
            "id": wiki_page.author.id,
            "name": wiki_page.author.name,
        }

    # Add project info
    if hasattr(wiki_page, "project"):
        result["project"] = {
            "id": wiki_page.project.id,
            "name": wiki_page.project.name,
        }

    # Process attachments if requested
    if include_attachments and hasattr(wiki_page, "attachments"):
        result["attachments"] = []
        for attachment in wiki_page.attachments:
            att_dict = {
                "id": attachment.id,
                "filename": attachment.filename,
                "filesize": attachment.filesize,
                "content_type": attachment.content_type,
                "description": getattr(attachment, "description", ""),
                "created_on": (
                    str(attachment.created_on)
                    if hasattr(attachment, "created_on") and attachment.created_on
                    else None
                ),
            }
            result["attachments"].append(att_dict)

    return result


def _require_wiki_page_title(action: str, wiki_page_title: Any) -> Optional[str]:
    """Return an error message if wiki_page_title is missing/invalid."""
    if not isinstance(wiki_page_title, str) or not wiki_page_title.strip():
        return (
            f"wiki_page_title is required for action '{action}' "
            "and must be a non-empty string."
        )
    return None


async def _list_wiki_pages_action(
    project_id: Optional[Union[str, int]] = None,
    **_: Any,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    try:
        client = _get_redmine_client()
        pages = client.wiki_page.filter(project_id=project_id)
        items: List[Dict[str, Any]] = []
        for page in _iter_capped(pages):
            entry: Dict[str, Any] = {
                "title": getattr(page, "title", None),
                "version": getattr(page, "version", None),
                "created_on": _safe_isoformat(getattr(page, "created_on", None)),
                "updated_on": _safe_isoformat(getattr(page, "updated_on", None)),
            }
            parent = getattr(page, "parent", None)
            if parent is not None:
                entry["parent_title"] = getattr(parent, "title", None)
            items.append(entry)
        return items
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"listing wiki pages in project {project_id}",
            {"resource_type": "wiki pages", "resource_id": project_id},
        )


async def _get_wiki_page_action(
    project_id: Optional[Union[str, int]] = None,
    wiki_page_title: Optional[str] = None,
    version: Optional[int] = None,
    include_attachments: bool = True,
    **_: Any,
) -> Dict[str, Any]:
    title_error = _require_wiki_page_title("get", wiki_page_title)
    if title_error is not None:
        return {"error": title_error}
    try:
        if version:
            wiki_page = _get_redmine_client().wiki_page.get(
                wiki_page_title, project_id=project_id, version=version
            )
        else:
            wiki_page = _get_redmine_client().wiki_page.get(
                wiki_page_title, project_id=project_id
            )
        return _wiki_page_to_dict(wiki_page, include_attachments)
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"fetching wiki page '{wiki_page_title}' in project {project_id}",
            {"resource_type": "wiki page", "resource_id": wiki_page_title},
        )


async def _create_wiki_page_action(
    project_id: Optional[Union[str, int]] = None,
    wiki_page_title: Optional[str] = None,
    text: Optional[str] = None,
    comments: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    title_error = _require_wiki_page_title("create", wiki_page_title)
    if title_error is not None:
        return {"error": title_error}
    if text is None:
        return {"error": "text is required for action 'create'"}

    try:
        wiki_page = _get_redmine_client().wiki_page.create(
            project_id=project_id,
            title=wiki_page_title,
            text=text,
            comments=comments if comments else None,
        )
        return _wiki_page_to_dict(wiki_page)
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"creating wiki page '{wiki_page_title}' in project {project_id}",
            {"resource_type": "wiki page", "resource_id": wiki_page_title},
        )


async def _update_wiki_page_action(
    project_id: Optional[Union[str, int]] = None,
    wiki_page_title: Optional[str] = None,
    text: Optional[str] = None,
    comments: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    title_error = _require_wiki_page_title("update", wiki_page_title)
    if title_error is not None:
        return {"error": title_error}
    if text is None:
        return {"error": "text is required for action 'update'"}

    try:
        _get_redmine_client().wiki_page.update(
            wiki_page_title,
            project_id=project_id,
            text=text,
            comments=comments if comments else None,
        )
        wiki_page = _get_redmine_client().wiki_page.get(
            wiki_page_title, project_id=project_id
        )
        return _wiki_page_to_dict(wiki_page)
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"updating wiki page '{wiki_page_title}' in project {project_id}",
            {"resource_type": "wiki page", "resource_id": wiki_page_title},
        )


async def _delete_wiki_page_action(
    project_id: Optional[Union[str, int]] = None,
    wiki_page_title: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    title_error = _require_wiki_page_title("delete", wiki_page_title)
    if title_error is not None:
        return {"error": title_error}

    try:
        _get_redmine_client().wiki_page.delete(wiki_page_title, project_id=project_id)
        return {
            "success": True,
            "title": wiki_page_title,
            "message": f"Wiki page '{wiki_page_title}' deleted successfully.",
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"deleting wiki page '{wiki_page_title}' in project {project_id}",
            {"resource_type": "wiki page", "resource_id": wiki_page_title},
        )


async def _rename_wiki_page_action(
    project_id: Optional[Union[str, int]] = None,
    wiki_page_title: Optional[str] = None,
    new_title: Optional[str] = None,
    redirect_existing_links: bool = True,
    **_: Any,
) -> Dict[str, Any]:
    title_error = _require_wiki_page_title("rename", wiki_page_title)
    if title_error is not None:
        return {"error": title_error}
    if not isinstance(new_title, str) or not new_title.strip():
        return {"error": "new_title must be a non-empty string."}
    if new_title == wiki_page_title:
        return {"error": "new_title must differ from wiki_page_title."}

    try:
        client = _get_redmine_client()

        # Redmine requires `text` on every wiki update; preserve the
        # existing body so the rename is a pure title change.
        existing = client.wiki_page.get(wiki_page_title, project_id=project_id)
        existing_text = getattr(existing, "text", "") or ""

        update_kwargs: Dict[str, Any] = {
            "project_id": project_id,
            "title": new_title,
            "text": existing_text,
        }
        if redirect_existing_links:
            update_kwargs["redirect_existing_links"] = "1"

        client.wiki_page.update(wiki_page_title, **update_kwargs)

        # If the API user lacks `rename_wiki_pages`, Redmine silently
        # drops the title change. Re-fetch at the new title to confirm.
        try:
            renamed = client.wiki_page.get(new_title, project_id=project_id)
        except Exception:
            return {
                "error": (
                    "Rename appeared to succeed but the page is not "
                    f"reachable at '{new_title}'. The API user may lack "
                    "the 'rename_wiki_pages' permission (Redmine "
                    "silently drops the title change in that case)."
                )
            }

        renamed_dict = _wiki_page_to_dict(renamed, include_attachments=False)
        return {"success": True, **renamed_dict}
    except Exception as e:
        return _handle_redmine_error(
            e,
            (
                f"renaming wiki page '{wiki_page_title}' to "
                f"'{new_title}' in project {project_id}"
            ),
            {"resource_type": "wiki page", "resource_id": wiki_page_title},
        )


@mcp.tool()
@action_dispatch(
    {
        "list": ActionMode.READ,
        "get": ActionMode.READ,
        "create": ActionMode.WRITE,
        "update": ActionMode.WRITE,
        "delete": ActionMode.WRITE,
        "rename": ActionMode.WRITE,
    }
)
async def manage_redmine_wiki_page(
    action: str,
    project_id: Union[str, int],
    wiki_page_title: Optional[str] = None,
    version: Optional[int] = None,
    include_attachments: bool = True,
    text: Optional[str] = None,
    comments: Optional[str] = None,
    new_title: Optional[str] = None,
    redirect_existing_links: bool = True,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List, get, create, update, delete, or rename a Redmine wiki page.

    Args:
        action: One of: ``list``, ``get``, ``create``, ``update``,
            ``delete``, ``rename``.
        project_id: Project identifier (required for all actions).
        wiki_page_title: Wiki page title. Required for all actions
            except ``list``.
        version: Specific version to retrieve (``get`` only, optional).
        include_attachments: Include attachment metadata in ``get``
            response. Default ``True``.
        text: Page content. Required for ``create`` and ``update``.
        comments: Change log comment. Optional for ``create`` and
            ``update``.
        new_title: New title for the page (required for ``rename``).
        redirect_existing_links: When ``True`` (default), the rename
            creates a redirect from ``wiki_page_title`` to ``new_title``.
            Passed to the API as ``"1"`` / ``"0"``.

    Returns:
        ``list``: list of page metadata dicts (no body text).
        ``get`` / ``create`` / ``update``: wiki page dict.
        ``delete``: ``{"success": True, "title": ..., "message": ...}``.
        ``rename``: ``{"success": True, ...}`` with the renamed page's
        metadata to confirm the title change actually applied.
        On error: ``{"error": "..."}``.
    """
    return {
        "list": _list_wiki_pages_action,
        "get": _get_wiki_page_action,
        "create": _create_wiki_page_action,
        "update": _update_wiki_page_action,
        "delete": _delete_wiki_page_action,
        "rename": _rename_wiki_page_action,
    }
