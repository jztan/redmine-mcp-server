# Changelog

All notable changes to this project will be documented in this file.


The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] - 2025-12-08

### Security
- **Removed private keys from repository** - Addresses GitGuardian secret exposure alert
  - Test SSL certificates now generated dynamically in CI/CD pipeline
  - Added `generate-test-certs.sh` script for local and CI certificate generation
  - Updated `.gitignore` to exclude all generated certificate files
  - Private keys no longer stored in version control

### Added
- **SSL Certificate Configuration** - Comprehensive SSL/TLS support for secure Redmine connections
  - **Self-Signed Certificates** - `REDMINE_SSL_CERT` environment variable for custom CA certificates
    - Support for `.pem`, `.crt`, `.cer` certificate formats
    - Path validation with existence and file type checks
    - Clear error messages for troubleshooting
  - **Mutual TLS (mTLS)** - `REDMINE_SSL_CLIENT_CERT` environment variable for client certificate authentication
    - Support for separate certificate and key files (comma-separated format)
    - Support for combined certificate files
    - Compatibility with unencrypted private keys (Python requests requirement)
  - **SSL Verification Control** - `REDMINE_SSL_VERIFY` environment variable to enable/disable verification
    - Defaults to `true` for security (secure by default)
    - Warning logs when SSL verification is disabled
    - Development/testing flexibility with explicit configuration
  - **Integration Testing** - 9 comprehensive integration tests with real SSL certificates
    - Test certificate generation using OpenSSL
    - Validation of all SSL configuration scenarios
    - Certificate path resolution and error handling tests

### Changed
- Enhanced Redmine client initialization with SSL configuration support
- Updated environment variable parsing for SSL options
- Improved error handling for SSL certificate validation

### Improved
- **Security** - Secure by default with SSL verification enabled
  - Certificate path validation prevents configuration errors
  - Clear warnings for insecure configurations (SSL disabled)
  - Comprehensive logging for SSL setup and errors
- **Flexibility** - Support for various SSL deployment scenarios
  - Self-signed certificates for internal infrastructure
  - Mutual TLS for high-security environments
  - Docker-compatible certificate mounting
- **Documentation** - Extensive updates across all documentation:
  - **README.md** - New SSL Certificate Configuration section with examples
    - Environment variables table updated with SSL options
    - Collapsible sections for different SSL scenarios
    - Link to troubleshooting guide for SSL issues
  - **docs/troubleshooting.md** - Comprehensive SSL troubleshooting section
    - 8 detailed troubleshooting scenarios with solutions
    - OpenSSL command examples for certificate validation
    - Docker deployment SSL configuration guide
    - Troubleshooting checklist for common issues
  - **docs/tool-reference.md** - New Security Best Practices section
    - SSL/TLS configuration best practices
    - Authentication security guidelines
    - File handling security features
    - Docker deployment security recommendations

### Fixed
- **CI/CD** - Added SSL certificate generation step to PyPI publish workflow
  - Tests were failing in GitHub Actions due to missing test certificates
  - Certificate generation now runs before tests in all CI workflows

### Technical Details
- **Test Coverage** - Added 29 comprehensive tests (20 unit + 9 integration)
  - Unit tests for environment variable parsing and SSL configuration logic
  - Integration tests with real certificate files
  - Error handling tests for missing/invalid certificates
- **Certificate Validation** - Robust path validation with clear error messages
  - `Path.resolve()` for symlink resolution
  - File existence and type checks
  - Original and resolved paths in error messages
- **Client Certificate Support** - Flexible format handling
  - Split comma-separated paths with `maxsplit=1`
  - Strip whitespace from paths
  - Support both tuple and single file formats
- **Code Quality** - All changes PEP 8 compliant and formatted with Black
- **Backward Compatibility** - Fully compatible with existing deployments
  - SSL verification enabled by default (same as before)
  - No changes required for users without custom SSL needs
  - Optional SSL configuration for advanced scenarios
## [0.7.1] - 2025-12-02

### Fixed
- **Critical: Redmine client initialization failure when installed via pip** ([#40](https://github.com/jztan/redmine-mcp-server/issues/40))
  - `.env` file is now loaded from the current working directory first, then falls back to package directory
  - Previously, the server only looked for `.env` relative to the installed package location (site-packages), causing "Redmine client not initialized" errors for pip-installed users
  - Added helpful warning messages when `REDMINE_URL` or authentication credentials are missing
  - Removed redundant `load_dotenv()` call from `main.py` to avoid duplicate initialization

### Added
- **Regression Tests** - Added 8 new tests in `test_env_loading.py` to prevent future regressions:
  - Tests for `.env` loading from current working directory
  - Tests for warning messages when configuration is missing
  - Tests for CWD precedence over package directory

### Migration Notes
- **No Breaking Changes** - Existing configurations continue to work
- **Recommended** - Place your `.env` file in the directory where you run the server (current working directory)
- **Fallback** - If no `.env` found in CWD, the package directory is checked as before

## [0.7.0] - 2025-11-29

### Added
- **Search Optimization** - Comprehensive enhancements to `search_redmine_issues()` to prevent MCP token overflow
  - **Pagination Support** - Server-side pagination with `limit` (default: 25, max: 1000) and `offset` parameters
  - **Field Selection** - Optional `fields` parameter for selective field inclusion to reduce token usage
  - **Native Search Filters** - Support for Redmine Search API native filters:
    - `scope` parameter (values: "all", "my_project", "subprojects")
    - `open_issues` parameter for filtering open issues only
  - **Pagination Metadata** - Optional structured response with `include_pagination_info` parameter
  - **Helper Function** - Added `_issue_to_dict_selective()` for efficient field filtering

### Changed
- **Default Behavior** - `search_redmine_issues()` now returns max 25 issues by default (was unlimited)
  - Prevents MCP token overflow (25,000 token limit)
  - Use `limit` parameter to customize page size
  - Fully backward compatible for existing usage patterns

### Improved
- **Performance** - Significant improvements for search operations:
  - Memory efficient: Uses server-side pagination
  - Token efficient: Default limit keeps responses under 2,000 tokens
  - ~95% token reduction possible with minimal field selection
  - ~87% faster response times for large result sets
- **Documentation** - Comprehensive updates:
  - Updated `docs/tool-reference.md` with detailed search parameters and examples
  - Added "When to Use" guidance (search vs list_my_redmine_issues)
  - Documented Search API limitations and filtering capabilities
  - Added performance tips and best practices

### Technical Details
- **Search API Limitations** - Documented that Search API supports text search with scope/open_issues filters only
  - For advanced filtering by project_id, status_id, priority_id, etc., use `list_my_redmine_issues()`
  - Search API does not provide total_count (pagination uses conservative estimation)
- **Test Coverage** - Added 81 comprehensive unit tests:
  - 29 tests for field selection helper
  - 22 tests for pagination support  - 15 tests for field selection integration
  - 15 tests for native filters
- **Code Quality** - All changes are PEP 8 compliant and formatted with Black

### Migration Notes
- **Fully Backward Compatible** - No breaking changes for existing code
- **New Default Limit** - If you need more than 25 results, explicitly set `limit` parameter
- **Field Selection** - `fields=None` (default) returns all fields for backward compatibility
- **Pagination** - Use `include_pagination_info=True` for structured responses with metadata

## [0.6.0] - 2025-10-25

### Changed
- **Dependency Updates** - Updated core dependencies to latest versions
  - `fastapi[standard]` upgraded from >=0.115.12 to >=0.120.0
  - `mcp[cli]` upgraded from >=1.14.1 to >=1.19.0

### Security
- **MCP Security Fix** - Includes security patch from MCP v1.19.0 (CVE-2025-62518)

### Improved
- **FastAPI Enhancements** - Benefits from latest bug fixes and improvements:
  - Mixed Pydantic v2/v1 mode for gradual migration support
  - Fixed `StreamingResponse` behavior with `yield` dependencies
  - Enhanced OpenAPI schema support (array values, external_docs parameter)
  - Improved Pydantic 2.12.0+ compatibility
  - Better validation error handling for Form and File parameters
- **MCP Protocol Improvements** - Enhanced capabilities from latest updates:
  - Tool metadata support in FastMCP decorators
  - OAuth scope selection and step-up authorization
  - Paginated list decorators for prompts, resources, and tools
  - Improved Unicode support for HTTP transport
  - Enhanced documentation structure and testing guidance
  - Better OAuth protected resource metadata handling per RFC 9728

### Notes
- Pydantic v1 support is deprecated in FastAPI v0.119.0 and will be removed in a future version
- All existing functionality remains backward compatible
- No breaking changes for current users
- Python 3.10-3.13 support maintained (Python 3.14 support available in dependencies but not yet tested in this project)

## [0.5.2] - 2025-10-09

### Documentation
- **Major README reorganization** - Comprehensive cleanup for professional, user-focused documentation
  - Created separate documentation guides:
    - `docs/tool-reference.md` - Complete tool documentation with examples
    - `docs/troubleshooting.md` - Comprehensive troubleshooting guide
    - `docs/contributing.md` - Complete developer guide with setup, testing, and contribution guidelines
  - Refactored MCP client configurations with collapsible `<details>` sections
  - Removed development-focused content from README (moved to contributing guide)
  - Streamlined README structure:
    - Cleaner Quick Start with proper navigation
    - Focused Features section (replaced "Comprehensive Testing" with "Pagination Support")
    - Removed redundant sections (Usage, Python Version Compatibility, development notes)
    - Added proper Troubleshooting and Contributing sections
    - Enhanced Additional Resources with all documentation links

### Improved
- **Professional documentation structure** - README now focuses purely on end-user usage
- **Better information architecture** - Clear separation between user docs and developer docs
- **Enhanced discoverability** - All documentation easily accessible with proper linking
- **Cleaner presentation** - Collapsible sections and categorized lists reduce visual clutter
- **Industry-standard pattern** - Documentation structure matches professional open-source projects

### Fixed
- Quick Start .env reference now properly links to Installation section
- Contributing link in quick navigation now points to correct location
- Removed duplicate and redundant information across README
- All internal documentation links verified and corrected

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

[0.8.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.8.0
[0.7.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.7.1
[0.7.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.7.0
[0.6.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.6.0
[0.5.2]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.5.2
[0.5.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.5.1
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

