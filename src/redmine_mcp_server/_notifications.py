"""Which write tools make Redmine send email (#401).

Redmine mails the people around an issue after every successful write, and
its REST API has no flag to suppress that for a single request. The only
lever a caller has is fewer writes. A model that splits one task into three
calls (set the status, add a note, reassign) sends three emails for one
change, and it cannot know that unless the tool description says so.

This module is the single source of truth for that effect. It mirrors the
shape of ``_annotations.py``: one central per-tool table, a short hint built
from it that ``MailHintMiddleware`` puts into the tool description, and an
anti-drift test that makes every write tool declare an answer.

The hint is kept short on purpose. It rides in ``tools/list`` on every
session, and a sentence with three reservations is read less than a plain
one. The reasons behind each row are comments here, not text for the model.

Maintenance:
    1. A new write tool needs an entry here. Not knowing yet is an answer:
       ``MailEffect.UNVERIFIED`` says so out loud and adds no hint.
    2. Read tools stay out of the table. The anti-drift test rejects them,
       so a tool that turns from a read into a write is not silently kept.
    3. For a ``manage_X(action=...)`` tool, list the actions that mail in
       ``actions``. The hint then names them, which is as much as a
       description can do: annotations cannot vary by argument, a sentence
       can.
    4. Checked against the Redmine source on master, a Redmine 6.0 server
       and the tools of 2.22.0. The checklist rows rest on what a server
       with RedmineUP Checklists does. The other plugin write tools (DMSF
       documents, the Helpdesk ticket tool, CRM, Products) are
       ``UNVERIFIED`` until someone reads the plugin.
"""

import enum
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional


class MailEffect(enum.Enum):
    """What a successful call does to Redmine's outgoing mail."""

    # Mails with the settings Redmine ships with, or because mailing is what
    # the tool or a plugin setting is for. Gets a hint.
    NOTIFIES = "notifies"
    # Mails only after an administrator has switched the event on. Redmine
    # ships with issue_added and issue_updated on and every other event off,
    # so on most servers a hint would warn about mail that is never sent.
    OFF_BY_DEFAULT = "off_by_default"
    NONE = "none"
    # Write tool of a plugin nobody has read for this. No hint is added:
    # a guess in a tool description is worse than silence.
    UNVERIFIED = "unverified"


# Issue#notified_users: the author, the assignee, the previous assignee, the
# watchers, and every project member whose own setting is "for any event".
# The REST API does not return that setting, so a caller cannot look up who
# is mailed. Reading the watcher list and concluding that
# nobody is mailed is the mistake the second half of the sentence is for.
_ISSUE_PEOPLE = "the people involved in the issue, also when nobody watches it"

# Redmine journals a new, moved or deleted subtask on its parent issue, and
# that entry mails too: one new subtask made two emails on Redmine 6.0.
_ISSUE_ADVICE = (
    "Put every change to one issue (fields, status, assignee, note) into "
    "one call: three calls send three emails. A subtask also mails its "
    "parent issue."
)

_CHECKLIST_HISTORY_ON = (
    "only when the RedmineUP Checklists setting that writes checklist changes "
    "to the issue history is on"
)


@dataclass(frozen=True)
class MailSpec:
    """One row of the table.

    Attributes:
        effect: The answer for this tool.
        actions: For a ``manage_X(action=...)`` tool, the actions that mail.
            ``None`` means every call of the tool does.
        recipients: Who Redmine mails, in the words of the hint.
        advice: What the caller can do about it, appended to the hint.
        condition: A plugin setting the mail depends on, named in the hint.
    """

    effect: MailEffect
    actions: Optional[FrozenSet[str]] = None
    recipients: str = _ISSUE_PEOPLE
    advice: str = ""
    condition: str = ""


MAIL_EFFECTS: Dict[str, MailSpec] = {
    # --- issues ---
    # The issue endpoint does not take relations, so each one is a further
    # request that journals on the new issue.
    "create_redmine_issue": MailSpec(
        MailEffect.NOTIFIES,
        advice=_ISSUE_ADVICE
        + " Relations cannot go in this call: each one is a further request "
        "that mails the new issue again.",
    ),
    # Each copied subtask is saved as a new issue of its own and is journaled
    # on its parent: two subtasks made five emails on Redmine 6.0.
    "copy_issue": MailSpec(
        MailEffect.NOTIFIES,
        advice="With `copy_subtasks` every copied subtask mails too. Put "
        "changes to the copy into `field_overrides` instead of a later "
        "update.",
    ),
    "update_redmine_issue": MailSpec(MailEffect.NOTIFIES, advice=_ISSUE_ADVICE),
    # Redmine journals the relation on both issues (IssueRelation#init_journals,
    # Issue#relation_added), so both sides mail, one request per relation.
    "manage_issue_relation": MailSpec(
        MailEffect.NOTIFIES,
        actions=frozenset({"create", "delete"}),
        recipients="the people involved in both issues, also when nobody "
        "watches them",
        advice="A relation cannot be bundled into an issue update, so set "
        "only the ones that are needed and say how many emails that is "
        "before setting several.",
    ),
    # Journal only notifies after_create_commit, so editing a note or
    # changing its privacy mails nobody.
    "manage_issue_note": MailSpec(MailEffect.NONE),
    "manage_issue_watcher": MailSpec(MailEffect.NONE),
    "manage_issue_category": MailSpec(MailEffect.NONE),
    # Deleting mails nobody about the issue itself, but a deleted subtask is
    # journaled on its parent.
    "delete_redmine_issue": MailSpec(
        MailEffect.NOTIFIES,
        recipients="the people involved in the parent issue, if the deleted "
        "issue is a subtask",
    ),
    # --- checklists (plugin) ---
    # RedmineUP Checklists writes the change to the issue history, and that
    # journal entry mails, when the plugin setting for it is on.
    "create_checklist_item": MailSpec(
        MailEffect.NOTIFIES,
        advice="An item is one call, so adding five items sends five emails.",
        condition=_CHECKLIST_HISTORY_ON,
    ),
    "update_checklist_item": MailSpec(
        MailEffect.NOTIFIES,
        advice="An item is one call, so changing five items sends five emails.",
        condition=_CHECKLIST_HISTORY_ON,
    ),
    # --- wiki ---
    # wiki_content_added and wiki_content_updated. The update mails only when
    # the text changed (WikiContent#send_notification_update).
    "manage_redmine_wiki_page": MailSpec(
        MailEffect.OFF_BY_DEFAULT, actions=frozenset({"create", "update"})
    ),
    # --- news ---
    # news_added. An update of an existing item does not notify.
    "manage_redmine_news": MailSpec(
        MailEffect.OFF_BY_DEFAULT, actions=frozenset({"create"})
    ),
    "delete_redmine_news": MailSpec(MailEffect.NONE),
    # --- files and attachments ---
    # file_added, for project files. An attachment that rides along on an
    # issue or wiki write is covered by that object's own mail.
    "upload_file": MailSpec(MailEffect.OFF_BY_DEFAULT),
    # Local only: stages a ticket, writes nothing to Redmine.
    "create_upload_ticket": MailSpec(MailEffect.NONE),
    "delete_file": MailSpec(MailEffect.NONE),
    "cleanup_attachment_files": MailSpec(MailEffect.NONE),
    # --- helpdesk (plugin) ---
    # Sending the mail is the point of the tool, not a side effect, but the
    # table has to be complete and the recipient is worth spelling out.
    "send_helpdesk_email_reply": MailSpec(
        MailEffect.NOTIFIES, recipients="the ticket's customer"
    ),
    "manage_helpdesk_ticket": MailSpec(MailEffect.UNVERIFIED),
    # --- projects, versions, members, time ---
    "manage_redmine_project": MailSpec(MailEffect.NONE),
    "manage_redmine_version": MailSpec(MailEffect.NONE),
    "manage_project_member": MailSpec(MailEffect.NONE),
    "manage_time_entry": MailSpec(MailEffect.NONE),
    "import_time_entries": MailSpec(MailEffect.NONE),
    # --- plugin tools nobody has read for this ---
    "manage_document": MailSpec(MailEffect.UNVERIFIED),
    "manage_product": MailSpec(MailEffect.UNVERIFIED),
    "manage_contact": MailSpec(MailEffect.UNVERIFIED),
    "manage_deal": MailSpec(MailEffect.UNVERIFIED),
    "manage_deal_category": MailSpec(MailEffect.UNVERIFIED),
    "add_deal_product": MailSpec(MailEffect.UNVERIFIED),
    "manage_crm_note": MailSpec(MailEffect.UNVERIFIED),
}

HINT_PREFIX = "Email:"


def _trigger(spec: MailSpec) -> str:
    if spec.actions is None:
        return "every successful call"
    actions = [f"`{name}`" for name in sorted(spec.actions)]
    if len(actions) == 1:
        return f"a successful {actions[0]} action"
    listed = ", ".join(actions[:-1])
    return f"a successful {listed} or {actions[-1]} action"


def mail_hint(tool_name: str) -> Optional[str]:
    """Return the hint for a tool's description, or None.

    Only a tool that mails with Redmine's own defaults gets one. A read
    tool, a write tool that mails nobody, one whose event is off by default
    and one whose plugin has not been read add nothing a caller could act on.
    """
    spec = MAIL_EFFECTS.get(tool_name)
    if spec is None or spec.effect is not MailEffect.NOTIFIES:
        return None
    condition = f" ({spec.condition})" if spec.condition else ""
    sentence = (
        f"{HINT_PREFIX} {_trigger(spec)} makes Redmine email "
        f"{spec.recipients}{condition}."
    )
    return f"{sentence} {spec.advice}" if spec.advice else sentence


def with_mail_hint(tool_name: str, description: Optional[str]) -> Optional[str]:
    """Return the description with the tool's hint in it.

    The hint goes after the summary line rather than at the end: some of
    these descriptions run for dozens of lines, where a sentence about email
    at the bottom is easy to miss. A tool without a hint gets its description
    back unchanged.
    """
    hint = mail_hint(tool_name)
    if hint is None:
        return description
    if not description:
        return hint
    head, separator, rest = description.partition("\n\n")
    if not separator:
        return f"{description}\n\n{hint}"
    return f"{head}\n\n{hint}\n\n{rest}"
