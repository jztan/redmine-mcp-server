"""Global search tool spanning issues, projects, wiki pages, news, etc."""

from typing import Annotated, Any, Dict, List, Optional

from pydantic import Field
from redminelib.exceptions import VersionMismatchError

from .._cleanup import _ensure_cleanup_started
from .._client import _get_redmine_client
from .._errors import _handle_redmine_error
from .._serialization import wrap_insecure_content
from ..server import mcp


def _resource_to_dict(resource: Any, resource_type: str) -> Dict[str, Any]:
    """
    Convert any Redmine resource to a serializable dict for search results.

    Args:
        resource: Python-redmine resource object (Issue, WikiPage, etc.)
        resource_type: Type identifier ('issues', 'wiki_pages', etc.)

    Returns:
        Dictionary with standardized fields for search results
    """
    base_dict: Dict[str, Any] = {
        "id": getattr(resource, "id", None),
        "type": resource_type,
    }

    # Extract title from various possible attributes
    if hasattr(resource, "subject"):
        base_dict["title"] = resource.subject
    elif hasattr(resource, "title"):
        base_dict["title"] = resource.title
    elif hasattr(resource, "name"):
        base_dict["title"] = resource.name
    else:
        base_dict["title"] = None

    # Extract project info
    if hasattr(resource, "project") and resource.project is not None:
        base_dict["project"] = (
            resource.project.name
            if hasattr(resource.project, "name")
            else str(resource.project)
        )
        base_dict["project_id"] = getattr(resource.project, "id", None)
    elif hasattr(resource, "project_id") and resource.project_id:
        # Fallback for search results that have project_id but not project object
        base_dict["project"] = None
        base_dict["project_id"] = resource.project_id
    else:
        base_dict["project"] = None
        base_dict["project_id"] = None

    # Extract status (issues have status, wiki pages don't)
    if hasattr(resource, "status"):
        base_dict["status"] = (
            resource.status.name
            if hasattr(resource.status, "name")
            else str(resource.status)
        )
    else:
        base_dict["status"] = None

    # Extract updated timestamp
    if hasattr(resource, "updated_on"):
        base_dict["updated_on"] = (
            str(resource.updated_on) if resource.updated_on else None
        )
    else:
        base_dict["updated_on"] = None

    # Extract description/excerpt (first 200 chars)
    if hasattr(resource, "description") and resource.description:
        raw_excerpt = (
            resource.description[:200] + "..."
            if len(resource.description) > 200
            else resource.description
        )
        base_dict["excerpt"] = wrap_insecure_content(raw_excerpt)
    elif hasattr(resource, "text") and resource.text:
        raw_excerpt = (
            resource.text[:200] + "..." if len(resource.text) > 200 else resource.text
        )
        base_dict["excerpt"] = wrap_insecure_content(raw_excerpt)
    else:
        base_dict["excerpt"] = None

    return base_dict


@mcp.tool()
async def search_entire_redmine(
    query: str,
    resources: Optional[List[str]] = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 100,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> Dict[str, Any]:
    """
    Search for issues and wiki pages across the Redmine instance.

    Args:
        query: Text to search for. Case sensitivity controlled by server DB config.
        resources: Filter by resource types. Allowed: ['issues', 'wiki_pages']
                   Default: None (searches both issues and wiki_pages)
        limit: Maximum number of results to return (max 100)
        offset: Pagination offset for server-side pagination

    Returns:
        Dictionary containing search results, counts, and metadata.
        On error, returns {"error": "message"}.

    Note:
        v1.4 Scope Limitation: Only 'issues' and 'wiki_pages' are supported.
        Requires Redmine 3.3.0 or higher for search API support.
    """

    try:
        await _ensure_cleanup_started()

        # Validate and enforce scope limitation (v1.4)
        allowed_types = ["issues", "wiki_pages"]
        if resources:
            resources = [r for r in resources if r in allowed_types]
            if not resources:
                resources = allowed_types  # Fall back to default if all filtered
        else:
            resources = allowed_types

        # Cap limit at 100 (Redmine API maximum)
        limit = min(limit, 100)
        if limit <= 0:
            limit = 100

        # Build search options
        search_options = {
            "resources": resources,
            "limit": limit,
            "offset": offset,
        }

        # Execute search
        categorized_results = _get_redmine_client().search(query, **search_options)

        # Handle empty results (python-redmine returns None)
        if not categorized_results:
            return {
                "results": [],
                "results_by_type": {},
                "total_count": 0,
                "query": query,
            }

        # Process categorized results
        all_results = []
        results_by_type: Dict[str, int] = {}

        for resource_type, resource_set in categorized_results.items():
            # Skip 'unknown' category (plugin resources)
            if resource_type == "unknown":
                continue

            # Skip if not in allowed types
            if resource_type not in allowed_types:
                continue

            # Handle both ResourceSet and dict (for 'unknown')
            if hasattr(resource_set, "__iter__"):
                count = 0
                for resource in resource_set:
                    result_dict = _resource_to_dict(resource, resource_type)
                    all_results.append(result_dict)
                    count += 1
                if count > 0:
                    results_by_type[resource_type] = count

        return {
            "results": all_results,
            "results_by_type": results_by_type,
            "total_count": len(all_results),
            "query": query,
        }

    except VersionMismatchError:
        return {"error": "Search requires Redmine 3.3.0 or higher."}
    except Exception as e:
        return _handle_redmine_error(e, f"searching Redmine for '{query}'")
