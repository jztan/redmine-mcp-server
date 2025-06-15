"""
Connection test script for Redmine MCP server.

This script tests the basic connection to a Redmine instance using either 
username/password or API key authentication. It can be run standalone or 
as part of the test suite.

Usage:
    python test_connection.py                 # Run as standalone script
    pytest test_connection.py                 # Run as pytest
    pytest test_connection.py -v              # Run with verbose output
"""
import os
import sys
import pytest
from redminelib import Redmine
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))


class TestRedmineConnection:
    """Test class for Redmine connection functionality."""

    def test_environment_variables_exist(self):
        """Test that required environment variables are set."""
        redmine_url = os.environ.get("REDMINE_URL", "")
        username = os.environ.get("REDMINE_USERNAME", "")
        password = os.environ.get("REDMINE_PASSWORD", "")
        api_key = os.environ.get("REDMINE_API_KEY", "")

        if not redmine_url:
            pytest.skip("REDMINE_URL not configured")
        
        # Either username/password or API key should be set
        has_username_password = all([username, password])
        has_api_key = bool(api_key)
        
        assert has_username_password or has_api_key, (
            "Either REDMINE_USERNAME/REDMINE_PASSWORD or REDMINE_API_KEY must be set"
        )

    @pytest.mark.integration
    def test_redmine_connection_with_credentials(self):
        """Test Redmine connection using configured credentials."""
        redmine_url = os.environ.get("REDMINE_URL", "")
        username = os.environ.get("REDMINE_USERNAME", "")
        password = os.environ.get("REDMINE_PASSWORD", "")
        api_key = os.environ.get("REDMINE_API_KEY", "")
        
        if not redmine_url:
            pytest.skip("REDMINE_URL not configured")
        
        # Try API key first, then username/password
        if api_key:
            redmine = Redmine(redmine_url, key=api_key)
            auth_method = "API Key"
        elif username and password:
            redmine = Redmine(redmine_url, username=username, password=password)
            auth_method = f"Username/Password ({username})"
        else:
            pytest.skip("No valid authentication credentials configured")
        
        try:
            # Test connection by fetching projects
            projects = list(redmine.project.all())
            print(f"\nSuccessfully connected to {redmine_url}")
            print(f"Authentication method: {auth_method}")
            print(f"Found {len(projects)} accessible projects")
            
            if projects:
                print(f"First project: {projects[0].name}")
            
            assert True  # Connection successful
            
        except Exception as e:
            pytest.fail(f"Failed to connect to Redmine using {auth_method}: {e}")

    @pytest.mark.integration
    def test_redmine_user_access(self):
        """Test that the authenticated user has proper access."""
        redmine_url = os.environ.get("REDMINE_URL", "")
        username = os.environ.get("REDMINE_USERNAME", "")
        password = os.environ.get("REDMINE_PASSWORD", "")
        api_key = os.environ.get("REDMINE_API_KEY", "")
        
        if not redmine_url:
            pytest.skip("REDMINE_URL not configured")
        
        if api_key:
            redmine = Redmine(redmine_url, key=api_key)
        elif username and password:
            redmine = Redmine(redmine_url, username=username, password=password)
        else:
            pytest.skip("No valid authentication credentials configured")
        
        try:
            # Test various access levels
            projects = list(redmine.project.all())
            print(f"\nAccess test results:")
            print(f"- Can access {len(projects)} projects")
            
            # Try to get current user info (if available)
            try:
                current_user = redmine.user.get('current')
                print(f"- Current user: {current_user.firstname} {current_user.lastname}")
                print(f"- User email: {getattr(current_user, 'mail', 'N/A')}")
            except:
                print("- Current user info: Not accessible")
            
            # Try to access issues from first project (if any)
            if projects:
                try:
                    first_project = projects[0]
                    issues = list(redmine.issue.filter(project_id=first_project.id, limit=5))
                    print(f"- Can access {len(issues)} issues from '{first_project.name}'")
                except Exception as e:
                    print(f"- Issue access from '{first_project.name}': Limited ({str(e)[:50]})")
            
            assert len(projects) > 0, "User should have access to at least one project"
            
        except Exception as e:
            pytest.fail(f"Failed to test user access: {e}")


def main():
    """Main function for standalone execution."""
    print("Redmine Connection Test")
    print("=" * 50)
    
    redmine_url = os.environ.get("REDMINE_URL", "")
    username = os.environ.get("REDMINE_USERNAME", "")
    password = os.environ.get("REDMINE_PASSWORD", "")
    api_key = os.environ.get("REDMINE_API_KEY", "")
    
    print(f"Redmine URL: {redmine_url}")
    print(f"Username: {username}")
    print(f"Password: {'*' * len(password) if password else 'Not set'}")
    print(f"API Key: {'*' * len(api_key) if api_key else 'Not set'}")
    print()

    # Check if we have either username/password or API key
    has_username_password = all([redmine_url, username, password])
    has_api_key = all([redmine_url, api_key])
    
    if not (has_username_password or has_api_key):
        print("Error: Missing required environment variables.")
        print("Please either set:")
        print("  - REDMINE_URL, REDMINE_USERNAME, and REDMINE_PASSWORD, or")
        print("  - REDMINE_URL and REDMINE_API_KEY")
        print("You can use a .env file or set them directly in the environment.")
        sys.exit(1)

    try:
        # Create Redmine connection
        if api_key:
            redmine = Redmine(redmine_url, key=api_key)
            auth_method = "API Key"
        else:
            redmine = Redmine(redmine_url, username=username, password=password)
            auth_method = "Username/Password"
        
        print(f"Attempting connection using {auth_method}...")
        
        # Test connection
        projects = list(redmine.project.all())
        print("✓ Redmine connection established successfully.")
        print(f"✓ Found {len(projects)} accessible projects")
        
        if projects:
            print(f"✓ First project: {projects[0].name}")
            
            # Try to get an issue from the first project
            try:
                issues = list(redmine.issue.filter(project_id=projects[0].id, limit=1))
                if issues:
                    print(f"✓ Can access issues (example: Issue #{issues[0].id})")
                else:
                    print("ℹ No issues found in first project")
            except Exception as e:
                print(f"⚠ Limited issue access: {e}")
        else:
            print("⚠ No projects found - check user permissions")
            
        print("\n✅ Connection test completed successfully!")
        return 0
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print("\nTroubleshooting tips:")
        print("1. Check your REDMINE_URL is correct and accessible")
        print("2. Verify your credentials (username/password or API key)")
        print("3. Ensure your user has proper permissions in Redmine")
        print("4. Check if your Redmine server requires specific authentication methods")
        return 1


if __name__ == "__main__":
    sys.exit(main())
