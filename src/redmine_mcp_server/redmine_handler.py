"""
MCP tools for Redmine integration.

This module provides Model Context Protocol (MCP) tools for interacting with Redmine
project management systems. It includes functionality to retrieve issue details,
list projects, and manage Redmine data through MCP-compatible interfaces.

The module handles authentication via either API key or username/password credentials,
and provides comprehensive error handling for network and authentication issues.

Tools provided:
    - get_redmine_issue: Retrieve detailed information about a specific issue
    - list_redmine_projects: Get a list of all accessible Redmine projects
    - list_my_redmine_issues: List issues with filtering, sorting, and group assignment support

Environment Variables Required:
    - REDMINE_URL: Base URL of the Redmine instance
    - REDMINE_API_KEY: API key for authentication (preferred), OR
    - REDMINE_USERNAME + REDMINE_PASSWORD: Username/password authentication

Dependencies:
    - redminelib: Python library for Redmine API interactions
    - python-dotenv: Environment variable management
    - mcp.server.fastmcp: FastMCP server implementation
"""
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from redminelib import Redmine
from redminelib.exceptions import ResourceNotFoundError
from mcp.server.fastmcp import FastMCP

# Load environment variables from .env file
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env')) # Adjust path to .env

REDMINE_URL = os.getenv("REDMINE_URL")
REDMINE_USERNAME = os.getenv("REDMINE_USERNAME")
REDMINE_PASSWORD = os.getenv("REDMINE_PASSWORD")
REDMINE_API_KEY = os.getenv("REDMINE_API_KEY")

# Initialize Redmine client
# It's better to initialize it once if possible, or handle initialization within tools
# For simplicity, we'll initialize it globally here.
# Ensure error handling if credentials are not set.
if not REDMINE_URL:
    raise ValueError("REDMINE_URL not set in .env file")

try:
    if REDMINE_API_KEY:
        redmine = Redmine(REDMINE_URL, key=REDMINE_API_KEY)
    elif REDMINE_USERNAME and REDMINE_PASSWORD:
        redmine = Redmine(REDMINE_URL, username=REDMINE_USERNAME, password=REDMINE_PASSWORD)
    else:
        raise ValueError("Redmine credentials (API Key or Username/Password) not fully set in .env file")
except Exception as e:
    print(f"Error initializing Redmine client: {e}")
    # Depending on FastMCP, you might want to prevent server start or handle this gracefully
    redmine = None # Set to None so tools can check

# Initialize FastMCP server
mcp = FastMCP("redmine_mcp_tools")


@mcp.tool()
async def get_redmine_issue(issue_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieves details for a specific Redmine issue by its ID.
    Args:
        issue_id: The ID of the Redmine issue.
    Returns:
        A dictionary containing issue details or None if not found or error.
    """
    if not redmine:
        return {"error": "Redmine client not initialized."}
    try:
        # python-redmine is synchronous, so we don't use await here for the library call
        issue = redmine.issue.get(issue_id)
        # Convert issue object to a dictionary for easier serialization
        return {
            "id": issue.id,
            "subject": issue.subject,
            "description": getattr(issue, 'description', ''),
            "project": {"id": issue.project.id, "name": issue.project.name},
            "status": {"id": issue.status.id, "name": issue.status.name},
            "priority": {"id": issue.priority.id, "name": issue.priority.name},
            "author": {"id": issue.author.id, "name": issue.author.name},
            "assigned_to": {"id": issue.assigned_to.id, "name": issue.assigned_to.name} if hasattr(issue, 'assigned_to') else None,
            "created_on": issue.created_on.isoformat() if hasattr(issue, 'created_on') else None,
            "updated_on": issue.updated_on.isoformat() if hasattr(issue, 'updated_on') else None,
        }
    except ResourceNotFoundError:
        return {"error": f"Issue {issue_id} not found."}
    except Exception as e:
        # Log the full error for debugging
        print(f"Error fetching Redmine issue {issue_id}: {e}")
        return {"error": f"An error occurred while fetching issue {issue_id}."}

@mcp.tool()
async def list_redmine_projects() -> List[Dict[str, Any]]:
    """
    Lists all accessible projects in Redmine.
    Returns:
        A list of dictionaries, each representing a project.
    """
    if not redmine:
        return [{"error": "Redmine client not initialized."}]
    try:
        projects = redmine.project.all()
        return [
            {
                "id": project.id,
                "name": project.name,
                "identifier": project.identifier,
                "description": getattr(project, 'description', ''),
                "created_on": project.created_on.isoformat() if hasattr(project, 'created_on') else None,
            }
            for project in projects
        ]
    except Exception as e:
        print(f"Error listing Redmine projects: {e}")
        return [{"error": "An error occurred while listing projects."}]


@mcp.tool()
async def list_my_redmine_issues(
    project_id: Optional[int] = None,
    status_id: Optional[str] = None, # Can be status name like 'open', 'closed' or numeric ID
    assigned_to_id: Optional[str] = 'me', # 'me' or specific user ID
    include_group_assignments: Optional[bool] = True, # Include issues assigned to user's groups
    sort: Optional[str] = None, # e.g., 'priority:desc', 'updated_on:asc'
    limit: Optional[int] = 25,
    offset: Optional[int] = 0
) -> List[Dict[str, Any]]:
    """
    Lists Redmine issues, defaulting to those assigned to the current user 
    and optionally including issues assigned to user's groups, with filtering and sorting options.

    Args:
        project_id: Optional. Filter by a specific project ID.
        status_id: Optional. Filter by status ID or name (e.g., 'open', 'closed').
        assigned_to_id: Optional. Filter by assignee ('me' or specific user ID). Defaults to 'me'.
        include_group_assignments: Optional. Include issues assigned to user's groups. Defaults to True.
        sort: Optional. Sorting criteria (e.g., 'priority:desc', 'updated_on:asc').
        limit: Optional. Number of issues to return. Defaults to 25.
        offset: Optional. Offset for pagination. Defaults to 0.

    Returns:
        A list of dictionaries, each representing an issue, or a list containing an error dictionary.
    """
    if not redmine:
        return [{"error": "Redmine client not initialized."}]

    base_params = {}
    if project_id:
        base_params['project_id'] = project_id
    if status_id:
        base_params['status_id'] = status_id
    if sort:
        base_params['sort'] = sort

    try:
        current_user_id = None
        user_groups = []
        
        # Handle 'me' parameter - get current user info
        if assigned_to_id == 'me':
            try:
                current_user = redmine.user.get('current')
                current_user_id = current_user.id
                
                # Enhanced group detection - try multiple approaches
                if include_group_assignments:
                    user_groups = []
                    
                    # Method 1: Try the standard include='groups' approach
                    try:
                        current_user_with_groups = redmine.user.get('current', include='groups')
                        if hasattr(current_user_with_groups, 'groups') and current_user_with_groups.groups:
                            user_groups = [group.id for group in current_user_with_groups.groups]
                            print(f"Found {len(user_groups)} groups via include='groups': {user_groups}")
                    except Exception as e:
                        print(f"Method 1 (include='groups') failed: {e}")
                    
                    # Method 2: If Method 1 failed, try to discover groups by testing access to known group IDs
                    if not user_groups:
                        print("Attempting group discovery via access testing...")
                        # Test common group IDs that might exist in the system
                        potential_groups = [92, 105, 236]  # Add other known group IDs from system
                        
                        for group_id in potential_groups:
                            try:
                                # Test if we can access issues assigned to this group
                                test_issues = redmine.issue.filter(assigned_to_id=group_id, limit=1)
                                test_list = list(test_issues)
                                if test_list:  # If we can access issues, we likely belong to this group
                                    user_groups.append(group_id)
                                    print(f"Detected group membership: {group_id} (can access {len(test_list)} issues)")
                            except Exception as e:
                                # If we can't access, we're probably not in this group
                                pass
                        
                        if user_groups:
                            print(f"Discovered {len(user_groups)} groups via access testing: {user_groups}")
                        else:
                            print("No groups discovered via access testing")
                    
            except Exception as e:
                print(f"Error fetching current user ID: {e}")
                return [{"error": "Could not determine current user ID for 'me'. Please ensure your API key has user impersonation rights or use a specific user ID."}]
        else:
            # If not 'me', use the provided user ID directly
            current_user_id = assigned_to_id
            include_group_assignments = False  # Don't include groups for other users

        # Collect all issues - both direct assignments and group assignments
        all_issues = []
        seen_issue_ids = set()

        # Get issues assigned directly to the user
        if current_user_id:
            user_params = base_params.copy()
            user_params['assigned_to_id'] = current_user_id
            user_params['limit'] = limit * 2  # Get more to account for deduplication
            user_params['offset'] = offset
            
            print(f"Fetching user-assigned issues for user {current_user_id} with params: {user_params}")
            try:
                user_issues = redmine.issue.filter(**user_params)
                user_issues_list = list(user_issues)
                print(f"Found {len(user_issues_list)} user-assigned issues")
                for issue in user_issues_list:
                    if issue.id not in seen_issue_ids:
                        all_issues.append(issue)
                        seen_issue_ids.add(issue.id)
                        print(f"Added user issue {issue.id}: {issue.subject}")
            except Exception as e:
                print(f"Error fetching user-assigned issues: {e}")

        # Get issues assigned to user's groups
        if include_group_assignments and user_groups:
            print(f"Fetching group-assigned issues for groups: {user_groups}")
            for group_id in user_groups:
                group_params = base_params.copy()
                group_params['assigned_to_id'] = group_id
                group_params['limit'] = limit * 2  # Get more to account for deduplication
                group_params['offset'] = 0  # Start from beginning for group queries
                
                print(f"Fetching issues for group {group_id} with params: {group_params}")
                try:
                    group_issues = redmine.issue.filter(**group_params)
                    group_issues_list = list(group_issues)
                    print(f"Found {len(group_issues_list)} issues for group {group_id}")
                    for issue in group_issues_list:
                        if issue.id not in seen_issue_ids:
                            all_issues.append(issue)
                            seen_issue_ids.add(issue.id)
                            print(f"Added group issue {issue.id}: {issue.subject}")
                        else:
                            print(f"Skipped duplicate issue {issue.id}")
                except Exception as e:
                    print(f"Error fetching group-assigned issues for group {group_id}: {e}")
        else:
            if not include_group_assignments:
                print("Group assignments disabled")
            elif not user_groups:
                print("No user groups detected")
        
        print(f"Total issues collected: {len(all_issues)} (user: {len(all_issues) - len([i for i in all_issues if hasattr(i, 'assigned_to') and hasattr(i.assigned_to, 'id') and i.assigned_to.id != current_user_id])}, group: {len([i for i in all_issues if hasattr(i, 'assigned_to') and hasattr(i.assigned_to, 'id') and i.assigned_to.id != current_user_id])})")

        # Sort issues if needed (since we combined multiple queries)
        if sort and all_issues:
            # Parse sort parameter
            sort_field, sort_order = sort.split(':') if ':' in sort else (sort, 'asc')
            reverse_sort = sort_order.lower() == 'desc'
            
            # Sort by the specified field
            if sort_field == 'updated_on':
                all_issues.sort(key=lambda x: getattr(x, 'updated_on', ''), reverse=reverse_sort)
            elif sort_field == 'created_on':
                all_issues.sort(key=lambda x: getattr(x, 'created_on', ''), reverse=reverse_sort)
            elif sort_field == 'priority':
                all_issues.sort(key=lambda x: getattr(x.priority, 'id', 0) if hasattr(x, 'priority') else 0, reverse=reverse_sort)
            elif sort_field == 'id':
                all_issues.sort(key=lambda x: x.id, reverse=reverse_sort)

        # Apply pagination to the combined and sorted results
        start_idx = offset
        end_idx = start_idx + limit
        paginated_issues = all_issues[start_idx:end_idx]

        # Convert to result format
        result = []
        for issue in paginated_issues:
            result.append({
                "id": issue.id,
                "subject": issue.subject,
                "description": getattr(issue, 'description', ''),
                "project": {"id": issue.project.id, "name": issue.project.name},
                "status": {"id": issue.status.id, "name": issue.status.name},
                "priority": {"id": issue.priority.id, "name": issue.priority.name},
                "author": {"id": issue.author.id, "name": issue.author.name},
                "assigned_to": {"id": issue.assigned_to.id, "name": issue.assigned_to.name} if hasattr(issue, 'assigned_to') else None,
                "created_on": issue.created_on.isoformat() if hasattr(issue, 'created_on') else None,
                "updated_on": issue.updated_on.isoformat() if hasattr(issue, 'updated_on') else None,
            })
        return result
    except Exception as e: # Broad exception for issue filtering
        print(f"Error listing Redmine issues: {e}")
        return [{"error": f"An error occurred while listing issues: {str(e)}"}]


if __name__ == "__main__":
    if not redmine:
        print("Redmine client could not be initialized. Some tools may not work.")
        print("Please check your .env file and Redmine server connectivity.")
    # Initialize and run the server
    mcp.run(transport='stdio')
