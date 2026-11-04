"""Which markup the Redmine server renders text with (#440).

Redmine renders notes, descriptions, wiki pages and news with one global Text
formatting setting, and the REST API has no endpoint for it. Without it the
model guesses, and a Textile list (``# item``) posted to a Markdown server
renders as a stack of headings. This module reads the formatter from the edit
toolbar on an issue's HTML page and holds the short syntax blocks appended to
the text-writing tools' descriptions.
"""

import re
from typing import Optional

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
