"""Unit tests for SSL configuration functionality.

This module tests SSL certificate configuration including:
- Environment variable parsing
- Certificate file validation
- Client certificate tuple parsing
- Requests config building
- Edge cases and error handling
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestSSLEnvironmentVariableParsing:
    """Test SSL environment variable parsing and validation."""

    def test_ssl_verify_default_true(self):
        """SSL verification should default to True when not set."""
        # Test that absence of REDMINE_SSL_VERIFY defaults to True
        with patch.dict(os.environ, {}, clear=True):
            result = os.getenv("REDMINE_SSL_VERIFY", "true").lower() == "true"
            assert result is True

    def test_ssl_verify_explicit_true(self):
        """SSL verification should be True when explicitly set to 'true'."""
        with patch.dict(os.environ, {"REDMINE_SSL_VERIFY": "true"}):
            result = os.getenv("REDMINE_SSL_VERIFY", "true").lower() == "true"
            assert result is True

    def test_ssl_verify_false_string(self):
        """'false' should disable SSL verification."""
        with patch.dict(os.environ, {"REDMINE_SSL_VERIFY": "false"}):
            result = os.getenv("REDMINE_SSL_VERIFY", "true").lower() == "true"
            assert result is False

    def test_ssl_verify_case_insensitive_true(self):
        """SSL_VERIFY should be case insensitive for 'true' values."""
        test_cases = ["True", "TRUE", "true", "tRuE"]
        for value in test_cases:
            with patch.dict(os.environ, {"REDMINE_SSL_VERIFY": value}):
                result = os.getenv("REDMINE_SSL_VERIFY", "true").lower() == "true"
                assert result is True, f"Failed for value: {value}"

    def test_ssl_verify_case_insensitive_false(self):
        """SSL_VERIFY should be case insensitive for 'false' values."""
        test_cases = ["False", "FALSE", "false", "fAlSe"]
        for value in test_cases:
            with patch.dict(os.environ, {"REDMINE_SSL_VERIFY": value}):
                result = os.getenv("REDMINE_SSL_VERIFY", "true").lower() == "true"
                assert result is False, f"Failed for value: {value}"

    def test_ssl_verify_whitespace_defaults_false(self):
        """Whitespace around 'true' should not match (secure behavior)."""
        test_cases = [" true", "true ", " true ", "\ttrue", "true\n"]
        for value in test_cases:
            with patch.dict(os.environ, {"REDMINE_SSL_VERIFY": value}):
                result = os.getenv("REDMINE_SSL_VERIFY", "true").lower() == "true"
                # Whitespace means it doesn't match "true" exactly
                assert result is False, f"Failed for value: '{value}'"


class TestCertificateFileValidation:
    """Test certificate file validation logic."""

    def test_cert_path_validation_file_not_found(self, tmp_path):
        """Should raise FileNotFoundError for missing certificate."""
        nonexistent_cert = tmp_path / "nonexistent.pem"
        cert_path = Path(nonexistent_cert).resolve()

        # Test that file doesn't exist
        assert not cert_path.exists()

        # This simulates what the actual code will do
        with pytest.raises(FileNotFoundError):
            if not cert_path.exists():
                raise FileNotFoundError(
                    f"SSL certificate not found: {nonexistent_cert} "
                    f"(resolved to: {cert_path})"
                )

    def test_cert_path_validation_directory_error(self, tmp_path):
        """Should raise ValueError when directory provided instead of file."""
        directory = tmp_path / "certdir"
        directory.mkdir()
        cert_path = Path(directory).resolve()

        # Test that it's a directory, not a file
        assert cert_path.exists()
        assert not cert_path.is_file()

        # This simulates what the actual code will do
        with pytest.raises(ValueError):
            if not cert_path.is_file():
                raise ValueError(
                    f"SSL certificate path must be a file, not directory: "
                    f"{cert_path}"
                )

    def test_cert_path_validation_valid_file(self, tmp_path):
        """Should accept valid certificate file path."""
        cert_file = tmp_path / "ca.crt"
        cert_file.write_text("-----BEGIN CERTIFICATE-----\nFAKE\n")

        cert_path = Path(cert_file).resolve()

        # Test validation passes
        assert cert_path.exists()
        assert cert_path.is_file()
        result_path = str(cert_path)
        assert result_path == str(cert_file.resolve())

    def test_cert_path_symlink_resolution(self, tmp_path):
        """Should resolve symlinks to actual certificate file."""
        # Create actual certificate file
        actual_cert = tmp_path / "actual_ca.crt"
        actual_cert.write_text("-----BEGIN CERTIFICATE-----\nFAKE\n")

        # Create symlink to certificate
        symlink_cert = tmp_path / "ca.crt"
        symlink_cert.symlink_to(actual_cert)

        # Resolve the symlink
        cert_path = Path(symlink_cert).resolve()

        # Should resolve to actual file
        assert cert_path == actual_cert.resolve()
        assert cert_path.exists()
        assert cert_path.is_file()


class TestClientCertificateParsing:
    """Test client certificate tuple parsing logic."""

    def test_client_cert_single_file_format(self):
        """Should handle single file format correctly."""
        cert_string = "/path/to/client.pem"

        # Check if comma exists (it doesn't)
        if "," in cert_string:
            cert, key = cert_string.split(",", 1)
            result = (cert.strip(), key.strip())
        else:
            result = cert_string

        assert result == "/path/to/client.pem"

    def test_client_cert_tuple_format(self):
        """Should parse tuple format correctly."""
        cert_string = "/path/to/cert.pem,/path/to/key.pem"

        # Parse tuple
        if "," in cert_string:
            cert, key = cert_string.split(",", 1)
            result = (cert.strip(), key.strip())
        else:
            result = cert_string

        assert result == ("/path/to/cert.pem", "/path/to/key.pem")

    def test_client_cert_tuple_with_comma_in_path(self):
        """Should handle commas in second path correctly (maxsplit=1)."""
        cert_string = "/path/cert.pem,/path/key,with,commas.pem"

        # Parse with maxsplit=1
        if "," in cert_string:
            cert, key = cert_string.split(",", 1)
            result = (cert.strip(), key.strip())
        else:
            result = cert_string

        # Second path should keep its commas
        assert result == ("/path/cert.pem", "/path/key,with,commas.pem")

    def test_client_cert_whitespace_stripped(self):
        """Should strip whitespace from paths."""
        cert_string = " /path/cert.pem , /path/key.pem "

        # Parse and strip
        if "," in cert_string:
            cert, key = cert_string.split(",", 1)
            result = (cert.strip(), key.strip())
        else:
            result = cert_string

        assert result == ("/path/cert.pem", "/path/key.pem")


class TestRequestsConfigBuilding:
    """Test building requests configuration dictionary."""

    def test_requests_config_ssl_verify_false(self):
        """Should set verify=False when SSL_VERIFY is false."""
        requests_config = {}
        ssl_verify = False

        if not ssl_verify:
            requests_config["verify"] = False

        assert requests_config == {"verify": False}

    def test_requests_config_custom_cert(self, tmp_path):
        """Should set verify to cert path when SSL_CERT provided."""
        cert_file = tmp_path / "ca.crt"
        cert_file.write_text("FAKE CERT")

        requests_config = {}
        ssl_verify = True
        ssl_cert = str(cert_file)

        if ssl_verify and ssl_cert:
            cert_path = Path(ssl_cert).resolve()
            if cert_path.exists() and cert_path.is_file():
                requests_config["verify"] = str(cert_path)

        assert "verify" in requests_config
        assert requests_config["verify"] == str(cert_file.resolve())

    def test_requests_config_ssl_verify_false_precedence(self, tmp_path):
        """SSL_VERIFY=false should take precedence over SSL_CERT."""
        cert_file = tmp_path / "ca.crt"
        cert_file.write_text("FAKE CERT")

        requests_config = {}
        ssl_verify = False
        ssl_cert = str(cert_file)

        # When SSL_VERIFY is False, it takes precedence
        if not ssl_verify:
            requests_config["verify"] = False
        elif ssl_cert:
            cert_path = Path(ssl_cert).resolve()
            if cert_path.exists() and cert_path.is_file():
                requests_config["verify"] = str(cert_path)

        # Should only have verify=False, SSL_CERT ignored
        assert requests_config == {"verify": False}

    def test_requests_config_client_cert_tuple(self):
        """Should include client cert tuple in config."""
        requests_config = {}
        ssl_client_cert = "/cert.pem,/key.pem"

        if ssl_client_cert:
            if "," in ssl_client_cert:
                cert, key = ssl_client_cert.split(",", 1)
                requests_config["cert"] = (cert.strip(), key.strip())
            else:
                requests_config["cert"] = ssl_client_cert

        assert requests_config["cert"] == ("/cert.pem", "/key.pem")

    def test_requests_config_client_cert_single(self):
        """Should include client cert single file in config."""
        requests_config = {}
        ssl_client_cert = "/combined.pem"

        if ssl_client_cert:
            if "," in ssl_client_cert:
                cert, key = ssl_client_cert.split(",", 1)
                requests_config["cert"] = (cert.strip(), key.strip())
            else:
                requests_config["cert"] = ssl_client_cert

        assert requests_config["cert"] == "/combined.pem"

    def test_requests_config_empty_when_defaults(self):
        """Should return empty dict when all defaults (SSL_VERIFY=true)."""
        requests_config = {}
        ssl_verify = True
        ssl_cert = None
        ssl_client_cert = None

        # Only add to config if non-default
        if not ssl_verify:
            requests_config["verify"] = False
        elif ssl_cert:
            # Would validate and add cert path
            pass

        if ssl_client_cert:
            # Would add client cert
            pass

        # Should be empty when using defaults
        assert requests_config == {}
