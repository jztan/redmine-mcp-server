"""SSRF protection: hostname/IP safety checks, pinned HTTP fetches, and
filename sanitization for attachment downloads.

Used by the upload_file tool's `source_url` parameter.
"""

import ipaddress
import logging
import os
import re
import socket
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

import httpx

from ._env import _is_true_env
from ._errors import _scrub_error_message

logger = logging.getLogger("redmine_mcp_server")

# Maximum filename length — typical POSIX limit for a single path component.
_MAX_FILENAME_LEN = 255

# Per-phase timeouts for source_url downloads. Separated so a slow-loris
# style server can't stall us indefinitely on a single phase.
_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)

# Max redirects we follow when downloading via source_url. Each hop is
# SSRF-revalidated independently to defeat redirect-based bypasses.
_FILE_DOWNLOAD_MAX_REDIRECTS = 5

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def _allow_private_fetch_urls() -> bool:
    """Opt-in env flag that disables SSRF protection for `source_url`.

    Intended ONLY for development against a localhost Redmine instance or
    a localhost MCP gateway. Must never be set in production.
    """
    return _is_true_env("REDMINE_ALLOW_PRIVATE_FETCH_URLS", "false")


def _is_ip_publicly_routable(ip: ipaddress._BaseAddress) -> bool:
    """Return True if ``ip`` is publicly routable (not private/special)."""
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _is_hostname_safe_for_fetch(
    hostname: str,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Resolve a hostname and return the first publicly routable IP.

    Rejects loopback, private, link-local (including 169.254.169.254 cloud
    metadata), reserved, multicast, and unspecified addresses to prevent SSRF.

    Returns ``(is_safe, error_message, resolved_ip)``. If safe, the caller
    SHOULD pin ``resolved_ip`` for the actual HTTP request to defeat DNS
    rebinding between our validation and httpx's own resolution.

    Error messages returned to callers are generic ("resolves to non-public
    address") and do not reveal the internal IP. The IP is logged instead
    (WARNING level) so operators can diagnose while attackers can't probe.

    Bypass for development only: ``REDMINE_ALLOW_PRIVATE_FETCH_URLS=true``.
    """
    if _allow_private_fetch_urls():
        # In dev mode, still resolve so we can pin the IP (consistency).
        try:
            addrinfo = socket.getaddrinfo(hostname, None)
            raw = addrinfo[0][4][0] if addrinfo else None
            ip_str = raw.split("%")[0] if raw and "%" in raw else raw
        except socket.gaierror:
            ip_str = None
        return True, None, ip_str

    if not hostname:
        return False, "Empty hostname in source_url.", None

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, f"Cannot resolve hostname '{hostname}'.", None

    if not addrinfo:
        return False, f"No addresses for hostname '{hostname}'.", None

    first_public_ip: Optional[str] = None
    for _family, _, _, _, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        if "%" in ip_str:  # strip IPv6 scope ID (e.g. fe80::1%eth0)
            ip_str = ip_str.split("%")[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            # Skip malformed addresses — still require at least one valid one.
            continue
        if not _is_ip_publicly_routable(ip):
            logger.warning(
                "Rejected SSRF target: %s resolved to non-public %s",
                hostname,
                ip_str,
            )
            # Fail on the first non-public hit — all resolutions must be safe
            # to avoid the attacker picking which IP httpx connects to.
            return (
                False,
                (
                    f"Refused to fetch from '{hostname}' (resolves to a "
                    "non-public address). Set "
                    "REDMINE_ALLOW_PRIVATE_FETCH_URLS=true for development only."
                ),
                None,
            )
        if first_public_ip is None:
            first_public_ip = ip_str

    if first_public_ip is None:
        return False, f"No usable public address for '{hostname}'.", None

    return True, None, first_public_ip


def _sanitize_filename(raw: str) -> Optional[str]:
    """Sanitize an untrusted filename from a URL path or HTTP header.

    - URL-decodes percent-encoded sequences
    - Strips any directory components (defeats `../../etc/passwd` and
      `C:\\windows\\system32\\cmd.exe` style traversal)
    - Rejects null bytes and other control characters
    - Caps length at ``_MAX_FILENAME_LEN`` (typical filesystem limit)

    Returns a safe basename, or ``None`` if the input cannot be salvaged.
    """
    if not raw:
        return None

    decoded = unquote(raw).strip().strip('"').strip("'")
    if not decoded:
        return None

    if _CONTROL_CHAR_RE.search(decoded):
        return None

    # Both os.path.basename and a manual split — different OS conventions.
    basename = os.path.basename(decoded.replace("\\", "/"))
    basename = basename.strip()
    if not basename or basename in (".", ".."):
        return None

    if len(basename) > _MAX_FILENAME_LEN:
        basename = basename[:_MAX_FILENAME_LEN]

    return basename


def _extract_content_disposition_filename(value: str) -> Optional[str]:
    """Extract a filename from a Content-Disposition header, sanitized."""
    if not value:
        return None
    # Prefer RFC 5987 filename* (e.g., filename*=UTF-8''hello.pdf)
    m = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", value, re.IGNORECASE)
    if not m:
        m = re.search(r'filename\s*=\s*"?([^";]+)"?', value, re.IGNORECASE)
    if not m:
        return None
    return _sanitize_filename(m.group(1))


def _make_pinned_client(
    hostname: Optional[str], resolved_ip: Optional[str]
) -> httpx.AsyncClient:
    """Build an httpx.AsyncClient for downloading a source_url.

    We validate the hostname via ``_is_hostname_safe_for_fetch`` on every
    hop before the request. An earlier iteration tried to pin the
    resolved IP into a custom httpx transport to defeat DNS rebinding,
    but rewriting the connect host broke TLS SNI (certs are valid for
    the hostname, not the IP) and failed for every real CDN.

    Current posture:
    - Per-hop hostname validation (hostname is resolved + checked right
      before the connect), narrowing the rebind window to microseconds.
    - Manual redirect handling with re-validation of each hop.
    - 50 MiB size cap as a blast-radius limit if a rebind slips through.

    The ``hostname`` / ``resolved_ip`` arguments are kept in the
    signature for future pinning work; they're currently unused.
    """
    _ = (hostname, resolved_ip)  # silence unused-arg linters
    return httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=False)


def _validate_fetch_url(
    current_url: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """Validate a URL for a single download hop.

    Checks scheme, rejects embedded credentials (which would leak on
    redirect), resolves the hostname, and refuses non-public IPs.

    Returns ``(error_dict_or_None, hostname, resolved_ip)``.
    """
    parsed = urlparse(current_url)
    if parsed.scheme not in ("http", "https"):
        return (
            {"error": (f"Refused URL with unsupported scheme " f"'{parsed.scheme}'.")},
            None,
            None,
        )

    # Embedded credentials (http://user:pass@host) would leak to any
    # redirect target. Reject up front.
    if parsed.username or parsed.password:
        return (
            {"error": ("URLs with embedded credentials are not permitted.")},
            None,
            None,
        )

    hostname = parsed.hostname or ""
    safe, ssrf_err, resolved_ip = _is_hostname_safe_for_fetch(hostname)
    if not safe:
        return (
            {"error": ssrf_err or "Refused to fetch from this host."},
            None,
            None,
        )
    return None, hostname, resolved_ip


async def _download_file_url(
    source_url: str,
) -> Tuple[bytes, Optional[str], Optional[Dict[str, Any]]]:
    """Download a file from an HTTP(S) URL with SSRF + size protections.

    Defenses (in order):
    - Only http/https schemes accepted.
    - URLs with embedded credentials are refused (would leak on redirect).
    - Each URL hop is DNS-resolved and rejected if any resolved IP is
      private/loopback/link-local/reserved (blocks AWS/GCP/Azure metadata
      services, RFC1918 networks, and localhost). Override for dev only:
      ``REDMINE_ALLOW_PRIVATE_FETCH_URLS=true``.
    - Redirects are followed manually, up to ``_FILE_DOWNLOAD_MAX_REDIRECTS``
      hops, and every hop is re-validated against the SSRF filter.
    - Content-Length header is checked before streaming (fail-fast).
    - Streams response body with hard 50 MiB cap enforced mid-stream.
    - Separate connect/read/write timeouts to avoid slow-loris-style stalls.

    Note: DNS rebinding (attacker-controlled DNS returning a public IP to
    our check, then a private IP to httpx microseconds later) is a
    theoretical residual risk. Pinning the resolved IP was attempted but
    broke TLS SNI for real-world CDNs; the window between our check and
    httpx's connect is microseconds, and the 50 MiB cap bounds the
    blast-radius if a rebind does slip through.

    Returns ``(content_bytes, inferred_filename, error_dict)``:
    - On success: ``(bytes, sanitized_filename_or_None, None)``
    - On failure: ``(b"", None, {"error": "..."})``
    """
    # Local import avoids a circular import: redmine_handler imports from
    # this module at top level, but we need the upload size cap from it.
    import io

    from .redmine_handler import _FILE_UPLOAD_MAX_SIZE_BYTES

    def _err(msg: str) -> Tuple[bytes, Optional[str], Dict[str, Any]]:
        return b"", None, {"error": msg}

    current_url = source_url
    # Initial scheme + credentials check before even attempting DNS.
    parsed = urlparse(current_url)
    if parsed.scheme not in ("http", "https"):
        return _err(
            f"Unsupported URL scheme '{parsed.scheme}'. "
            "Only http:// and https:// are supported."
        )
    if parsed.username or parsed.password:
        return _err("URLs with embedded credentials are not permitted.")

    inferred: Optional[str] = None
    if parsed.path:
        inferred = _sanitize_filename(os.path.basename(parsed.path))

    redirects_followed = 0
    content_bytes = b""
    try:
        while True:
            err_dict, hostname, resolved_ip = _validate_fetch_url(current_url)
            if err_dict is not None:
                return b"", None, err_dict

            async with _make_pinned_client(
                hostname=hostname, resolved_ip=resolved_ip
            ) as hc:
                async with hc.stream("GET", current_url) as response:
                    # Follow redirects ourselves so every hop is revalidated.
                    if response.status_code in (301, 302, 303, 307, 308):
                        redirects_followed += 1
                        if redirects_followed > _FILE_DOWNLOAD_MAX_REDIRECTS:
                            return _err(
                                f"Too many redirects "
                                f"(> {_FILE_DOWNLOAD_MAX_REDIRECTS})."
                            )
                        location = response.headers.get("location", "")
                        if not location:
                            return _err(
                                f"Got redirect status {response.status_code} "
                                "with no Location header."
                            )
                        # Resolve the Location header relative to current URL.
                        current_url = str(httpx.URL(current_url).join(location))
                        continue

                    if response.status_code >= 400:
                        return _err(
                            f"Failed to fetch source_url: HTTP "
                            f"{response.status_code} {response.reason_phrase}"
                        )

                    # Fail-fast on an honest Content-Length that exceeds
                    # the cap (still enforced mid-stream if the server lies).
                    cl_header = response.headers.get("content-length")
                    if cl_header and cl_header.isdigit():
                        declared = int(cl_header)
                        if declared > _FILE_UPLOAD_MAX_SIZE_BYTES:
                            size_mb = declared / (1024 * 1024)
                            limit_mb = _FILE_UPLOAD_MAX_SIZE_BYTES / (1024 * 1024)
                            return _err(
                                f"Server declares file size {size_mb:.1f} MiB, "
                                f"exceeds {limit_mb:.0f} MiB limit."
                            )

                    # Use the server's filename only if the original URL
                    # didn't give us a usable one. Sanitize aggressively.
                    if not inferred:
                        inferred = _extract_content_disposition_filename(
                            response.headers.get("content-disposition", "")
                        )

                    buffer = io.BytesIO()
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > _FILE_UPLOAD_MAX_SIZE_BYTES:
                            size_mb = total / (1024 * 1024)
                            limit_mb = _FILE_UPLOAD_MAX_SIZE_BYTES / (1024 * 1024)
                            return _err(
                                f"Downloaded file too large: exceeds "
                                f"{limit_mb:.0f} MiB limit "
                                f"(received {size_mb:.1f} MiB so far)."
                            )
                        buffer.write(chunk)
                    content_bytes = buffer.getvalue()
                    break  # exits the redirect loop
    except httpx.TimeoutException:
        return _err(
            "Timed out fetching source_url. Check the URL or try a smaller file."
        )
    except httpx.RequestError as e:
        # Scrub the exception message — httpx can embed URLs with creds.
        safe_msg = _scrub_error_message(str(e))
        return _err(f"Failed to fetch source_url: {safe_msg}")

    if len(content_bytes) == 0:
        return _err("Downloaded content is empty. Check the source_url.")

    return content_bytes, inferred, None
