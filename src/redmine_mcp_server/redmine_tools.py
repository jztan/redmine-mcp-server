"""
Pure Python tools for Redmine integration - no MCP dependencies.

This module contains the core business logic for Redmine operations, extracted
from MCP handlers to enable easy testing and reuse across different transport modes.

The RedmineTools class provides all Redmine functionality as simple async methods
that can be easily mocked and tested independently of the MCP protocol.
"""

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from redminelib import Redmine
from redminelib.exceptions import ResourceNotFoundError


def get_redmine_client() -> Optional[Redmine]:
    """Initialize and return a Redmine client based on environment variables.
    
    Returns:
        Configured Redmine client or None if configuration is invalid.
    """
    # Load environment variables from .env file
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
    
    REDMINE_URL = os.getenv("REDMINE_URL")
    REDMINE_USERNAME = os.getenv("REDMINE_USERNAME")
    REDMINE_PASSWORD = os.getenv("REDMINE_PASSWORD")
    REDMINE_API_KEY = os.getenv("REDMINE_API_KEY")
    
    if not REDMINE_URL or not (REDMINE_API_KEY or (REDMINE_USERNAME and REDMINE_PASSWORD)):
        return None
    
    try:
        if REDMINE_API_KEY:
            return Redmine(REDMINE_URL, key=REDMINE_API_KEY)
        else:
            return Redmine(REDMINE_URL, username=REDMINE_USERNAME, password=REDMINE_PASSWORD)
    except Exception as e:
        print(f"Error initializing Redmine client: {e}")
        return None


class RedmineTools:
    """Pure Python tools for Redmine operations - no MCP dependencies."""
    
    def __init__(self, redmine_client: Optional[Redmine] = None):
        """Initialize with a Redmine client instance.
        
        Args:
            redmine_client: Configured Redmine client. If None, operations will fail gracefully.
        """
        self.client = redmine_client
    
    def _issue_to_dict(self, issue: Any) -> Dict[str, Any]:
        """Convert a python-redmine Issue object to a serializable dict."""
        assigned = getattr(issue, "assigned_to", None)

        return {
            "id": issue.id,
            "subject": issue.subject,
            "description": getattr(issue, "description", ""),
            "project": {"id": issue.project.id, "name": issue.project.name},
            "status": {"id": issue.status.id, "name": issue.status.name},
            "priority": {"id": issue.priority.id, "name": issue.priority.name},
            "author": {"id": issue.author.id, "name": issue.author.name},
            "assigned_to": {
                "id": assigned.id,
                "name": assigned.name,
            }
            if assigned is not None
            else None,
            "created_on": issue.created_on.isoformat()
            if getattr(issue, "created_on", None) is not None
            else None,
            "updated_on": issue.updated_on.isoformat()
            if getattr(issue, "updated_on", None) is not None
            else None,
        }

    def _journals_to_list(self, issue: Any) -> List[Dict[str, Any]]:
        """Convert journals on an issue object to a list of dicts."""
        raw_journals = getattr(issue, "journals", None)
        if raw_journals is None:
            return []

        journals: List[Dict[str, Any]] = []
        try:
            iterator = iter(raw_journals)
        except TypeError:
            return []

        for journal in iterator:
            notes = getattr(journal, "notes", "")
            if not notes:
                continue
            user = getattr(journal, "user", None)
            journals.append(
                {
                    "id": journal.id,
                    "user": {
                        "id": user.id,
                        "name": user.name,
                    }
                    if user is not None
                    else None,
                    "notes": notes,
                    "created_on": journal.created_on.isoformat() if getattr(journal, "created_on", None) is not None else None,
                }
            )
        return journals

    def _attachments_to_list(self, issue: Any) -> List[Dict[str, Any]]:
        """Convert attachments on an issue object to a list of dicts."""
        raw_attachments = getattr(issue, "attachments", None)
        if raw_attachments is None:
            return []

        attachments: List[Dict[str, Any]] = []
        try:
            iterator = iter(raw_attachments)
        except TypeError:
            return []

        for attachment in iterator:
            attachments.append(
                {
                    "id": attachment.id,
                    "filename": getattr(attachment, "filename", ""),
                    "filesize": getattr(attachment, "filesize", 0),
                    "content_type": getattr(attachment, "content_type", ""),
                    "description": getattr(attachment, "description", ""),
                    "content_url": getattr(attachment, "content_url", ""),
                    "author": {
                        "id": attachment.author.id,
                        "name": attachment.author.name,
                    }
                    if getattr(attachment, "author", None) is not None
                    else None,
                    "created_on": attachment.created_on.isoformat()
                    if getattr(attachment, "created_on", None) is not None
                    else None,
                }
            )
        return attachments

    def _analyze_issues(self, issues: List[Any]) -> Dict[str, Any]:
        """Helper function to analyze a list of issues and return statistics."""
        if not issues:
            return {
                "by_status": {},
                "by_priority": {},
                "by_assignee": {},
                "total": 0,
            }
        
        status_counts = {}
        priority_counts = {}
        assignee_counts = {}
        
        for issue in issues:
            # Count by status
            status_name = getattr(issue.status, 'name', 'Unknown')
            status_counts[status_name] = status_counts.get(status_name, 0) + 1
            
            # Count by priority
            priority_name = getattr(issue.priority, 'name', 'Unknown')
            priority_counts[priority_name] = priority_counts.get(priority_name, 0) + 1
            
            # Count by assignee
            assigned_to = getattr(issue, 'assigned_to', None)
            if assigned_to:
                assignee_name = getattr(assigned_to, 'name', 'Unknown')
                assignee_counts[assignee_name] = assignee_counts.get(assignee_name, 0) + 1
            else:
                assignee_counts['Unassigned'] = assignee_counts.get('Unassigned', 0) + 1
        
        return {
            "by_status": status_counts,
            "by_priority": priority_counts, 
            "by_assignee": assignee_counts,
            "total": len(issues),
        }

    async def get_redmine_issue(
        self, issue_id: int, include_journals: bool = True, include_attachments: bool = True
    ) -> Dict[str, Any]:
        """Retrieve a specific Redmine issue by ID.

        Args:
            issue_id: The ID of the issue to retrieve
            include_journals: Whether to include journals (comments) in the result.
            include_attachments: Whether to include attachments metadata in the result.

        Returns:
            A dictionary containing issue details or error information.
        """
        if not self.client:
            return {"error": "Redmine client not initialized."}
        
        try:
            includes = []
            if include_journals:
                includes.append("journals")
            if include_attachments:
                includes.append("attachments")

            if includes:
                issue = self.client.issue.get(issue_id, include=",".join(includes))
            else:
                issue = self.client.issue.get(issue_id)

            result = self._issue_to_dict(issue)
            if include_journals:
                result["journals"] = self._journals_to_list(issue)
            if include_attachments:
                result["attachments"] = self._attachments_to_list(issue)

            return result
        except ResourceNotFoundError:
            return {"error": f"Issue {issue_id} not found."}
        except Exception as e:
            print(f"Error fetching Redmine issue {issue_id}: {e}")
            return {"error": f"An error occurred while fetching issue {issue_id}."}

    async def list_redmine_projects(self) -> List[Dict[str, Any]]:
        """List all accessible projects in Redmine.
        
        Returns:
            A list of dictionaries representing projects or error information.
        """
        if not self.client:
            return [{"error": "Redmine client not initialized."}]
        
        try:
            projects = self.client.project.all()
            return [
                {
                    "id": project.id,
                    "name": project.name,
                    "identifier": project.identifier,
                    "description": getattr(project, 'description', ''),
                    "created_on": project.created_on.isoformat() if getattr(project, 'created_on', None) is not None else None,
                }
                for project in projects
            ]
        except Exception as e:
            print(f"Error listing Redmine projects: {e}")
            return [{"error": "An error occurred while listing projects."}]

    async def list_my_redmine_issues(self, **filters: Any) -> List[Dict[str, Any]]:
        """List issues assigned to the authenticated user.

        Args:
            **filters: Additional filters for the query.

        Returns:
            A list of issue dictionaries or error information.
        """
        if not self.client:
            return [{"error": "Redmine client not initialized."}]
        
        try:
            issues = self.client.issue.filter(assigned_to_id="me", **filters)
            return [self._issue_to_dict(issue) for issue in issues]
        except Exception as e:
            print(f"Error listing issues assigned to current user: {e}")
            return [{"error": "An error occurred while listing issues."}]

    async def search_redmine_issues(self, query: str, **options: Any) -> List[Dict[str, Any]]:
        """Search Redmine issues matching a query string.

        Args:
            query: Text to search for in issues.
            **options: Additional search options.

        Returns:
            A list of issue dictionaries or error information.
        """
        if not self.client:
            return [{"error": "Redmine client not initialized."}]

        try:
            results = self.client.issue.search(query, **options)
            if results is None:
                return []
            return [self._issue_to_dict(issue) for issue in results]
        except Exception as e:
            print(f"Error searching Redmine issues: {e}")
            return [{"error": "An error occurred while searching issues."}]

    async def create_redmine_issue(
        self,
        project_id: int,
        subject: str,
        description: str = "",
        **fields: Any,
    ) -> Dict[str, Any]:
        """Create a new issue in Redmine.
        
        Args:
            project_id: ID of the project to create issue in.
            subject: Issue subject/title.
            description: Issue description.
            **fields: Additional issue fields.
            
        Returns:
            Dictionary containing created issue details or error information.
        """
        if not self.client:
            return {"error": "Redmine client not initialized."}
        
        try:
            issue = self.client.issue.create(
                project_id=project_id, subject=subject, description=description, **fields
            )
            return self._issue_to_dict(issue)
        except Exception as e:
            print(f"Error creating Redmine issue: {e}")
            return {"error": "An error occurred while creating the issue."}

    async def update_redmine_issue(self, issue_id: int, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing Redmine issue.

        Args:
            issue_id: ID of the issue to update.
            fields: Dictionary of fields to update. Can include 'status_name' for convenience.

        Returns:
            Dictionary containing updated issue details or error information.
        """
        if not self.client:
            return {"error": "Redmine client not initialized."}

        # Convert status name to id if requested
        if "status_name" in fields and "status_id" not in fields:
            name = str(fields.pop("status_name")).lower()
            try:
                statuses = self.client.issue_status.all()
                for status in statuses:
                    if getattr(status, "name", "").lower() == name:
                        fields["status_id"] = status.id
                        break
            except Exception as e:
                print(f"Error resolving status name '{name}': {e}")

        try:
            self.client.issue.update(issue_id, **fields)
            updated_issue = self.client.issue.get(issue_id)
            return self._issue_to_dict(updated_issue)
        except ResourceNotFoundError:
            return {"error": f"Issue {issue_id} not found."}
        except Exception as e:
            print(f"Error updating Redmine issue {issue_id}: {e}")
            return {"error": f"An error occurred while updating issue {issue_id}."}

    async def download_redmine_attachment(
        self, attachment_id: int, save_dir: str = "."
    ) -> Dict[str, Any]:
        """Download a Redmine attachment and return the saved file path.

        Args:
            attachment_id: The ID of the attachment to download.
            save_dir: Directory where the file will be saved.

        Returns:
            Dictionary with file_path or error information.
        """
        if not self.client:
            return {"error": "Redmine client not initialized."}
        
        try:
            attachment = self.client.attachment.get(attachment_id)
            # Ensure the save directory exists to avoid FileNotFoundError
            os.makedirs(save_dir, exist_ok=True)
            file_path = attachment.download(savepath=save_dir)
            return {"file_path": file_path}
        except ResourceNotFoundError:
            return {"error": f"Attachment {attachment_id} not found."}
        except Exception as e:
            print(f"Error downloading Redmine attachment {attachment_id}: {e}")
            return {
                "error": f"An error occurred while downloading attachment {attachment_id}."
            }

    async def summarize_project_status(
        self, project_id: int, days: int = 30
    ) -> Dict[str, Any]:
        """Provide a summary of project status based on issue activity.
        
        Args:
            project_id: The ID of the project to summarize.
            days: Number of days to look back for analysis.
        
        Returns:
            Dictionary containing project status summary or error information.
        """
        if not self.client:
            return {"error": "Redmine client not initialized."}
        
        try:
            # Validate project exists
            try:
                project = self.client.project.get(project_id)
            except ResourceNotFoundError:
                return {"error": f"Project {project_id} not found."}
            
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            date_filter = f">={start_date.strftime('%Y-%m-%d')}"
            
            # Get issues created in the date range
            created_issues = list(self.client.issue.filter(
                project_id=project_id, 
                created_on=date_filter
            ))
            
            # Get issues updated in the date range
            updated_issues = list(self.client.issue.filter(
                project_id=project_id, 
                updated_on=date_filter
            ))
            
            # Analyze created issues
            created_stats = self._analyze_issues(created_issues)
            
            # Analyze updated issues  
            updated_stats = self._analyze_issues(updated_issues)
            
            # Calculate trends
            total_created = len(created_issues)
            total_updated = len(updated_issues)
            
            # Get all project issues for context
            all_issues = list(self.client.issue.filter(project_id=project_id))
            all_stats = self._analyze_issues(all_issues)
            
            return {
                "project": {
                    "id": project.id,
                    "name": project.name,
                    "identifier": getattr(project, 'identifier', ''),
                },
                "analysis_period": {
                    "days": days,
                    "start_date": start_date.strftime('%Y-%m-%d'),
                    "end_date": end_date.strftime('%Y-%m-%d'),
                },
                "recent_activity": {
                    "issues_created": total_created,
                    "issues_updated": total_updated,
                    "created_breakdown": created_stats,
                    "updated_breakdown": updated_stats,
                },
                "project_totals": {
                    "total_issues": len(all_issues),
                    "overall_breakdown": all_stats,
                },
                "insights": {
                    "daily_creation_rate": round(total_created / days, 2),
                    "daily_update_rate": round(total_updated / days, 2),
                    "recent_activity_percentage": round(
                        (total_updated / len(all_issues) * 100) if all_issues else 0, 2
                    ),
                },
            }
            
        except Exception as e:
            print(f"Error summarizing project {project_id}: {e}")
            return {"error": f"An error occurred while summarizing project {project_id}."}