"""
Test runner script for the Redmine MCP server.

This script provides different test execution modes:
- Unit tests only (default)
- Integration tests only  
- All tests
- Specific test files

Usage:
    python run_tests.py                    # Run unit tests only
    python run_tests.py --integration      # Run integration tests only
    python run_tests.py --all             # Run all tests
    python run_tests.py --file test_file   # Run specific test file
    python run_tests.py --coverage        # Run with coverage report
"""
import argparse
import subprocess
import sys
import os


def run_tests(test_type="unit", specific_file=None, coverage=False, verbose=False):
    """Run tests based on the specified type."""
    
    # Base pytest command
    cmd = ["python", "-m", "pytest"]
    
    # Add verbosity
    if verbose:
        cmd.append("-v")
    else:
        cmd.append("-q")
    
    # Add coverage if requested
    if coverage:
        cmd.extend(["--cov=src/redmine_mcp_server", "--cov-report=html", "--cov-report=term"])
    
    # Determine what tests to run
    if specific_file:
        # Run specific test file
        test_file = f"tests/{specific_file}" if not specific_file.startswith("tests/") else specific_file
        cmd.append(test_file)
    elif test_type == "unit":
        # Run unit tests (exclude integration marker)
        cmd.extend(["-m", "not integration", "tests/"])
    elif test_type == "integration":
        # Run integration tests only
        cmd.extend(["-m", "integration", "tests/"])
    elif test_type == "all":
        # Run all tests
        cmd.append("tests/")
    
    # Add test output formatting
    cmd.extend(["--tb=short"])
    
    print(f"Running command: {' '.join(cmd)}")
    print("-" * 60)
    
    # Run the tests
    try:
        result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)) + "/..", 
                              capture_output=False, text=True)
        return result.returncode
    except Exception as e:
        print(f"Error running tests: {e}")
        return 1


def check_dependencies():
    """Check if required test dependencies are installed."""
    required_packages = ["pytest", "pytest-asyncio"]
    
    missing_packages = []
    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("Missing required test dependencies:")
        for package in missing_packages:
            print(f"  - {package}")
        print("\nInstall them with:")
        print(f"uv pip install {' '.join(missing_packages)}")
        return False
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Run tests for Redmine MCP server")
    parser.add_argument("--integration", action="store_true", 
                       help="Run integration tests only")
    parser.add_argument("--all", action="store_true", 
                       help="Run all tests (unit + integration)")
    parser.add_argument("--file", type=str, 
                       help="Run specific test file")
    parser.add_argument("--coverage", action="store_true",
                       help="Run with coverage report")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Verbose output")
    
    args = parser.parse_args()
    
    # Check dependencies first
    if not check_dependencies():
        return 1
    
    # Determine test type
    if args.all:
        test_type = "all"
    elif args.integration:
        test_type = "integration"
    else:
        test_type = "unit"
    
    # Run tests
    return run_tests(
        test_type=test_type,
        specific_file=args.file,
        coverage=args.coverage,
        verbose=args.verbose
    )


if __name__ == "__main__":
    sys.exit(main())
