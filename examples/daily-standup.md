# Daily Standup Report Generator

A Claude Code recipe for generating daily standup reports and tracking progress in Redmine.

## Overview

This recipe automates standup preparation by analyzing your assigned issues, recent activity, and blockers. Perfect for distributed teams using Redmine for task tracking.

## What This Recipe Does

1. **Generates standup reports** - Summarizes what you worked on yesterday and plan for today
2. **Identifies blockers** - Flags issues with no recent activity or dependencies
3. **Tracks progress** - Shows issue status changes and completion trends
4. **Formats updates** - Creates ready-to-share standup summaries

## Prerequisites

- Redmine MCP Server installed and configured ([installation guide](../README.md#installation))
- MCP server running and connected to your Claude Code client
- Issues assigned to you in Redmine

## Usage Example

### Quick Standup Report

```
Hi Claude! Generate my daily standup report for today.
```

### Claude's Workflow

**Step 1: Fetch Your Issues**

Claude will use `list_my_redmine_issues` to get your current work:

```
Let me check your assigned issues...
```

**Step 2: Analyze Recent Activity**

Claude will use `get_redmine_issue` with journals to see what changed:

```
Checking activity from the last 24 hours...
```

**Step 3: Generate Report**

Claude creates a formatted standup summary:

```
Daily Standup Report - January 15, 2025

YESTERDAY:
✓ Completed: Issue #234 - User login bug fix
✓ Progressed: Issue #456 - API endpoint implementation (60% complete)

TODAY:
→ Continue: Issue #456 - API endpoint implementation
→ Start: Issue #789 - Database migration script

BLOCKERS:
⚠ Issue #456 - Waiting on design mockups from UX team
```

## Interactive Examples

### Example 1: Standard Daily Standup

**You:**
```
Generate my standup report for today
```

**Claude:**
```
Fetching your assigned issues...

[Uses: list_my_redmine_issues(limit=50)]

Found 8 active issues assigned to you. Let me analyze recent activity...

[Uses: get_redmine_issue(issue_id=X, include_journals=true) for each active issue]

DAILY STANDUP - Tuesday, January 15, 2025
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

YESTERDAY (Jan 14):
  ✓ #234 "Fix login redirect loop"
    - Status: New → Resolved
    - Updated: Added fix and deployed to staging

  ✓ #456 "Implement user profile API"
    - Status: In Progress
    - Updated: Completed endpoint logic, started tests
    - Progress: ~70% complete

TODAY (Jan 15):
  → #456 "Implement user profile API"
    - Goal: Complete unit tests and documentation
    - ETA: End of day

  → #789 "Database schema migration"
    - Goal: Review migration script and test locally
    - Priority: High

  → #512 "Update API documentation"
    - Goal: Document new profile endpoints

BLOCKERS:
  ⚠ #456 - Waiting on code review from @tech-lead
  ⚠ #890 "Deploy to production" - Blocked by #456 completion

METRICS:
  • Active issues: 8
  • In Progress: 3
  • Waiting Review: 2
  • Ready to Start: 3
  • Velocity: 2 issues resolved this week

Would you like me to:
- Post this to a Redmine issue/note?
- Format for Slack/email?
- Add more details on specific issues?
```

### Example 2: Weekly Progress Summary

**You:**
```
Summarize my work from the past week
```

**Claude:**
```
Analyzing your activity from Jan 8-15...

[Uses: list_my_redmine_issues(limit=100)]
[Uses: get_redmine_issue() for issues with recent activity]

WEEKLY SUMMARY - Week of January 8-15, 2025
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

COMPLETED (5 issues):
  ✓ #123 "Fix password reset email" - Resolved Mon
  ✓ #234 "Login redirect loop" - Resolved Mon
  ✓ #345 "Update user permissions" - Resolved Wed
  ✓ #456 "User profile API" - Resolved Thu
  ✓ #567 "API documentation" - Resolved Fri

IN PROGRESS (3 issues):
  → #678 "Database migration" - 50% complete
  → #789 "Performance optimization" - 30% complete
  → #890 "Integration tests" - Just started

BLOCKED (1 issue):
  ⚠ #901 "Production deployment" - Waiting on DevOps approval

WEEKLY METRICS:
  • Issues completed: 5
  • Issues started: 8
  • Average cycle time: 2.4 days
  • Comments posted: 23
  • Time logged: 32 hours

KEY ACHIEVEMENTS:
  • Completed entire user authentication refactor
  • All critical bugs resolved
  • API documentation up to date

FOCUS NEXT WEEK:
  • Complete database migration (#678)
  • Performance optimization (#789)
  • Clear deployment blockers (#901)
```

### Example 3: Team Standup Summary

**You:**
```
What did our team work on yesterday? Show summary for project ID 5.
```

**Claude:**
```
Fetching team activity for project 5...

[Uses: summarize_project_status(project_id=5, days=1)]
[Uses: search_redmine_issues(project_id=5, updated_on=">=2025-01-14")]

TEAM STANDUP - Project: Mobile App
Date: January 15, 2025
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

YESTERDAY'S ACTIVITY:
  • 8 issues updated
  • 3 issues resolved
  • 2 new issues created
  • 15 comments posted

BY TEAM MEMBER:

Alice (@alice):
  ✓ #234 "Login bug" → Resolved
  → #456 "API endpoint" → In Progress (80%)

Bob (@bob):
  ✓ #345 "Payment flow" → Resolved
  ✓ #567 "Cart persistence" → Resolved
  → #678 "Checkout UI" → In Progress

Carol (@carol):
  → #789 "Performance tests" → In Progress
  → #890 "Load testing" → In Progress
  ⚠ #901 "Deploy staging" → Blocked (infra issues)

TEAM METRICS:
  • Total active issues: 23
  • Completion rate: 38% (3/8 in progress completed)
  • New issues: 2
  • Blockers: 1

BLOCKERS:
  ⚠ #901 - Staging environment down, affects Carol's deployment

TRENDING:
  ↑ Good velocity - 3 issues completed yesterday
  → Team capacity utilized: ~85%
  ⚠ Watch #901 blocker - may impact sprint

Would you like a breakdown for specific team members?
```

### Example 4: Quick Status Update

**You:**
```
What's the status of my issue #456?
```

**Claude:**
```
[Uses: get_redmine_issue(issue_id=456, include_journals=true)]

ISSUE #456: "Implement user profile API"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Current Status: In Progress
Priority: High
Assigned to: You
Created: Jan 10, 2025
Last updated: 2 hours ago

RECENT ACTIVITY:
  • 2 hours ago - You added comment:
    "Completed endpoint implementation, running tests"

  • Yesterday - Status changed: New → In Progress

  • Yesterday - You added comment:
    "Starting implementation, reviewed requirements"

JOURNALS (last 3):
  1. Jan 15, 10:30 AM - You:
     "Completed endpoint logic, unit tests at 70%"

  2. Jan 14, 3:45 PM - Status: New → In Progress

  3. Jan 14, 3:40 PM - @tech-lead:
     "Assigned to you, needs completion by Friday"

ATTACHMENTS:
  • API_spec.pdf (uploaded Jan 10)
  • mockup_profile_ui.png (uploaded Jan 12)

NEXT STEPS:
  → Complete remaining unit tests (30%)
  → Update API documentation
  → Request code review
  → Deploy to staging for QA

Would you like me to:
- Add a status update comment?
- Create follow-up tasks?
- Update the progress percentage?
```

## Useful Prompts

### Daily Reports
```
"Generate my standup report for today"
"What did I work on yesterday?"
"Show my active issues"
"What should I work on today?"
```

### Weekly Summaries
```
"Summarize my work from the past week"
"How many issues did I complete this week?"
"Show my weekly velocity"
```

### Team Updates
```
"Team standup for project [X]"
"What did the team complete yesterday?"
"Show team activity for the last 3 days"
```

### Quick Status
```
"Status of issue #[X]"
"Recent activity on my issues"
"Any blockers on my work?"
```

### Progress Tracking
```
"What's my completion rate this sprint?"
"How many issues are in progress?"
"Show issues with no recent updates"
```

## Tools Used

This recipe leverages the following Redmine MCP tools:

| Tool | Purpose |
|------|---------|
| `list_my_redmine_issues` | Get your assigned issues |
| `get_redmine_issue` | Fetch detailed issue info and history |
| `summarize_project_status` | Get team/project activity summary |
| `search_redmine_issues` | Find issues by date or criteria |
| `update_redmine_issue` | Post status updates (optional) |

## Tips & Best Practices

1. **Run Daily** - Make standup generation part of your morning routine
2. **Include Context** - Mention blockers and dependencies proactively
3. **Be Specific** - Include issue IDs and concrete progress metrics
4. **Track Blockers** - Flag impediments early for team visibility
5. **Update Issues** - Keep Redmine current for accurate reports

## Automation Ideas

### Morning Routine Script
```bash
# Create a shell alias for daily standup
alias standup='claude "Generate my standup report for today"'
```

### Slack Integration
Ask Claude to format the report for Slack:
```
"Generate my standup and format it for Slack with emoji"
```

### Custom Time Ranges
```
"Show my work from 9am yesterday to now"
"Activity since last Friday"
"What changed over the weekend?"
```

## Troubleshooting

**Issue: No issues found**
- Verify issues are assigned to you in Redmine
- Check authentication credentials are correct
- Confirm project access permissions

**Issue: Missing recent activity**
- Ensure journals/comments are enabled in Redmine
- Check date/time filters in queries
- Verify timezone settings match your location

**Issue: Report too long**
- Use filters to limit to specific projects
- Reduce time range (e.g., 1 day instead of 7)
- Focus on active issues only

## Related Recipes

- [Sprint Planning Assistant](./sprint-planning.md) - Plan sprints and iterations
- [Issue Triage Helper](./issue-triage.md) - Organize and prioritize work
- [Health Check Monitor](./health-check.md) - Track project health

## Learn More

- [Tool Reference](../docs/tool-reference.md) - Complete MCP tool documentation
- [Redmine Issues API](https://www.redmine.org/projects/redmine/wiki/Rest_Issues) - API details
- [Agile Standup Guide](https://www.atlassian.com/agile/scrum/standups) - Best practices
