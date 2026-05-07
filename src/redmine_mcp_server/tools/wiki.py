"""Wiki page tool — list/get/create/update/delete/rename actions."""

from typing import Any, Dict, List, Optional, Union

from .._cleanup import _ensure_cleanup_started
from .._client import _get_redmine_client
from .._env import _is_read_only_mode
from .._errors import _READ_ONLY_ERROR, _handle_redmine_error
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


@mcp.tool()
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
    _valid_actions = {"list", "get", "create", "update", "delete", "rename"}
    if action not in _valid_actions:
        return {
            "error": (
                f"Invalid action '{action}'. "
                "Allowed: list, get, create, update, delete, rename"
            )
        }

    if action == "list":
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

    # All non-list actions require wiki_page_title.
    if not isinstance(wiki_page_title, str) or not wiki_page_title.strip():
        return {
            "error": (
                f"wiki_page_title is required for action '{action}' "
                "and must be a non-empty string."
            )
        }

    if action == "get":
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

    elif action == "create":
        if text is None:
            return {"error": "text is required for action 'create'"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

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

    elif action == "update":
        if text is None:
            return {"error": "text is required for action 'update'"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

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

    elif action == "delete":
        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            _get_redmine_client().wiki_page.delete(
                wiki_page_title, project_id=project_id
            )
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

    else:  # action == "rename"
        # Title validation runs before the read-only check so the
        # per-action structure matches the rest of this tool. The original
        # PR #98 ``rename_wiki_page`` checked read-only first; that ordering
        # only differs from this one when an invalid ``new_title`` is sent
        # while read-only mode is on.
        if not isinstance(new_title, str) or not new_title.strip():
            return {"error": "new_title must be a non-empty string."}
        if new_title == wiki_page_title:
            return {"error": "new_title must differ from wiki_page_title."}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

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
