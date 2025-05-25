"""
Configuration file for pytest.

This file configures pytest markers and test settings for the Redmine MCP server tests.
"""
import pytest


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark tests as integration tests (require actual Redmine connection)"
    )
    config.addinivalue_line(
        "markers", "unit: mark tests as unit tests (use mocks, no external dependencies)"
    )


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment before running tests."""
    import os
    import sys
    
    # Add src to Python path if not already there
    src_path = os.path.join(os.path.dirname(__file__), '..', 'src')
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    
    # Set test environment variable
    os.environ['TESTING'] = 'true'
    
    yield
    
    # Cleanup after tests
    if 'TESTING' in os.environ:
        del os.environ['TESTING']


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Fixture to mock environment variables for testing."""
    monkeypatch.setenv("REDMINE_URL", "https://test-redmine.example.com")
    monkeypatch.setenv("REDMINE_USERNAME", "test_user")
    monkeypatch.setenv("REDMINE_PASSWORD", "test_password")
    monkeypatch.setenv("SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("SERVER_PORT", "8000")


@pytest.fixture
def mock_api_key_env(monkeypatch):
    """Fixture to mock API key authentication environment."""
    monkeypatch.setenv("REDMINE_URL", "https://test-redmine.example.com")
    monkeypatch.setenv("REDMINE_API_KEY", "test_api_key_12345")
    monkeypatch.setenv("SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("SERVER_PORT", "8000")
    # Remove username/password if they exist
    monkeypatch.delenv("REDMINE_USERNAME", raising=False)
    monkeypatch.delenv("REDMINE_PASSWORD", raising=False)
