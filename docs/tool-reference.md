# Tool Reference

Complete documentation for all available Redmine MCP Server tools.

## Project Management

### `list_redmine_projects`

Lists all accessible projects in the Redmine instance.

**Parameters:** None

**Returns:** List of project dictionaries with id, name, identifier, and description

**Example:**
```json
[
  {
    "id": 1,
    "name": "My Project",
    "identifier": "my-project",
    "description": "Project description"
  }
]
```

---

### `summarize_project_status`

Provide a comprehensive summary of project status based on issue activity over a specified time period.

**Parameters:**
- `project_id` (integer, required): The ID of the project to summarize
- `days` (integer, optional): Number of days to analyze. Default: `30`

**Returns:** Comprehensive project status summary including:
- Recent activity metrics (issues created/updated)
- Status, priority, and assignee breakdowns
- Project totals and overall statistics
- Activity insights and trends

**Example:**
```json
{
  "project_id": 1,
  "project_name": "My Project",
  "analysis_period_days": 30,
  "recent_activity": {
    "created_count": 15,
    "updated_count": 42
  },
  "status_breakdown": {
    "New": 5,
    "In Progress": 8,
    "Resolved": 12
  }
}
```

---

## Issue Operations

### `get_redmine_issue`

Retrieve detailed information about a specific Redmine issue.

**Parameters:**
- `issue_id` (integer, required): The ID of the issue to retrieve
- `include_journals` (boolean, optional): Include journals (comments) in result. Default: `true`
- `include_attachments` (boolean, optional): Include attachments metadata. Default: `true`

**Returns:** Issue dictionary with details, journals, and attachments

**Example:**
```json
{
  "id": 123,
  "subject": "Bug in login form",
  "description": "Users cannot login...",
  "status": {"id": 1, "name": "New"},
  "priority": {"id": 2, "name": "Normal"},
  "journals": [...],
  "attachments": [...]
}
```

---

### `list_my_redmine_issues`

Lists issues assigned to the authenticated user with pagination support.

**Parameters:**
- `limit` (integer, optional): Maximum issues to return. Default: `25`, Max: `1000`
- `offset` (integer, optional): Number of issues to skip for pagination. Default: `0`
- `include_pagination_info` (boolean, optional): Return structured response with metadata. Default: `false`
- `**filters` (optional): Additional query parameters (e.g., `status_id`, `project_id`)

**Returns:** List of issue dictionaries assigned to current user, or structured response with pagination metadata

**Example (simple):**
```json
[
  {"id": 1, "subject": "Task 1"},
  {"id": 2, "subject": "Task 2"}
]
```

**Example (with pagination info):**
```json
{
  "issues": [...],
  "pagination": {
    "total": 150,
    "limit": 25,
    "offset": 0,
    "has_next": true,
    "has_prev": false
  }
}
```

---

### `search_redmine_issues`

Search issues using text queries.

**Parameters:**
- `query` (string, required): Text to search for in issues
- `**options` (optional): Additional search options passed to Redmine API

**Returns:** List of matching issue dictionaries

**Example:**
```json
[
  {
    "id": 456,
    "subject": "Search keyword found here",
    "description": "Issue containing the search term..."
  }
]
```

---

### `create_redmine_issue`

Creates a new issue in the specified project.

**Parameters:**
- `project_id` (integer, required): Target project ID
- `subject` (string, required): Issue subject/title
- `description` (string, optional): Issue description. Default: `""`
- `**fields` (optional): Additional Redmine fields (e.g., `priority_id`, `assigned_to_id`, `tracker_id`, `status_id`)

**Returns:** Created issue dictionary

**Example:**
```python
# Create a bug report
create_redmine_issue(
    project_id=1,
    subject="Login button not working",
    description="The login button does not respond to clicks",
    priority_id=3,  # High priority
    tracker_id=1    # Bug tracker
)
```

---

### `update_redmine_issue`

Updates an existing issue with the provided fields.

**Parameters:**
- `issue_id` (integer, required): ID of the issue to update
- `fields` (object, required): Dictionary of fields to update

**Returns:** Updated issue dictionary

**Note:** You can use either `status_id` or `status_name` in fields. When `status_name` is provided, the tool automatically resolves the corresponding status ID.

**Example:**
```python
# Update issue status using status name
update_redmine_issue(
    issue_id=123,
    fields={
        "status_name": "Resolved",
        "notes": "Fixed the issue"
    }
)

# Or use status_id directly
update_redmine_issue(
    issue_id=123,
    fields={
        "status_id": 3,
        "assigned_to_id": 5
    }
)
```

---

## File Operations

### `get_redmine_attachment_download_url`

Get an HTTP download URL for a Redmine attachment. The attachment is downloaded to server storage and a time-limited URL is returned for client access.

**Parameters:**
- `attachment_id` (integer, required): The ID of the attachment to download

**Returns:**
```json
{
    "download_url": "http://localhost:8000/files/12345678-1234-5678-9abc-123456789012",
    "filename": "document.pdf",
    "content_type": "application/pdf",
    "size": 1024,
    "expires_at": "2025-09-22T10:30:00Z",
    "attachment_id": 123
}
```

**Security Features:**
- Server-controlled storage location and expiry policy
- UUID-based filenames prevent path traversal attacks
- No client control over server configuration
- Automatic cleanup of expired files

**Example:**
```python
# Get download URL for an attachment
result = get_redmine_attachment_download_url(attachment_id=456)
print(f"Download from: {result['download_url']}")
print(f"Expires at: {result['expires_at']}")
```

---

### `cleanup_attachment_files`

Removes expired attachment files and provides cleanup statistics.

**Parameters:** None

**Returns:** Cleanup statistics:
- `cleaned_files`: Number of files removed
- `cleaned_bytes`: Total bytes cleaned up
- `cleaned_mb`: Total megabytes cleaned up (rounded)

**Example:**
```json
{
    "cleaned_files": 12,
    "cleaned_bytes": 15728640,
    "cleaned_mb": 15
}
```

**Note:** Automatic cleanup runs in the background based on server configuration. This tool allows manual cleanup on demand.

---

## Deprecated Tools

### `download_redmine_attachment`

**⚠️ DEPRECATED:** This tool will be removed in a future version. Use [`get_redmine_attachment_download_url`](#get_redmine_attachment_download_url) instead.

**Reason for deprecation:** Security and flexibility improvements. The new tool provides:
- Server-controlled storage and expiry
- HTTP download URLs for better client compatibility
- Enhanced security with UUID-based file storage

**Migration:**
```python
# Old way (deprecated)
result = download_redmine_attachment(
    attachment_id=123,
    save_dir="/path/to/save",
    expires_hours=2
)

# New way (recommended)
result = get_redmine_attachment_download_url(attachment_id=123)
# Server controls storage location and expiry
# Use the returned download_url to access the file
```
