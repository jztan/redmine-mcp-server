# Tool Reference

Complete documentation for all available Redmine MCP Server tools.

## Security Best Practices

### SSL/TLS Configuration

The Redmine MCP Server supports comprehensive SSL/TLS configuration for secure connections to your Redmine instance.

**Recommended Practices:**

1. **Always Use HTTPS**
   ```bash
   # In .env file
   REDMINE_URL=https://redmine.company.com  # Use https://, not http://
   ```

2. **Enable SSL Verification (Default)**
   - SSL verification is enabled by default for security
   - Never disable in production environments
   - Only disable for development/testing when absolutely necessary

3. **Self-Signed Certificates**

   For Redmine servers with self-signed certificates or internal CA infrastructure:

   ```bash
   # In .env file
   REDMINE_SSL_CERT=/path/to/ca-certificate.crt
   ```

   **Security Considerations:**
   - Verify certificate authenticity before trusting
   - Obtain certificates from trusted administrators
   - Use absolute paths for certificate files
   - Ensure certificate files have appropriate permissions (644)

4. **Mutual TLS (Client Certificates)**

   For high-security environments requiring client certificate authentication:

   ```bash
   # In .env file
   REDMINE_SSL_CLIENT_CERT=/path/to/cert.pem,/path/to/key.pem
   ```

   **Security Considerations:**
   - Private keys MUST be unencrypted (Python requests library requirement)
   - Store private keys securely with restricted permissions (600)
   - Never commit certificates or keys to version control
   - Rotate client certificates regularly per security policy

5. **Development vs Production**

   ⚠️ **Development Only:**
   ```bash
   REDMINE_SSL_VERIFY=false  # WARNING: Only for development/testing!
   ```

   Disabling SSL verification makes your connection vulnerable to man-in-the-middle attacks. **Never use in production.**

### Authentication Best Practices

1. **API Key Authentication (Recommended)**

   Prefer API key authentication over username/password:

   ```bash
   # In .env file
   REDMINE_API_KEY=your_api_key_here
   ```

   **Benefits:**
   - More secure than password storage
   - Can be revoked without changing password
   - Granular access control
   - Better audit trail

2. **Username/Password Authentication**

   Only use when API key is not available:

   ```bash
   # In .env file
   REDMINE_USERNAME=your_username
   REDMINE_PASSWORD=your_password
   ```

   **Security Considerations:**
   - Never commit credentials to version control
   - Use strong, unique passwords
   - Rotate passwords regularly
   - Consider using API keys instead

3. **Credential Storage**

   - Store credentials in `.env` file (not in code)
   - Add `.env` to `.gitignore`
   - Use environment variables in production
   - Consider using secret management systems (e.g., HashiCorp Vault, AWS Secrets Manager)

### File Handling Security

The server implements multiple security layers for file operations:

1. **Server-Controlled Storage**
   - Attachment storage location controlled by server (`ATTACHMENTS_DIR`)
   - Clients cannot specify arbitrary file paths
   - Prevents directory traversal attacks

2. **UUID-Based File Storage**
   - Files stored with UUID-based names, not original filenames
   - Prevents path manipulation and collision attacks
   - Predictable cleanup and management

3. **Time-Limited Access**
   - Download URLs expire based on server configuration
   - Default expiry: 60 minutes (configurable via `ATTACHMENT_EXPIRES_MINUTES`)
   - Automatic cleanup of expired files

4. **Secure File Serving**
   - Metadata validation before file access
   - Expiry checks on every request
   - No directory listing or browsing

### Docker Deployment Security

When deploying with Docker, follow these additional practices:

1. **Certificate Management**
   ```yaml
   # In docker-compose.yml
   volumes:
     - ./certs:/certs:ro  # Read-only mount
   ```

2. **Environment Variable Security**
   - Use separate `.env.docker` file
   - Never include credentials in Dockerfile
   - Use Docker secrets for sensitive data in production

3. **Network Security**
   - Separate internal binding from external URLs
   - Use reverse proxy (nginx, traefik) for SSL termination
   - Restrict container network access

### Additional Resources

- [SSL Certificate Configuration](../README.md#ssl-certificate-configuration) - Detailed configuration examples
- [Troubleshooting Guide - SSL Errors](./troubleshooting.md#ssl-certificate-errors) - Common SSL issues and solutions
- [Environment Variables](../README.md#environment-variables) - Complete configuration reference

---

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

### `list_redmine_issues`

List Redmine issues with flexible filtering and pagination support. A general-purpose tool for listing issues from Redmine. Supports filtering by project, status, assignee, tracker, priority, and any other Redmine issue filter.

**Parameters:**
- `project_id` (integer or string, optional): Filter by project (numeric ID or string identifier)
- `status_id` (integer, optional): Filter by status ID
- `tracker_id` (integer, optional): Filter by tracker ID
- `assigned_to_id` (integer or string, optional): Filter by assignee. Use a numeric user ID or the special value `'me'` to retrieve issues assigned to the currently authenticated user.
- `priority_id` (integer, optional): Filter by priority ID
- `sort` (string, optional): Sort order (e.g., `"updated_on:desc"`)
- `limit` (integer, optional): Maximum issues to return. Default: `25`, Max: `1000`
- `offset` (integer, optional): Number of issues to skip for pagination. Default: `0`
- `include_pagination_info` (boolean, optional): Return structured response with metadata. Default: `false`
- `fields` (array of strings, optional): List of field names to include in results. Default: all fields
  - Available fields: `id`, `subject`, `description`, `project`, `status`, `priority`, `author`, `assigned_to`, `created_on`, `updated_on`
  - Special values: `["*"]` or `["all"]` for all fields

**Returns:** List of issue dictionaries, or structured response with pagination metadata

**Examples:**

List all issues in a project:
```python
list_redmine_issues(project_id="my-project")
```

Filter by multiple criteria:
```python
list_redmine_issues(
    project_id=1,
    status_id=1,
    assigned_to_id="me",
    sort="updated_on:desc"
)
```

With pagination metadata:
```python
list_redmine_issues(
    project_id=1,
    limit=25,
    offset=50,
    include_pagination_info=True
)
# Returns:
# {
#   "issues": [...],
#   "pagination": {
#     "total": 150,
#     "limit": 25,
#     "offset": 50,
#     "has_next": true,
#     "has_previous": true,
#     "next_offset": 75,
#     "previous_offset": 25
#   }
# }
```

With field selection (reduces token usage):
```python
list_redmine_issues(
    project_id=1,
    fields=["id", "subject", "status"]
)
# Returns: [{"id": 1, "subject": "Bug fix", "status": {...}}, ...]
```

---

### `list_my_redmine_issues`

> **Deprecated:** This tool will be removed in a future release. Use `list_redmine_issues(assigned_to_id='me')` instead.

Convenience wrapper around `list_redmine_issues` that automatically filters by `assigned_to_id='me'`. Supports all the same filters and pagination options.

**Parameters:**
- Same as `list_redmine_issues` (see above)

**Returns:** List of issue dictionaries assigned to current user, or structured response with pagination metadata

**Example:**
```python
# These are equivalent:
list_my_redmine_issues(project_id=1, limit=10)
list_redmine_issues(project_id=1, assigned_to_id="me", limit=10)
```

---

### `search_redmine_issues`

Search issues using text queries with support for pagination, field selection, and native Search API filters.

**Parameters:**
- `query` (string, required): Text to search for in issues
- `limit` (integer, optional): Maximum number of issues to return. Default: `25`, Max: `1000`
- `offset` (integer, optional): Number of issues to skip for pagination. Default: `0`
- `include_pagination_info` (boolean, optional): Return structured response with pagination metadata. Default: `false`
- `fields` (array of strings, optional): List of field names to include in results. Default: `null` (all fields)
  - Available fields: `id`, `subject`, `description`, `project`, `status`, `priority`, `author`, `assigned_to`, `created_on`, `updated_on`
  - Special values: `["*"]` or `["all"]` for all fields
- `scope` (string, optional): Search scope. Default: `"all"`
  - Values: `"all"`, `"my_project"`, `"subprojects"`
- `open_issues` (boolean, optional): Search only open issues. Default: `false`

**Returns:**
- By default: List of issue dictionaries
- With `include_pagination_info=true`: Dictionary with `issues` and `pagination` keys

**When to Use:**
- **Use `search_redmine_issues()`** for text-based searches across issues
- **Use `list_redmine_issues()`** for advanced filtering by project_id, status_id, priority_id, etc.

**Search API Limitations:**
The Search API supports text search with `scope` and `open_issues` filters only. For advanced filtering by specific field values (project_id, status_id, priority_id, etc.), use `list_redmine_issues()` instead.

**Examples:**

Basic search:
```python
search_redmine_issues("bug fix")
```

With pagination:
```python
# First page
search_redmine_issues("performance", limit=10, offset=0)

# Second page
search_redmine_issues("performance", limit=10, offset=10)
```

With pagination metadata:
```python
search_redmine_issues(
    "security",
    limit=25,
    offset=0,
    include_pagination_info=True
)
# Returns:
# {
#   "issues": [...],
#   "pagination": {
#     "limit": 25,
#     "offset": 0,
#     "count": 25,
#     "has_next": true,
#     "has_previous": false,
#     "next_offset": 25,
#     "previous_offset": null
#   }
# }
```

With field selection (token reduction):
```python
# Minimal fields for better performance
search_redmine_issues("urgent", fields=["id", "subject", "status"])
```

With native filters:
```python
# Search only in my projects for open issues
search_redmine_issues(
    "bug",
    scope="my_project",
    open_issues=True
)
```

All features combined:
```python
search_redmine_issues(
    "critical",
    scope="my_project",
    open_issues=True,
    limit=10,
    offset=0,
    fields=["id", "subject", "priority", "status"],
    include_pagination_info=True
)
```

**Performance Tips:**
- Use pagination (default limit: 25) to prevent token overflow
- Use field selection to minimize data transfer and token usage
- Combine pagination + field selection for optimal performance
- Token reduction: ~95% fewer tokens with minimal fields vs all fields

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

## Search & Wiki

### `search_entire_redmine`

Search across issues and wiki pages in the Redmine instance. Requires Redmine 3.3.0 or higher.

**Parameters:**
- `query` (string, required): Text to search for
- `resources` (list, optional): Filter by resource types. Allowed: `["issues", "wiki_pages"]`. Default: both types
- `limit` (integer, optional): Maximum results to return (max 100). Default: 100
- `offset` (integer, optional): Pagination offset. Default: 0

**Returns:**
```json
{
    "results": [
        {
            "id": 123,
            "type": "issues",
            "title": "Bug in login page",
            "project": "Web App",
            "status": "Open",
            "updated_on": "2025-01-15T10:00:00Z",
            "excerpt": "First 200 characters of description..."
        },
        {
            "id": null,
            "type": "wiki_pages",
            "title": "Installation Guide",
            "project": "Documentation",
            "status": null,
            "updated_on": "2025-01-10T14:30:00Z",
            "excerpt": "First 200 characters of wiki text..."
        }
    ],
    "results_by_type": {
        "issues": 1,
        "wiki_pages": 1
    },
    "total_count": 2,
    "query": "installation"
}
```

**Example:**
```python
# Search all resource types
search_entire_redmine(query="installation guide")

# Search only wiki pages
search_entire_redmine(query="setup", resources=["wiki_pages"])

# With pagination
search_entire_redmine(query="bug", limit=25, offset=0)
```

**Notes:**
- Requires Redmine 3.3.0+ for search API support
- v1.4 scope limitation: Only `issues` and `wiki_pages` supported
- Invalid resource types are silently filtered out
- Search is case-sensitive/insensitive based on Redmine server DB config

---

### `get_redmine_wiki_page`

Retrieve full wiki page content from a Redmine project.

**Parameters:**
- `project_id` (string or integer, required): Project identifier (ID number or string identifier)
- `wiki_page_title` (string, required): Wiki page title (e.g., "Installation_Guide")
- `version` (integer, optional): Specific version number. Default: latest version
- `include_attachments` (boolean, optional): Include attachment metadata. Default: true

**Returns:**
```json
{
    "title": "Installation Guide",
    "text": "# Installation\n\nFollow these steps to install...",
    "version": 5,
    "created_on": "2025-01-15T10:00:00Z",
    "updated_on": "2025-01-20T14:30:00Z",
    "author": {
        "id": 123,
        "name": "John Doe"
    },
    "project": {
        "id": 1,
        "name": "My Project"
    },
    "attachments": [
        {
            "id": 456,
            "filename": "diagram.png",
            "filesize": 102400,
            "content_type": "image/png",
            "description": "Architecture diagram",
            "created_on": "2025-01-15T10:00:00Z"
        }
    ]
}
```

**Example:**
```python
# Get latest version
get_redmine_wiki_page(
    project_id="my-project",
    wiki_page_title="Installation_Guide"
)

# Get specific version
get_redmine_wiki_page(
    project_id=123,
    wiki_page_title="Installation",
    version=3
)

# Without attachments
get_redmine_wiki_page(
    project_id="docs",
    wiki_page_title="FAQ",
    include_attachments=False
)
```

**Notes:**
- Use `get_redmine_attachment_download_url()` to download wiki attachments
- Supports both string identifiers (e.g., "my-project") and numeric IDs

---

### `create_redmine_wiki_page`

Create a new wiki page in a Redmine project.

**Parameters:**
- `project_id` (string or integer, required): Project identifier (ID number or string identifier)
- `wiki_page_title` (string, required): Wiki page title (e.g., "Installation_Guide")
- `text` (string, required): Wiki page content (Textile or Markdown depending on Redmine config)
- `comments` (string, optional): Comment for the change log. Default: empty

**Returns:**
```json
{
    "title": "New Page",
    "text": "# New Page\n\nContent here.",
    "version": 1,
    "created_on": "2025-01-15T10:00:00Z",
    "updated_on": "2025-01-15T10:00:00Z",
    "author": {
        "id": 123,
        "name": "John Doe"
    },
    "project": {
        "id": 1,
        "name": "My Project"
    }
}
```

**Example:**
```python
# Create a simple wiki page
create_redmine_wiki_page(
    project_id="my-project",
    wiki_page_title="Getting_Started",
    text="# Getting Started\n\nWelcome to the project!"
)

# Create with change log comment
create_redmine_wiki_page(
    project_id=123,
    wiki_page_title="API_Reference",
    text="# API Reference\n\n## Endpoints\n...",
    comments="Initial API documentation"
)
```

**Notes:**
- Wiki page titles typically use underscores instead of spaces
- Content format (Textile/Markdown) depends on Redmine server configuration
- Requires wiki edit permissions in the target project

---

### `update_redmine_wiki_page`

Update an existing wiki page in a Redmine project.

**Parameters:**
- `project_id` (string or integer, required): Project identifier (ID number or string identifier)
- `wiki_page_title` (string, required): Wiki page title (e.g., "Installation_Guide")
- `text` (string, required): New wiki page content
- `comments` (string, optional): Comment for the change log. Default: empty

**Returns:**
```json
{
    "title": "Installation Guide",
    "text": "# Installation\n\nUpdated content...",
    "version": 6,
    "created_on": "2025-01-10T10:00:00Z",
    "updated_on": "2025-01-20T14:30:00Z",
    "author": {
        "id": 123,
        "name": "John Doe"
    },
    "project": {
        "id": 1,
        "name": "My Project"
    }
}
```

**Example:**
```python
# Update wiki page content
update_redmine_wiki_page(
    project_id="my-project",
    wiki_page_title="Installation_Guide",
    text="# Installation\n\nUpdated installation steps..."
)

# Update with change log comment
update_redmine_wiki_page(
    project_id=123,
    wiki_page_title="FAQ",
    text="# FAQ\n\n## New Questions\n...",
    comments="Added new FAQ entries"
)
```

**Notes:**
- Version number increments automatically on each update
- Redmine maintains version history for rollback
- Requires wiki edit permissions in the target project

---

### `delete_redmine_wiki_page`

Delete a wiki page from a Redmine project.

**Parameters:**
- `project_id` (string or integer, required): Project identifier (ID number or string identifier)
- `wiki_page_title` (string, required): Wiki page title to delete

**Returns:**
```json
{
    "success": true,
    "title": "Obsolete_Page",
    "message": "Wiki page 'Obsolete_Page' deleted successfully."
}
```

**Example:**
```python
# Delete a wiki page
delete_redmine_wiki_page(
    project_id="my-project",
    wiki_page_title="Obsolete_Page"
)

# Delete by numeric project ID
delete_redmine_wiki_page(
    project_id=123,
    wiki_page_title="Old_Documentation"
)
```

**Notes:**
- Deletion is permanent - page and all versions are removed
- Requires wiki delete permissions in the target project
- Child pages (if any) may become orphaned

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