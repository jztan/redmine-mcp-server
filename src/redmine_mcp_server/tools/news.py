"""News tools: read project announcements, and manage them.

Redmine news are project-level announcements -- a title, a one-line summary,
a body, and optionally comments and attachments. Reading has been in the
REST API since Redmine 1.1; writing arrived in 5.1.

Two shapes of this API need care, and both are handled here rather than
passed on to the caller:

- **Writes answer 204 with no body**, create included. python-redmine's
  ``NewsManager`` compensates on create by re-reading
  ``news.filter(**self.params)[0]``. Those params carry the ``project_id``
  that was posted, so the read-back is scoped to the target project rather
  than to the newest news anywhere: the remaining race is someone else
  posting to the *same* project in the same instant. Narrow, but not
  nothing, so the read-back is verified against the title that was sent and
  a create whose result cannot be confirmed says so instead of returning a
  neighbour's record.
- **Two failures arrive as plain HTTP codes** that mean something specific
  here. ``News.redmine_version`` is ``(1, 1, 0)`` for the whole resource,
  so python-redmine raises no version error on a pre-5.1 server: the POST
  simply 404s, which a caller would read as a missing project. And with the
  news module disabled on a project, Redmine answers 403 before it checks
  any permission -- an administrator is refused too. Both get their own
  code, ``NEWS_WRITE_UNSUPPORTED`` and ``NEWS_MODULE_DISABLED``.

The list endpoint takes ``project_id`` as a query parameter rather than in
the path, because python-redmine's ``News.query_filter`` is ``/news.json``
with no placeholder. Redmine reads it either way, and answers 404 for a
project that does not exist.
"""

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import Field
from redminelib.exceptions import ResourceNotFoundError, ResourceSetIndexError

from .._client import _get_redmine_client, logger
from .._decorators import ActionMode, action_dispatch
from .._env import _is_read_only_mode
from .._errors import _READ_ONLY_ERROR, _handle_redmine_error
from .._offload import offloaded
from .._serialization import (
    _attachment_to_dict,
    _included_list,
    _named_ref,
    _safe_isoformat,
    wrap_insecure_content,
)
from .._validation import _is_positive_int
from ..server import mcp

_MAX_LIMIT = 100


def _news_comment_to_dict(comment: Any) -> Dict[str, Any]:
    """Serialize one comment on a news item."""
    return {
        "id": getattr(comment, "id", None),
        "author": _named_ref(getattr(comment, "author", None)),
        # Free-form text a user wrote, so it is wrapped like a journal note.
        "content": wrap_insecure_content(getattr(comment, "content", "")),
        "created_on": _safe_isoformat(getattr(comment, "created_on", None)),
    }


def _news_to_dict(news: Any) -> Dict[str, Any]:
    """Convert a python-redmine News object to a serializable dict.

    ``title`` is left unwrapped for the same reason ``subject`` is on an
    issue: it is short and label-shaped, and downstream consumers render it
    as an identifier. ``summary`` and ``description`` are prose and are
    wrapped, as is every comment's ``content``.

    ``comments`` and ``attachments`` appear only when the request that
    fetched the news asked for the matching include; this reads the payload
    and never fetches.
    """
    result: Dict[str, Any] = {
        "id": getattr(news, "id", None),
        "project": _named_ref(getattr(news, "project", None)),
        "author": _named_ref(getattr(news, "author", None)),
        "title": getattr(news, "title", ""),
        "summary": wrap_insecure_content(getattr(news, "summary", "")),
        "description": wrap_insecure_content(getattr(news, "description", "")),
        "created_on": _safe_isoformat(getattr(news, "created_on", None)),
    }

    comments = _included_list(news, "comments")
    if comments:
        result["comments"] = [_news_comment_to_dict(c) for c in comments]
    attachments = _included_list(news, "attachments")
    if attachments:
        result["attachments"] = [_attachment_to_dict(a) for a in attachments]
    return result


def _classify_write_failure(
    exc: Exception, project_id: Optional[Union[str, int]]
) -> Optional[Dict[str, Any]]:
    """Name the two write failures that arrive as bare HTTP codes.

    A 403 on a news write means the project has the news module switched
    off: Redmine checks the module before any permission, so this refuses an
    administrator too, and reads like a missing right when it is not one.

    A 404 is ambiguous on ``POST /projects/{id}/news.json`` -- either the
    project is gone, or the route is (writing news is Redmine 5.1 and newer,
    and ``News.redmine_version`` is ``(1, 1, 0)`` for the whole resource, so
    python-redmine raises no version error of its own). One extra request on
    the error path tells them apart: if the project reads back fine, the
    route is what is missing.

    Returns ``None`` when the failure is neither, leaving it to the shared
    error handler.
    """
    from redminelib.exceptions import ForbiddenError

    if isinstance(exc, ForbiddenError):
        return {
            "error": (
                "Redmine refused the news write. The project most likely has "
                "the news module switched off."
            ),
            "hint": (
                "Enable it under Project settings > Modules > News. Redmine "
                "checks the module before permissions, so this is refused "
                "even for an administrator. get_project_modules shows what a "
                "project has enabled."
            ),
            "code": "NEWS_MODULE_DISABLED",
            "upstream_status": 403,
            "project_id": project_id,
        }

    if isinstance(exc, ResourceNotFoundError) and project_id is not None:
        try:
            _get_redmine_client().project.get(project_id)
        except Exception:
            return None  # The project is what is missing; let NOT_FOUND stand.
        return {
            "error": (
                "This Redmine does not offer news writing over the REST API. "
                "It arrived in Redmine 5.1."
            ),
            "hint": (
                "The project exists and is readable, so the missing piece is "
                "the endpoint. Reading news works on any version; create and "
                "update need 5.1 or newer."
            ),
            "code": "NEWS_WRITE_UNSUPPORTED",
            "upstream_status": 404,
            "project_id": project_id,
        }
    return None


@mcp.tool()
@offloaded
def list_redmine_news(
    project_id: Optional[Union[str, int]] = None,
    limit: Annotated[int, Field(ge=1, le=_MAX_LIMIT)] = 25,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List Redmine news (project announcements), newest first.

    Without ``project_id`` this spans every project the caller can see.
    Comments and attachments are not included -- the list endpoint does not
    serve them; use ``get_redmine_news`` for one item's full context.

    Args:
        project_id: Restrict to one project (numeric ID or string
            identifier). Redmine narrows the collection server-side, and
            answers 404 for a project that does not exist.
        limit: Maximum news items to return (default 25, max 100).
        offset: Items to skip, for paging.

    Returns:
        A list of news dictionaries ``{id, project, author, title, summary,
        description, created_on}``. On failure, a dict with an ``"error"``
        key, with ``code: NOT_FOUND`` for an unknown project.

    Examples:
        >>> await list_redmine_news(project_id="my-project", limit=5)
        [{"id": 12, "title": "Release 2.4 is out", ...}, ...]
    """
    if project_id is not None and isinstance(project_id, int):
        if not _is_positive_int(project_id):
            return {"error": "project_id must be a positive integer."}

    try:
        filters: Dict[str, Any] = {"limit": min(limit, _MAX_LIMIT), "offset": offset}
        if project_id is not None:
            filters["project_id"] = project_id

        news_items = _get_redmine_client().news.filter(**filters)
        return [_news_to_dict(n) for n in news_items]
    except ResourceNotFoundError:
        return {
            "error": f"Project {project_id!r} not found.",
            "code": "NOT_FOUND",
            "upstream_status": 404,
            "project_id": project_id,
        }
    except Exception as e:
        context = (
            {"resource_type": "project", "resource_id": project_id}
            if project_id is not None
            else {}
        )
        return _handle_redmine_error(e, "listing news", context)


@mcp.tool()
@offloaded
def get_redmine_news(
    news_id: int,
    include_comments: bool = True,
    include_attachments: bool = True,
) -> Dict[str, Any]:
    """Retrieve one news item, with its comments and attachments.

    Args:
        news_id: ID of the news item.
        include_comments: Include the comment thread (default ``True``).
            Comments are where a discussion about an announcement lives, so
            they are on by default -- unlike the issue tools, a news item
            without them is usually just three fields.
        include_attachments: Include attachment metadata (default ``True``).

    Returns:
        A news dictionary; ``comments`` and ``attachments`` are present only
        when requested *and* non-empty. On failure, a dict with an
        ``"error"`` key, with ``code: NOT_FOUND`` for an unknown id.
    """
    if not _is_positive_int(news_id):
        return {"error": "news_id must be a positive integer."}

    includes = []
    if include_comments:
        includes.append("comments")
    if include_attachments:
        includes.append("attachments")

    try:
        news = _get_redmine_client().news.get(
            news_id, include=",".join(includes) if includes else None
        )
        return _news_to_dict(news)
    except ResourceNotFoundError:
        return {
            "error": f"News item {news_id} not found.",
            "code": "NOT_FOUND",
            "upstream_status": 404,
            "news_id": news_id,
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"getting news {news_id}",
            {"resource_type": "news", "resource_id": news_id},
        )


@offloaded
def _create_news_action(
    project_id: Optional[Union[str, int]] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    summary: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    if project_id is None:
        return {"error": "project_id is required for action='create'."}
    if not title or not str(title).strip():
        return {"error": "title is required for action='create'."}
    if not description or not str(description).strip():
        # Redmine validates presence of both, so refusing here turns a 422
        # into a message that names the missing field.
        return {"error": "description is required for action='create'."}

    params: Dict[str, Any] = {
        "project_id": project_id,
        "title": title,
        "description": description,
    }
    if summary is not None:
        params["summary"] = summary

    unconfirmed = {
        "success": True,
        "confirmed": False,
        "code": "CREATE_UNCONFIRMED",
        "warning": (
            "The news item was created, but Redmine answers a news write "
            "with 204 and no body, and reading it back did not return a "
            "record matching the title that was sent -- most likely someone "
            "posted to the same project in the same instant. Look the item "
            "up in the project rather than trusting an id from this call."
        ),
        "sent": {"project_id": project_id, "title": title},
    }

    try:
        created = _get_redmine_client().news.create(**params)
    except ResourceSetIndexError:
        # The create itself succeeded (204); only NewsManager's read-back
        # found nothing. Reporting a failure here would be wrong.
        logger.warning(
            "Created news in project %s but could not read it back.", project_id
        )
        return unconfirmed
    except Exception as e:
        named = _classify_write_failure(e, project_id)
        if named is not None:
            return named
        return _handle_redmine_error(
            e,
            "creating news",
            {"resource_type": "project", "resource_id": project_id},
        )

    if str(getattr(created, "title", "")) != str(title):
        logger.warning(
            "Read-back after creating news in project %s returned %r, not %r.",
            project_id,
            getattr(created, "title", None),
            title,
        )
        return unconfirmed
    return _news_to_dict(created)


@offloaded
def _update_news_action(
    news_id: Optional[int] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    summary: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(news_id):
        return {"error": "news_id is required for action='update'."}
    if title is not None and not str(title).strip():
        return {"error": "title cannot be blank."}
    if description is not None and not str(description).strip():
        return {"error": "description cannot be blank."}

    fields: Dict[str, Any] = {}
    if title is not None:
        fields["title"] = title
    if description is not None:
        fields["description"] = description
    if summary is not None:
        # An empty string is a deliberate clear, so this checks presence.
        fields["summary"] = summary
    if not fields:
        return {"error": "Nothing to update: pass title, summary or description."}

    try:
        _get_redmine_client().news.update(news_id, **fields)
    except ResourceNotFoundError:
        return {
            "error": f"News item {news_id} not found.",
            "code": "NOT_FOUND",
            "upstream_status": 404,
            "news_id": news_id,
        }
    except Exception as e:
        named = _classify_write_failure(e, None)
        if named is not None:
            return named
        return _handle_redmine_error(
            e,
            f"updating news {news_id}",
            {"resource_type": "news", "resource_id": news_id},
        )

    # Redmine answers an update with 204 and no body, so the result is read
    # back rather than assumed -- what is returned is what Redmine stored.
    try:
        return _news_to_dict(_get_redmine_client().news.get(news_id))
    except Exception:
        logger.warning("Updated news %s but could not read it back.", news_id)
        return {
            "success": True,
            "confirmed": False,
            "code": "UPDATE_UNCONFIRMED",
            "news_id": news_id,
            "updated_fields": sorted(fields),
        }


@mcp.tool()
@action_dispatch(
    {
        "create": ActionMode.WRITE,
        "update": ActionMode.WRITE,
    }
)
async def manage_redmine_news(
    action: Literal["create", "update"],
    project_id: Optional[Union[str, int]] = None,
    news_id: Optional[int] = None,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update a Redmine news item (project announcement).

    Needs Redmine 5.1 or newer: writing news over the REST API did not
    exist before that, and an older server answers with an error rather
    than silently doing nothing.

    Deleting is a separate tool, ``delete_redmine_news``, so a deployment
    can offer announcements without offering their destruction.

    Args:
        action: One of ``create``, ``update``.
        project_id: Project to announce in. Required for ``create``;
            ignored by ``update``, since news cannot move between projects.
        news_id: Item to change. Required for ``update``.
        title: Headline. Required for ``create``, optional for ``update``
            (cannot be blank).
        summary: One-line teaser shown in listings. Optional; an empty
            string clears it on ``update``.
        description: The body. Required for ``create``, optional for
            ``update`` (cannot be blank).

    Returns:
        The resulting news dictionary. Where Redmine's bodyless response
        makes the result unverifiable, an envelope with ``confirmed:
        False`` and a ``code`` of ``CREATE_UNCONFIRMED`` /
        ``UPDATE_UNCONFIRMED`` instead of a possibly wrong record. On
        error, ``{"error": "..."}``.

        Blocked in read-only mode (``REDMINE_MCP_READ_ONLY=true``).
    """
    return {
        "create": _create_news_action,
        "update": _update_news_action,
    }


@mcp.tool()
@offloaded
def delete_redmine_news(
    news_id: Optional[int] = None,
    confirm_delete: bool = False,
) -> Dict[str, Any]:
    """Hard-delete a news item via ``DELETE /news/{id}.json``.

    Deletion is **irreversible** and takes the item's comments and
    attachments with it. Like the other destructive tools here, this one
    refuses unless ``confirm_delete=True``, and the refusal carries a
    preview of what would be lost.

    Needs Redmine 5.1 or newer. For the other operations use
    ``manage_redmine_news`` (create, update), ``get_redmine_news`` or
    ``list_redmine_news``.

    Args:
        news_id: ID of the news item to delete.
        confirm_delete: When ``False`` (default), the tool refuses and
            returns the impact preview. Pass ``True`` to actually delete.

    Returns:
        On refusal: ``{"error", "code": "CONFIRMATION_REQUIRED", "hint",
        "impact"}``, where ``impact`` names the title and counts the
        comments and attachments that would go with it.

        On success: ``{"success": True, "deleted_news_id": N,
        "cascade_deleted": {"comments": C, "attachments": A}}``.

        Blocked in read-only mode (``REDMINE_MCP_READ_ONLY=true``).
    """
    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)
    if not _is_positive_int(news_id):
        return {"error": "news_id must be a positive integer."}

    client = _get_redmine_client()

    # Read first, so the preview is real and a missing item is reported as
    # missing rather than as a failed delete.
    try:
        news = client.news.get(news_id, include="comments,attachments")
    except ResourceNotFoundError:
        return {
            "error": f"News item {news_id} not found.",
            "code": "NOT_FOUND",
            "upstream_status": 404,
            "news_id": news_id,
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"reading news {news_id} before deletion",
            {"resource_type": "news", "resource_id": news_id},
        )

    impact = {
        "news_id": news_id,
        "title": getattr(news, "title", ""),
        "comments": len(_included_list(news, "comments")),
        "attachments": len(_included_list(news, "attachments")),
    }

    if not confirm_delete:
        return {
            "error": f"Deleting news item {news_id} needs explicit confirmation.",
            "code": "CONFIRMATION_REQUIRED",
            "hint": (
                "Re-run with confirm_delete=True to delete it. This cannot "
                "be undone, and the comments and attachments counted in "
                "'impact' go with it."
            ),
            "impact": impact,
        }

    try:
        client.news.delete(news_id)
    except ResourceNotFoundError:
        return {
            "error": f"News item {news_id} not found.",
            "code": "NOT_FOUND",
            "upstream_status": 404,
            "news_id": news_id,
        }
    except Exception as e:
        named = _classify_write_failure(e, None)
        if named is not None:
            return named
        return _handle_redmine_error(
            e,
            f"deleting news {news_id}",
            {"resource_type": "news", "resource_id": news_id},
        )

    return {
        "success": True,
        "deleted_news_id": news_id,
        "cascade_deleted": {
            "comments": impact["comments"],
            "attachments": impact["attachments"],
        },
    }
