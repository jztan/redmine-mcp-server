# Troubleshooting Guide

This guide covers common issues and solutions for the Redmine MCP Server.

## Connection Issues

### Cannot Connect to Redmine Server

**Symptoms:**
- "Connection refused" errors
- "Failed to connect to Redmine" messages
- Server health check fails

**Solutions:**

1. **Verify Redmine URL**
   ```bash
   # Check your .env file
   cat .env | grep REDMINE_URL

   # Test connectivity with curl
   curl -I https://your-redmine-server.com
   ```

2. **Check Network Connectivity**
   - Ensure you can reach the Redmine server from your network
   - Verify no firewall blocking the connection
   - Check if VPN is required for access

3. **Verify Redmine Server is Running**
   - Access your Redmine URL in a web browser
   - Check with your Redmine administrator if server is up

### Network Timeout Errors

**Symptoms:**
- Requests timing out
- "Connection timeout" errors

**Solutions:**

1. **Increase Timeout Settings**
   - Add longer timeout values in your configuration
   - Check if Redmine server is slow or overloaded

2. **Check Network Speed**
   - Test your internet connection
   - Consider using local network if possible

### SSL Certificate Errors

**Symptoms:**
- "SSL certificate verify failed" errors
- "CERTIFICATE_VERIFY_FAILED" messages
- "SSL: CERTIFICATE_VERIFY_FAILED" in connection errors
- "SSLError" or "CertificateError" messages

**Solutions:**

1. **Use HTTPS URLs**
   ```bash
   # In .env file
   REDMINE_URL=https://your-redmine-server.com  # Not http://
   ```

2. **Self-Signed Certificates**

   If your Redmine server uses a self-signed certificate or internal CA, configure the custom CA certificate:

   ```bash
   # In .env file
   REDMINE_URL=https://redmine.company.com
   REDMINE_API_KEY=your_api_key
   REDMINE_SSL_CERT=/path/to/ca-certificate.crt
   ```

   **Supported certificate formats:** `.pem`, `.crt`, `.cer`

   **Obtaining the certificate:**
   ```bash
   # Export certificate from browser (Chrome/Firefox)
   # Or get from system administrator

   # Or download from server (if accessible)
   openssl s_client -connect redmine.company.com:443 -showcerts < /dev/null 2>/dev/null | \
     openssl x509 -outform PEM > ca-cert.pem
   ```

3. **Mutual TLS (Client Certificates)**

   For environments requiring client certificate authentication:

   **Option A: Separate certificate and key files**
   ```bash
   # In .env file
   REDMINE_URL=https://secure.redmine.com
   REDMINE_API_KEY=your_api_key
   REDMINE_SSL_CERT=/path/to/ca-bundle.pem
   REDMINE_SSL_CLIENT_CERT=/path/to/cert.pem,/path/to/key.pem
   ```

   **Option B: Combined certificate file**
   ```bash
   # In .env file
   REDMINE_SSL_CLIENT_CERT=/path/to/combined-cert.pem
   ```

   **Important:** Private keys must be unencrypted (Python requests library requirement)

   **Removing password from encrypted key:**
   ```bash
   openssl rsa -in encrypted-key.pem -out unencrypted-key.pem
   ```

4. **Disable SSL Verification (Development Only)**

   ⚠️ **WARNING:** Only use in development/testing environments!

   ```bash
   # In .env file
   REDMINE_SSL_VERIFY=false
   ```

   Disabling SSL verification makes your connection vulnerable to man-in-the-middle attacks. Never use in production.

5. **Certificate File Not Found**

   **Symptoms:**
   - "SSL certificate not found: /path/to/cert.pem"
   - "FileNotFoundError" for certificate path

   **Solutions:**
   - Verify the certificate file path is correct
   - Use absolute paths instead of relative paths
   - Check file permissions (must be readable)
   ```bash
   # Verify certificate file exists
   ls -la /path/to/ca-cert.pem

   # Check file permissions
   chmod 644 /path/to/ca-cert.pem
   ```

6. **Certificate Path is a Directory**

   **Symptoms:**
   - "SSL certificate path must be a file, not directory"

   **Solutions:**
   - Specify the actual certificate file, not the directory
   ```bash
   # Wrong
   REDMINE_SSL_CERT=/etc/ssl/certs/

   # Correct
   REDMINE_SSL_CERT=/etc/ssl/certs/ca-bundle.crt
   ```

7. **Certificate Validation Errors with Custom CA**

   **Symptoms:**
   - Still getting SSL errors even with `REDMINE_SSL_CERT` configured

   **Solutions:**
   - Verify you have the correct CA certificate (not the server certificate)
   - Ensure certificate chain is complete
   - Test certificate validation:
   ```bash
   # Test SSL connection with custom CA
   openssl s_client -connect redmine.company.com:443 \
     -CAfile /path/to/ca-cert.pem
   ```

8. **Docker Deployment SSL Configuration**

   When using Docker, mount certificates into container:

   ```bash
   # In docker-compose.yml
   volumes:
     - ./certs:/certs:ro
   ```

   ```bash
   # In .env.docker
   REDMINE_SSL_CERT=/certs/ca-cert.pem
   REDMINE_SSL_CLIENT_CERT=/certs/client-cert.pem,/certs/client-key.pem
   ```

**Troubleshooting Checklist:**
- [ ] Verified `REDMINE_URL` uses `https://`
- [ ] Certificate file exists at specified path
- [ ] Certificate file is readable (permissions 644 or similar)
- [ ] Using correct CA certificate (not server certificate)
- [ ] For mutual TLS: client private key is unencrypted
- [ ] For Docker: certificates mounted into container
- [ ] Tested SSL connection with `openssl s_client`

**See also:** [README.md - SSL Certificate Configuration](../README.md#ssl-certificate-configuration) for configuration examples.

---

## Authentication Issues

### API Key Not Working

**Symptoms:**
- "401 Unauthorized" errors
- "Invalid API key" messages

**Solutions:**

1. **Verify API Key**
   ```bash
   # Check your .env file
   cat .env | grep REDMINE_API_KEY
   ```

2. **Generate New API Key**
   - Log into Redmine web interface
   - Go to "My Account" → "API access key"
   - Click "Show" to view or "Reset" to generate new key
   - Update `.env` with new key

3. **Check API Access is Enabled**
   - Ensure Redmine administrator has enabled REST API
   - Check in Redmine: Administration → Settings → API → "Enable REST web service"

### Username/Password Authentication Failed

**Symptoms:**
- "Authentication failed" errors when using username/password

**Solutions:**

1. **Verify Credentials**
   ```bash
   # Check your .env file
   cat .env | grep REDMINE_USERNAME
   cat .env | grep REDMINE_PASSWORD
   ```

2. **Test Credentials**
   - Try logging into Redmine web interface with same credentials
   - Reset password if needed

3. **Use API Key Instead**
   - API key authentication is recommended over username/password
   - More secure and doesn't require password storage

### Permission Denied Errors

**Symptoms:**
- "403 Forbidden" errors
- "You are not authorized to access this resource"

**Solutions:**

1. **Check User Permissions**
   - Verify your Redmine user has necessary project roles
   - Contact project administrator to grant permissions

2. **Project Visibility**
   - Ensure projects are not private or restricted
   - Check project membership settings

---

## Installation Issues

### Import Errors

**Symptoms:**
- `ModuleNotFoundError` or `ImportError`
- "No module named 'redmine_mcp_server'"

**Solutions:**

1. **Install Dependencies**
   ```bash
   # For source installation
   uv pip install -e .

   # For PyPI installation
   pip install redmine-mcp-server
   ```

2. **Activate Virtual Environment**
   ```bash
   # If using virtual environment
   source .venv/bin/activate
   ```

3. **Reinstall Package**
   ```bash
   pip uninstall redmine-mcp-server
   pip install redmine-mcp-server
   ```

### Dependency Conflicts

**Symptoms:**
- "Dependency conflict" errors
- Package version incompatibility errors

**Solutions:**

1. **Use Fresh Virtual Environment**
   ```bash
   # Create new virtual environment
   python -m venv .venv
   source .venv/bin/activate
   pip install redmine-mcp-server
   ```

2. **Update pip and setuptools**
   ```bash
   pip install --upgrade pip setuptools
   ```

### Python Version Incompatibility

**Symptoms:**
- "Python version not supported" errors
- Syntax errors in code

**Solutions:**

1. **Check Python Version**
   ```bash
   python --version  # Should be 3.10 or higher
   ```

2. **Install Correct Python Version**
   - Python 3.10+ required for local installation
   - Use Docker deployment if Python upgrade not possible

---

## Runtime Issues

### Port Conflicts

**Symptoms:**
- "Address already in use" errors
- "Port 8000 is already allocated"

**Solutions:**

1. **Change Server Port**
   ```bash
   # In .env file
   SERVER_PORT=8001  # Use different port
   ```

2. **Find Process Using Port**
   ```bash
   # On macOS/Linux
   lsof -i :8000

   # Kill process if needed
   kill -9 <PID>
   ```

3. **Use Docker Port Mapping**
   ```bash
   # Map to different external port
   docker run -p 8001:8000 redmine-mcp-server
   ```

### File Permission Errors

**Symptoms:**
- "Permission denied" when accessing attachments
- Cannot write to attachments directory

**Solutions:**

1. **Check Directory Permissions**
   ```bash
   # Ensure attachments directory is writable
   chmod 755 ./attachments
   ```

2. **Configure Custom Directory**
   ```bash
   # In .env file
   ATTACHMENTS_DIR=/path/to/writable/directory
   ```

### Attachment Download Failures

**Symptoms:**
- "Failed to download attachment" errors
- File download URLs expire immediately

**Solutions:**

1. **Check Disk Space**
   ```bash
   df -h  # Ensure sufficient space in attachments directory
   ```

2. **Verify Redmine Permissions**
   - Ensure your Redmine user can access attachments
   - Check attachment exists in Redmine

3. **Configure Expiry Time**
   ```bash
   # In .env file
   ATTACHMENT_EXPIRES_MINUTES=120  # Increase expiry time
   ```

### Memory or Performance Issues

**Symptoms:**
- Slow response times
- High memory usage
- Server crashes

**Solutions:**

1. **Enable Automatic Cleanup**
   ```bash
   # In .env file
   AUTO_CLEANUP_ENABLED=true
   CLEANUP_INTERVAL_MINUTES=10
   ```

2. **Monitor Resource Usage**
   ```bash
   # Check server resources
   docker stats  # For Docker deployment
   htop  # For local deployment
   ```

3. **Reduce Pagination Limits**
   - Use smaller `limit` values in `list_my_redmine_issues`
   - Default limit is 25 to prevent token overflow

---

## MCP Client Issues

### Server Not Appearing in MCP Client

**Symptoms:**
- Redmine server not listed in client
- Configuration not recognized

**Solutions:**

1. **Verify Configuration Format**
   - Check configuration matches your client's format
   - See [MCP Client Configuration](../README.md#mcp-client-configuration)

2. **Restart MCP Client**
   - Reload VS Code or restart your MCP client
   - Configuration changes may require restart

3. **Check Server is Running**
   ```bash
   # Test health endpoint
   curl http://localhost:8000/health
   ```

### Tools Not Loading

**Symptoms:**
- MCP client connected but no tools available
- "No tools found" messages

**Solutions:**

1. **Verify Server Started Correctly**
   ```bash
   # Check server logs for errors
   redmine-mcp-server
   ```

2. **Test MCP Endpoint**
   ```bash
   # Should return MCP protocol response
   curl http://localhost:8000/mcp
   ```

3. **Reload Client Configuration**
   - Run MCP client's reload/refresh command
   - Reconnect to server

### HTTP Transport Errors

**Symptoms:**
- "HTTP transport not supported" errors
- "Streamable HTTP failed" messages

**Solutions:**

1. **Use HTTP-to-stdio Bridge** (for clients with limited HTTP support)
   ```json
   {
     "mcpServers": {
       "redmine": {
         "command": "npx",
         "args": ["-y", "mcp-client-http", "http://127.0.0.1:8000/mcp"]
       }
     }
   }
   ```

2. **Verify Client Supports HTTP**
   - Check your MCP client's documentation
   - Some clients require specific transport types

---

## Debug & Logging

### Enable Debug Mode

**For Source Installation:**

Edit `src/redmine_mcp_server/main.py`:
```python
# Set debug mode
mcp.settings.debug = True
```

**For Docker Deployment:**

Add to `.env.docker`:
```bash
DEBUG=true
```

### View Server Logs

**Local Deployment:**
```bash
# Logs appear in terminal where server is running
redmine-mcp-server
```

**Docker Deployment:**
```bash
# View container logs
docker logs <container-id>

# Follow logs in real-time
docker logs -f <container-id>
```

### Common Error Messages

#### "redmine client not initialized"

**Cause:** Environment variables not loaded or invalid credentials

**Solution:**
1. Check `.env` file exists and has correct values
2. Verify credentials are valid
3. Ensure `REDMINE_URL` is set

#### "File not found or expired"

**Cause:** Attachment file was cleaned up or URL expired

**Solution:**
1. Generate new download URL using `get_redmine_attachment_download_url`
2. Increase `ATTACHMENT_EXPIRES_MINUTES` in `.env`

#### "Token limit exceeded"

**Cause:** Too many results returned causing MCP token overflow

**Solution:**
1. Use smaller `limit` values in `list_my_redmine_issues`
2. Use pagination with `offset` parameter
3. Filter results with specific parameters

---

## Getting Additional Help

If your issue isn't covered here:

1. **Check GitHub Issues**
   - Search existing issues: https://github.com/jztan/redmine-mcp-server/issues
   - Look for similar problems and solutions

2. **Create New Issue**
   - Provide detailed description of the problem
   - Include error messages and logs
   - Specify your environment (Python version, OS, deployment method)

3. **Review Documentation**
   - [README](../README.md) - Setup and configuration
   - [Tool Reference](./tool-reference.md) - Tool usage details
   - [CLAUDE.md](../CLAUDE.md) - Development information

4. **Community Support**
   - Check MCP community resources
   - Review python-redmine library documentation
