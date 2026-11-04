"""Which markup the Redmine server renders text with (#440).

Redmine renders notes, descriptions, wiki pages and news with one global Text
formatting setting, and the REST API has no endpoint for it. Without it the
model guesses, and a Textile list (``# item``) posted to a Markdown server
renders as a stack of headings. This module reads the formatter from the edit
toolbar on an issue's HTML page and holds the short syntax blocks appended to
the text-writing tools' descriptions.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import httpx

from . import _client
from ._env import get_text_formatting

logger = logging.getLogger("redmine_mcp_server")

FORMATS = ("textile", "markdown", "common_mark", "none")

# Redmine 6.1+: the notes textarea carries the formatter as a Stimulus param.
_DATA_ATTR_RE = re.compile(r'data-list-autofill-text-formatting-param="([a-z_]+)"')
# Redmine 3.4+: the toolbar script is per formatter. Assets may be fingerprinted
# (``textile-3c4d.js``) or query-stamped (``markdown.js?160...``).
_SCRIPT_RE = re.compile(
    r'<script[^>]*\bsrc="[^"]*jstoolbar/(textile|markdown|common_mark)\b[^"]*"'
)
# Redmine 3.4 shipped Textile as a single minified bundle.
_TEXTILE_MIN_RE = re.compile(r'<script[^>]*\bsrc="[^"]*jstoolbar-textile\.min[^"]*"')
# Redmine 5.1 and older: the help URL is per formatter, passed to the toolbar in
# an inline script (never an <a href>). 2.6 Textile used plain wiki_syntax.html.
# From 6.0 the URL is the generic /help/wiki_syntax and matches nothing here.
_HELP_LINK_RE = re.compile(
    r"setHelpLink\('[^']*wiki_syntax(?:_(textile|markdown|common_mark))?\.html'\)"
)


def parse_format_from_html(html: str) -> Optional[str]:
    """Return the formatter an issue page's edit toolbar was built for.

    Only markup Redmine itself emits counts: a ``data-*`` attribute, a
    ``<script src>`` include, or the ``setHelpLink('...')`` call. Rendered
    user text cannot fake these because Rails escapes quotes in it. A page
    with no toolbar returns ``None``, never ``"none"``: the user may simply
    lack permission to edit the issue.
    """
    match = _DATA_ATTR_RE.search(html)
    if match and match.group(1) in FORMATS:
        return match.group(1)
    match = _SCRIPT_RE.search(html)
    if match:
        return match.group(1)
    if _TEXTILE_MIN_RE.search(html):
        return "textile"
    match = _HELP_LINK_RE.search(html)
    if match:
        return match.group(1) or "textile"
    return None


_MARKDOWN_RULES = (
    "Numbered list `1. item`, bullets `- item`, bold `**bold**`, "
    "code `` `x` `` and ``` fences,\n"
    "link `[text](url)`. Never start a line with `#` unless you want a heading."
)

TEXT_BLOCKS = {
    "markdown": "Text formatting on this Redmine: Markdown.\n" + _MARKDOWN_RULES,
    "common_mark": "Text formatting on this Redmine: CommonMark Markdown.\n"
    + _MARKDOWN_RULES,
    "textile": (
        "Text formatting on this Redmine: Textile.\n"
        "Numbered list `# item`, bullets `* item`, bold `*bold*`, "
        "code `@x@` and <pre>,\n"
        'link `"text":url`, heading `h2. Title`. Markdown syntax will NOT render.'
    ),
    "none": "This Redmine renders text as plain text; do not use any markup.",
    "unknown": (
        "This Redmine's text formatting could not be determined. Write plain "
        "text: short paragraphs, `1)` or `-` for lists, no `#`, `*`, `_` or "
        "backtick markup."
    ),
}

# Tools whose text Redmine renders through the formatter. Plain-text fields
# (time entry comments, wiki edit comments, attachment and version
# descriptions, news summaries) are deliberately absent. Helpdesk tickets are
# issues. CRM, deals, products and DMSF wait until their rendering is checked.
FORMATTED_TEXT_TOOLS = frozenset(
    {
        "create_redmine_issue",
        "update_redmine_issue",
        "manage_issue_note",
        "copy_issue",
        "manage_redmine_wiki_page",
        "manage_redmine_news",
        "manage_redmine_project",
        "manage_helpdesk_ticket",
        "send_helpdesk_email_reply",
    }
)

SERVER_INSTRUCTIONS = (
    "Text you write to Redmine is rendered with the server's text formatting. "
    "Each text-writing tool's description states which syntax to use."
)


@dataclass(frozen=True)
class FormatResult:
    """``value`` is one of FORMATS or ``"unknown"``; ``source`` is ``"env"``,
    ``"detected"`` or ``"unknown"``."""

    value: str
    source: str


UNKNOWN = FormatResult("unknown", "unknown")
DETECT_TIMEOUT = 5.0
FAILURE_TTL = 600.0


async def detect_format(
    cred: "_client.RequestCredential",
    *,
    base_url: str,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> Optional[str]:
    """Read the formatter from any visible issue's HTML page, or ``None``.

    ``IssuesController#show`` accepts API auth whatever the format, so the
    API key, Basic auth and an OAuth Bearer all work on the HTML page.
    Redirects are not followed: a 302 to /login is a failure, not a page.
    """
    base = (base_url or "").rstrip("/")
    if not base.startswith("http"):
        return None
    try:
        kwargs = {**_client.httpx_ssl_kwargs(), **cred.httpx_kwargs()}
        if transport is not None:
            kwargs["transport"] = transport
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(DETECT_TIMEOUT), follow_redirects=False, **kwargs
        ) as http:
            listing = await http.get(f"{base}/issues.json", params={"limit": 1})
            if listing.status_code != 200:
                return _failed(f"issues.json HTTP {listing.status_code}")
            issues = listing.json().get("issues") or []
            if not issues:
                return _failed("no visible issue")
            page = await http.get(f"{base}/issues/{issues[0]['id']}")
            if page.status_code != 200:
                return _failed(f"issue page HTTP {page.status_code}")
            value = parse_format_from_html(page.text)
    except Exception as exc:  # any failure means "unknown", never a guess
        return _failed(type(exc).__name__)
    if value is None:
        return _failed("no toolbar marker on the issue page")
    logger.info("text_formatting detected=%s", value)
    return value


def _failed(reason: str) -> None:
    logger.info("text_formatting detection failed: %s", reason)
    return None


Detector = Callable[..., Awaitable[Optional[str]]]


class TextFormattingResolver:
    """Resolve the formatting once per process.

    A success is shared by every caller for the life of the process (one
    process talks to one Redmine). A failure is remembered only for the
    credential that hit it, for ``failure_ttl`` seconds, so one user who
    cannot see an editable issue does not force ``unknown`` on everyone.
    """

    def __init__(
        self,
        *,
        detector: Detector = detect_format,
        clock: Callable[[], float] = time.monotonic,
        failure_ttl: float = FAILURE_TTL,
    ):
        self.detector = detector
        self._clock = clock
        self._failure_ttl = failure_ttl
        self._lock = asyncio.Lock()
        self.reset()

    def reset(self) -> None:
        self._detected: Optional[str] = None
        self._failed_at: dict = {}

    def _recently_failed(self, key: str) -> bool:
        at = self._failed_at.get(key)
        return at is not None and self._clock() - at < self._failure_ttl

    async def resolve(self, cred) -> FormatResult:
        configured = get_text_formatting()
        if configured != "auto":
            return FormatResult(configured, "env")
        if self._detected is not None:
            return FormatResult(self._detected, "detected")
        if cred is None:
            return UNKNOWN
        key = cred.cache_key()
        if self._recently_failed(key):
            return UNKNOWN
        async with self._lock:
            if self._detected is not None:
                return FormatResult(self._detected, "detected")
            if self._recently_failed(key):
                return UNKNOWN
            value = await self.detector(cred, base_url=_client.REDMINE_URL)
            if value is None:
                self._failed_at[key] = self._clock()
                return UNKNOWN
            self._detected = value
            return FormatResult(value, "detected")


RESOLVER = TextFormattingResolver()


async def current_format() -> FormatResult:
    """The formatting for the current request's credential."""
    cred = _client.resolve_request_credential(strict=False)
    return await RESOLVER.resolve(cred)
