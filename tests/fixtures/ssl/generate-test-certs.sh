#!/bin/bash
# Generate test SSL certificates for CI/CD
# These certificates are for testing only - do NOT use in production

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Certificate validity (10 years for test certs)
DAYS=3650

echo "Generating test SSL certificates..."

# Generate CA private key and certificate
openssl genrsa -out ca-key.pem 2048
openssl req -new -x509 -days $DAYS -key ca-key.pem -out ca-cert.pem \
    -subj "/C=US/ST=Test/L=Test/O=Test CA/CN=Test CA"

# Generate server private key and CSR
openssl genrsa -out server-key.pem 2048
openssl req -new -key server-key.pem -out server-csr.pem \
    -subj "/C=US/ST=Test/L=Test/O=Test Server/CN=localhost"

# Sign server certificate with CA
openssl x509 -req -days $DAYS -in server-csr.pem -CA ca-cert.pem -CAkey ca-key.pem \
    -CAcreateserial -out server-cert.pem

# Generate client private key and CSR
openssl genrsa -out client-key.pem 2048
openssl req -new -key client-key.pem -out client-csr.pem \
    -subj "/C=US/ST=Test/L=Test/O=Test Client/CN=testclient"

# Sign client certificate with CA
openssl x509 -req -days $DAYS -in client-csr.pem -CA ca-cert.pem -CAkey ca-key.pem \
    -CAcreateserial -out client-cert.pem

# Create combined client certificate (cert + key in one file)
cat client-cert.pem client-key.pem > client-combined.pem

echo "Test certificates generated successfully in $SCRIPT_DIR"
ls -la *.pem
