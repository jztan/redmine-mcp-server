# Changelog

All notable changes to this project will be documented in this file.


The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.1] - 2025-10-08

### Documentation
- **Updated MCP client configurations** - Comprehensive update to all MCP client setup instructions
  - VS Code: Added native MCP support with CLI, Command Palette, and manual configuration methods
  - Codex CLI: New section with CLI command and TOML configuration format
  - Kiro: Updated to use mcp-client-http bridge for HTTP transport compatibility
  - Generic clients: Expanded with both HTTP and command-based configuration formats
  - Removed Continue extension section (replaced by VS Code native support)
- All configurations verified against official documentation and real-world examples

### Improved
- Enhanced README MCP client configuration section for better user experience
- Clearer installation instructions for various MCP-compatible clients
- More accurate configuration examples reflecting current client capabilities

## [0.5.0] - 2025-09-25

### Added
- **Python 3.10+ support** - Expanded compatibility from Python 3.13+ to Python 3.10+
- CI/CD matrix testing across Python 3.10, 3.11, 3.12, and 3.13 versions
- Python version compatibility matrix in documentation
- GitHub Actions workflows for multi-version testing before PyPI publication

### Changed
- **BREAKING**: Minimum Python requirement lowered from 3.13+ to 3.10+
- Updated project classifiers to include Python 3.10, 3.11, and 3.12
- Enhanced CI/CD pipeline with comprehensive multi-version testing
- Version bumped to 0.5.0 for major compatibility expansion

### Improved
- **10x larger potential user base** with Python 3.10+ support
- Full backward compatibility maintained across all Python versions
- Zero source code changes required for compatibility expansion
- Enhanced documentation with deployment-specific Python version guidance
- Updated all metadata files (server.json, roadmap.md) for version consistency

### Fixed
- Docker deployment script now correctly uses `.env.docker` instead of `.env`
- Maintains proper deployment compatibility (local uses `.env`, Docker uses `.env.docker`)

### Technical
- Configuration-only implementation approach for maximum safety
- Ultra-minimal development setup (Python 3.13.1 local, CI handles multi-version)
- All 71 tests validated across Python 3.10-3.13 via GitHub Actions
- Maintained Docker deployment with Python 3.13 for optimal performance

## [0.4.5] - 2025-09-24

### Improved
- Enhanced PyPI installation documentation with step-by-step instructions
- Simplified installation process with clearer configuration examples
- Updated development documentation with improved setup guidance
- Streamlined package management and dependency handling

### Documentation
- Added comprehensive PyPI installation guide as primary installation method
- Improved environment configuration examples with practical defaults
- Enhanced README structure for better user onboarding experience
- Updated development workflow documentation

## [0.4.4] - 2025-09-23

### Fixed
- PyPI badges and links in README now point to correct package name `redmine-mcp-server`
- Previously pointed to old package name `mcp-redmine`

## [0.4.3] - 2025-09-23

### Added
- MCP Registry support with server.json configuration
- MCP server name identifier in README for registry validation

### Changed
- Updated README with registry identification metadata
- Version bump for PyPI republication with registry validation support

## [0.4.2] - 2025-09-23

### Added
- PyPI package publishing support as `redmine-mcp-server`
- Console script entry point: `redmine-mcp-server` command
- Comprehensive package metadata for PyPI distribution
- GitHub Actions workflow for automated PyPI publishing

### Changed
- Updated package name from `mcp-redmine` to `redmine-mcp-server` for PyPI
- Enhanced pyproject.toml with full package metadata and classifiers
- Added main() function for console script execution

### Improved
- Better package discoverability with keywords and classifications
- Professional package structure following PyPI best practices
- Automated release workflow for seamless publishing

## [0.4.1] - 2025-09-23

### Fixed
- GitHub Actions CI test failure in security validation tests
- Updated test assertions to handle Redmine client initialization state properly
- Security validation tests now pass consistently in CI environments

### Improved
- Enhanced GitHub Actions workflow with manual dispatch trigger
- Added verbose test output for better CI debugging
- Improved test reliability across different environments

## [0.4.0] - 2025-09-22

### Added
- `get_redmine_attachment_download_url()` - Secure replacement for attachment downloads
- Comprehensive security validation test suite
- Server-controlled storage and expiry policies for enhanced security

### Changed
- Updated MCP library to v1.14.1
- Integration tests now create their own test attachments for reliability
- Attachment files always use UUID-based directory structure

### Deprecated
- `download_redmine_attachment()` - Use `get_redmine_attachment_download_url()` instead
  - ⚠️ SECURITY: `save_dir` parameter vulnerable to path traversal (CWE-22, CVSS 7.5)
  - `expires_hours` parameter exposes server policies to clients
  - Will be removed in v0.5.0

### Fixed
- Path traversal vulnerability in attachment downloads eliminated
- Integration test no longer skipped due to missing attachments

### Security
- **CRITICAL**: Fixed path traversal vulnerability in attachment downloads (CVSS 7.5)
- Removed client control over server storage configuration
- Enhanced logging for security events and deprecated function usage

## [0.3.1] - 2025-09-21

### Fixed
- Integration test compatibility with new attachment download API format
- Test validation now properly checks HTTP download URLs instead of file paths
- Comprehensive validation of all attachment response fields (download_url, filename, content_type, size, expires_at, attachment_id)

## [0.3.0] - 2025-09-21

### Added
- **Automatic file cleanup system** with configurable intervals and expiry times
- `AUTO_CLEANUP_ENABLED` environment variable for enabling/disabling automatic cleanup (default: true)
- `CLEANUP_INTERVAL_MINUTES` environment variable for cleanup frequency (default: 10 minutes)
- `ATTACHMENT_EXPIRES_MINUTES` environment variable for default attachment expiry (default: 60 minutes)
- Background cleanup task with lazy initialization via MCP tool calls
- Cleanup status endpoint (`/cleanup/status`) for monitoring background task
- `CleanupTaskManager` class for managing cleanup task lifecycle
- Enhanced health check endpoint with cleanup task initialization
- Comprehensive file management configuration documentation in README

### Changed
- **BREAKING**: `CLEANUP_INTERVAL_HOURS` replaced with `CLEANUP_INTERVAL_MINUTES` for finer control
- Default attachment expiry configurable via environment variable instead of hardcoded 24 hours
- Cleanup task now starts automatically when first MCP tool is called (lazy initialization)
- Updated `.env.example` with new minute-based configuration options

### Improved
- More granular control over cleanup timing with minute-based intervals
- Better resource management with automatic cleanup task lifecycle
- Enhanced monitoring capabilities with cleanup status endpoint
- Clearer documentation with practical configuration examples for development and production

## [0.2.1] - 2025-09-20

### Added
- HTTP file serving endpoint (`/files/{file_id}`) for downloaded attachments
- Secure UUID-based file URLs with automatic expiry (24 hours default)
- New `file_manager.py` module for attachment storage and cleanup management
- `cleanup_attachment_files` MCP tool for expired file management
- PUBLIC_HOST/PUBLIC_PORT environment variables for external URL generation
- PEP 8 compliance standards and development tools (flake8, black)
- Storage statistics tracking for attachment management

### Changed
- **BREAKING**: `download_redmine_attachment` now returns `download_url` instead of `file_path`
- Attachment downloads now provide HTTP URLs for external access
- Docker URL generation fixed (uses localhost instead of 0.0.0.0)
- Dependencies optimized (httpx moved to dev/test dependencies)

### Fixed
- Docker container URL accessibility issues for downloaded attachments
- URL generation for external clients in containerized environments

### Improved
- Code quality with full PEP 8 compliance across all Python modules
- Test coverage for new HTTP URL return format
- Documentation updated with file serving details

## [0.2.0] - 2025-09-20

### Changed
- **BREAKING**: Migrated from FastAPI/SSE to FastMCP streamable HTTP transport
- **BREAKING**: MCP endpoint changed from `/sse` to `/mcp`
- Updated server architecture to use FastMCP's native HTTP capabilities
- Simplified initialization and removed FastAPI dependency layer

### Added
- Native FastMCP streamable HTTP transport support
- Claude Code CLI setup command documentation
- Stateless HTTP mode for better scalability
- Smart issue summarization tool with comprehensive project analytics

### Improved
- Better MCP protocol compliance with native FastMCP implementation
- Reduced complexity by removing custom FastAPI/SSE layer
- Updated all documentation to reflect new transport method
- Enhanced health check endpoint with service identification

### Migration Notes
- Existing MCP clients need to update endpoint from `/sse` to `/mcp`
- Claude Code users can now use: `claude mcp add --transport http redmine http://127.0.0.1:8000/mcp`
- Server initialization simplified with `mcp.run(transport="streamable-http")`

## [0.1.6] - 2025-06-19
### Added
- New MCP tool `search_redmine_issues` for querying issues by text.

## [0.1.5] - 2025-06-18
### Added
- `get_redmine_issue` can now return attachment metadata via a new
  `include_attachments` parameter.
- New MCP tool `download_redmine_attachment` for downloading attachments.

## [0.1.4] - 2025-05-28

### Removed
- Deprecated `get_redmine_issue_comments` tool. Use `get_redmine_issue` with
  `include_journals=True` to retrieve comments.

### Changed
- `get_redmine_issue` now includes issue journals by default. A new
  `include_journals` parameter allows opting out of comment retrieval.

## [0.1.3] - 2025-05-27

### Added
- New MCP tool `list_my_redmine_issues` for retrieving issues assigned to the current user
- New MCP tool `get_redmine_issue_comments` for retrieving issue comments
## [0.1.2] - 2025-05-26

### Changed
- Roadmap moved to its own document with updated plans
- Improved README badges and links

### Added
- New MCP tools `create_redmine_issue` and `update_redmine_issue` for managing issues
- Documentation updates describing the new tools
- Integration tests for issue creation and update
- Integration test for Redmine issue management

## [0.1.1] - 2025-05-25

### Changed
- Updated project documentation with correct repository URLs
- Updated LICENSE with proper copyright (2025 Kevin Tan and contributors)
- Enhanced VS Code integration documentation
- Improved .gitignore to include test coverage files


## [0.1.0] - 2025-05-25

### Added
- Initial release of Redmine MCP Server
- MIT License for open source distribution
- Core MCP server implementation with FastAPI and SSE transport
- Two primary MCP tools:
  - `get_redmine_issue(issue_id)` - Retrieve detailed issue information
  - `list_redmine_projects()` - List all accessible Redmine projects
- Comprehensive authentication support (username/password and API key)
- Modern Python project structure with uv package manager
- Complete testing framework with 20 tests:
  - 10 unit tests for core functionality
  - 7 integration tests for end-to-end workflows
  - 3 connection validation tests
- Docker containerization support:
  - Multi-stage Dockerfile with security hardening
  - Docker Compose configuration with health checks
  - Automated deployment script with comprehensive management
  - Production-ready container setup with non-root user
- Comprehensive documentation:
  - Detailed README.md with installation and usage instructions
  - Complete API documentation with examples
  - Docker deployment guide
  - Testing framework documentation
- Git Flow workflow implementation with standard branching strategy
- Environment configuration templates and examples
- Advanced test runner with coverage reporting and flexible execution

### Technical Features
- **Architecture**: FastAPI application with Server-Sent Events (SSE) transport
- **Security**: Authentication with Redmine instances, non-root Docker containers
- **Testing**: pytest framework with mocks, fixtures, and comprehensive coverage
- **Deployment**: Docker support with automated scripts and health monitoring
- **Documentation**: Complete module docstrings and user guides
- **Development**: Modern Python toolchain with uv, Git Flow, and automated testing

### Dependencies
- Python 3.13+
- FastAPI with standard extensions
- MCP CLI tools
- python-redmine for Redmine API integration
- Docker for containerization
- pytest ecosystem for testing

### Compatibility
- Compatible with Redmine 3.x and 4.x instances
- Supports both username/password and API key authentication
- Works with Docker and docker-compose
- Tested on macOS and Linux environments

[0.5.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.5.0
[0.4.5]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.4.5
[0.4.4]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.4.4
[0.4.3]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.4.3
[0.4.2]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.4.2
[0.4.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.4.1
[0.4.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.4.0
[0.3.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.3.1
[0.3.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.3.0
[0.2.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.2.1
[0.2.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.2.0
[0.1.6]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.6
[0.1.5]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.5
[0.1.4]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.4
[0.1.3]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.3
[0.1.2]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.2
[0.1.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.1
[0.1.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.0

