# Issue Triage Helper

A Claude Code recipe for efficiently triaging, categorizing, and prioritizing Redmine issues.

## Overview

This recipe streamlines issue triage by helping you quickly assess, categorize, and route incoming issues. Perfect for project managers, team leads, and support teams managing high-volume issue queues.

## What This Recipe Does

1. **Identifies untriaged issues** - Finds new and unassigned issues needing attention
2. **Categorizes issues** - Helps classify by type, severity, and urgency
3. **Routes work** - Suggests assignments based on issue characteristics
4. **Prioritizes queues** - Orders issues by impact and effort
5. **Batch operations** - Updates multiple issues efficiently

## Prerequisites

- Redmine MCP Server installed and configured ([installation guide](../README.md#installation))
- MCP server running and connected to your Claude Code client
- Update permission for issues in your Redmine project

## Usage Example

### Starting a Triage Session

```
Hi Claude! I need to triage new issues for project ID 5.
Show me all unassigned issues and help me prioritize them.
```

### Claude's Workflow

**Step 1: Find Untriaged Issues**

Claude will use `search_redmine_issues` to find new issues:

```
Searching for unassigned and new issues in project 5...
```

**Step 2: Analyze Each Issue**

Claude will use `get_redmine_issue` to review details:

```
Let me review each issue to assess priority and category...
```

**Step 3: Recommend Actions**

Claude suggests triage decisions:

```
Issue #456: "Application crashes on login"
- Severity: High (affects user access)
- Category: Bug
- Recommended priority: Urgent
- Suggested assignee: Backend team
- Action: Assign to @alice, set priority to High
```

**Step 4: Execute Updates**

Claude can batch-update issues with your approval:

```
Updating issue #456...
[Uses: update_redmine_issue(issue_id=456, fields={...})]
```

## Interactive Examples

### Example 1: Triage New Issues

**You:**
```
Triage all new issues in project 5. Categorize them and suggest priorities.
```

**Claude:**
```
Searching for new issues in project 5...

[Uses: search_redmine_issues(project_id=5, status_id=1)]

Found 12 new issues. Let me analyze them...

[Uses: get_redmine_issue(issue_id=X) for each]

TRIAGE SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

URGENT (3 issues) - Need immediate attention:

  #456 "Application crashes on login"
    📋 Type: Bug - Critical
    💥 Impact: High - Affects all users
    ⚡ Urgency: Critical - Users cannot access system
    👤 Suggest: Assign to @backend-team, Priority: Immediate
    💬 Recommendation: Drop everything, fix within 2 hours

  #457 "Payment processing fails"
    📋 Type: Bug - Critical
    💥 Impact: High - Revenue impact
    ⚡ Urgency: Critical - Payments failing since 2 hours ago
    👤 Suggest: Assign to @alice (payments expert), Priority: Urgent
    💬 Recommendation: Fix today, communicate to stakeholders

  #458 "Database connection timeout"
    📋 Type: Bug - Major
    💥 Impact: Medium - Affects 30% of requests
    ⚡ Urgency: High - Performance degradation
    👤 Suggest: Assign to @devops, Priority: High
    💬 Recommendation: Investigate today, temporary mitigation ASAP

HIGH PRIORITY (4 issues) - Address this sprint:

  #459 "Add export to CSV feature"
    📋 Type: Feature Request
    💥 Impact: Medium - Requested by 5 customers
    ⚡ Urgency: Medium - Customer commitment
    👤 Suggest: Assign to @bob, Priority: High
    💬 Recommendation: Schedule for current sprint

  #460 "Slow report generation"
    📋 Type: Performance
    💥 Impact: Medium - Affects reporting team
    ⚡ Urgency: Medium - Workaround exists
    👤 Suggest: Assign to @backend-team, Priority: Normal
    💬 Recommendation: Optimize next sprint

  #461 "Missing validation on user input"
    📋 Type: Bug - Security
    💥 Impact: Medium - Potential data integrity issue
    ⚡ Urgency: High - Security concern
    👤 Suggest: Assign to @carol, Priority: High
    💬 Recommendation: Fix this week

  #462 "Update API documentation"
    📋 Type: Documentation
    💥 Impact: Low - Internal only
    ⚡ Urgency: Medium - Developers confused
    👤 Suggest: Assign to @technical-writer, Priority: Normal
    💬 Recommendation: Complete this sprint

NORMAL (3 issues) - Backlog candidates:

  #463 "Add dark mode to UI"
    📋 Type: Enhancement
    💥 Impact: Low - Nice to have
    ⚡ Urgency: Low - No deadline
    👤 Suggest: Backlog for future sprint
    💬 Recommendation: Gather more user feedback first

  #464 "Refactor authentication module"
    📋 Type: Technical Debt
    💥 Impact: Low - Code quality
    ⚡ Urgency: Low - No immediate issues
    👤 Suggest: Schedule for tech debt sprint
    💬 Recommendation: Plan with team, estimate effort

  #465 "Add more unit tests"
    📋 Type: Testing
    💥 Impact: Low - Preventive
    ⚡ Urgency: Low - Coverage acceptable
    👤 Suggest: Ongoing effort
    💬 Recommendation: Add incrementally with features

LOW PRIORITY (2 issues) - Consider closing:

  #466 "Change button color on homepage"
    📋 Type: UI Tweak
    💥 Impact: Minimal - Cosmetic
    ⚡ Urgency: Low - Personal preference
    👤 Suggest: Close or defer
    💬 Recommendation: Needs design review, low ROI

  #467 "Support for IE11"
    📋 Type: Feature Request
    💥 Impact: Minimal - <1% users
    ⚡ Urgency: Low - Browser deprecated
    👤 Suggest: Close with explanation
    💬 Recommendation: Not supported, suggest modern browser

TRIAGE ACTIONS:

Would you like me to:
1. Update priorities for all urgent issues?
2. Assign issues to suggested team members?
3. Add triage notes to each issue?
4. Create a triage summary issue?
5. Close/reject low priority items?

Which would you like me to do? (Or say "all" for complete triage)
```

### Example 2: Bug Triage Session

**You:**
```
Find all unresolved bugs in project 3 and help me prioritize them
```

**Claude:**
```
Searching for active bugs in project 3...

[Uses: search_redmine_issues(project_id=3, tracker_id=1, status_id="!5")]

Found 18 open bugs. Analyzing severity and impact...

BUG TRIAGE - Project 3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CRITICAL BUGS (2) - Fix immediately:
  🔴 #501 "Data loss on save" - CRITICAL
     • Reported: 3 hours ago
     • Affects: All users editing records
     • Reproducibility: 100%
     • Impact: Data integrity
     → ACTION: Hotfix required, assign to senior dev

  🔴 #502 "Authentication bypass possible" - SECURITY
     • Reported: Yesterday
     • Affects: All authenticated endpoints
     • Reproducibility: Confirmed
     • Impact: Security vulnerability
     → ACTION: Immediate patch, security review

HIGH SEVERITY (5) - Fix this week:
  🟠 #503 "Form submission error on Firefox"
     • Affects: 15% of users (Firefox users)
     • Workaround: Use Chrome
     → ACTION: Fix within 3 days

  🟠 #504 "Email notifications not sent"
     • Affects: All notification subscribers
     • Started: This morning
     → ACTION: Investigate SMTP server

  [... 3 more high-severity bugs ...]

MEDIUM SEVERITY (8) - Schedule for sprint:
  🟡 #508 "UI alignment issue on mobile"
  🟡 #509 "Search results pagination broken"
  [... 6 more medium bugs ...]

LOW SEVERITY (3) - Backlog:
  🟢 #516 "Tooltip text typo"
  🟢 #517 "Minor CSS glitch on hover"
  🟢 #518 "Console warning in dev tools"

RECOMMENDATIONS:
  1. Escalate #501 and #502 to on-call engineer
  2. Assign high-severity bugs to sprint
  3. Create bug-fix release for critical items
  4. Defer low-severity items to next minor version

Shall I:
- Update priorities based on this analysis?
- Create a critical bug-fix release issue?
- Notify the team about urgent items?
```

### Example 3: Customer Support Triage

**You:**
```
Show me all customer-reported issues from the last 48 hours.
Identify which need urgent response.
```

**Claude:**
```
Searching for recent customer issues...

[Uses: search_redmine_issues(created_on=">=2025-01-13", custom_field_source="customer")]

Found 9 customer-reported issues. Analyzing urgency...

CUSTOMER SUPPORT TRIAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Last 48 hours - 9 issues

🔥 NEEDS IMMEDIATE RESPONSE (2):

  #601 "Cannot access account after payment"
    👤 Customer: Acme Corp (Enterprise)
    ⏰ Reported: 4 hours ago
    💰 Value: $50K/year customer
    😤 Sentiment: Frustrated (3rd issue this month)
    📊 SLA: 4 hours - 0 hours remaining ⚠️
    → ACTION: Assign to @support-lead immediately
    → RESPONSE: Acknowledge within 30 mins, provide ETA

  #602 "Production deployment failed"
    👤 Customer: Beta Systems (Premium)
    ⏰ Reported: 2 hours ago
    💰 Value: $30K/year customer
    📊 SLA: 8 hours - 6 hours remaining
    → ACTION: Escalate to engineering
    → RESPONSE: Provide rollback instructions, investigate

⚡ HIGH PRIORITY (3):

  #603 "Feature request: Bulk import"
    👤 Customer: Global Industries (Enterprise)
    ⏰ Reported: Yesterday
    💰 Value: $100K/year customer
    📊 Type: Feature request
    → ACTION: Forward to product team
    → RESPONSE: Acknowledge, add to roadmap discussion

  #604 "Report shows incorrect data"
    👤 Customer: Small Biz Inc (Standard)
    ⏰ Reported: 18 hours ago
    💰 Value: $5K/year customer
    📊 SLA: 24 hours - 6 hours remaining
    → ACTION: Verify data, may be user error
    → RESPONSE: Request reproduction steps

  #605 "Integration not working"
    👤 Customer: Tech Startup (Standard)
    ⏰ Reported: 24 hours ago
    💰 Value: $8K/year customer
    → ACTION: Check API logs, provide debug info
    → RESPONSE: Send troubleshooting guide

📋 NORMAL PRIORITY (4):

  #606 "Question about billing"
  #607 "How to export data?"
  #608 "Feature suggestion: Email templates"
  #609 "Minor UI bug in settings"

TRIAGE SUMMARY:
  • Urgent response needed: 2 issues
  • At-risk SLA: 1 issue (#601)
  • High-value customers: 3 issues
  • Questions/How-to: 2 issues
  • Feature requests: 2 issues

RECOMMENDED ACTIONS:
  1. ⚠️ Immediately respond to #601 (SLA breach imminent)
  2. Escalate #602 to engineering team
  3. Assign customer success manager to #603 (high-value customer)
  4. Route questions (#607) to documentation team
  5. Tag feature requests for product review

Would you like me to:
- Draft response templates for urgent issues?
- Update issue priorities and assignments?
- Create escalation notifications?
- Add SLA tracking comments?
```

### Example 4: Batch Issue Update

**You:**
```
Take all "New" issues in project 7 without an assignee and assign them
to the appropriate team based on the issue type.
```

**Claude:**
```
Finding unassigned new issues in project 7...

[Uses: search_redmine_issues(project_id=7, status_id=1, assigned_to_id="!*")]

Found 15 unassigned issues. Let me categorize by team...

[Uses: get_redmine_issue() to check tracker/category for each]

BATCH ASSIGNMENT PLAN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Backend Team (user_id: 5) - 6 issues:
  #701 "API endpoint returns 500 error" (Bug)
  #702 "Database migration needed" (Task)
  #703 "Add validation to user model" (Enhancement)
  #704 "Optimize query performance" (Performance)
  #705 "Fix authentication flow" (Bug)
  #706 "Add new API endpoint" (Feature)

Frontend Team (user_id: 7) - 4 issues:
  #707 "Button styling broken" (Bug - UI)
  #708 "Add loading spinner" (Enhancement - UI)
  #709 "Responsive layout issue" (Bug - UI)
  #710 "Implement new dashboard" (Feature - UI)

DevOps Team (user_id: 9) - 3 issues:
  #711 "CI/CD pipeline failing" (Bug - Infrastructure)
  #712 "Setup staging environment" (Task - Infrastructure)
  #713 "Increase server capacity" (Task - Infrastructure)

Documentation Team (user_id: 11) - 2 issues:
  #714 "API docs outdated" (Documentation)
  #715 "Add setup guide" (Documentation)

Executing assignments...

[Uses: update_redmine_issue(issue_id=701, fields={"assigned_to_id": 5})]
[Uses: update_redmine_issue(issue_id=702, fields={"assigned_to_id": 5})]
[... continues for all 15 issues ...]

✓ Successfully assigned 15 issues:
  • Backend Team: 6 issues
  • Frontend Team: 4 issues
  • DevOps Team: 3 issues
  • Documentation Team: 2 issues

All teams have been notified via Redmine notifications.

Would you like me to:
- Set default priorities for these assignments?
- Add a comment explaining the triage decision?
- Create a summary report of assignments?
```

## Useful Prompts

### Finding Issues to Triage
```
"Show me all unassigned issues in project [X]"
"Find new issues from the last 24 hours"
"List all bugs with no priority set"
"Show customer-reported issues"
```

### Categorization
```
"Categorize these issues by severity"
"Which issues are bugs vs features?"
"Group issues by component/module"
"Identify security-related issues"
```

### Prioritization
```
"Prioritize these issues by impact"
"Which bugs should we fix first?"
"Rank issues by customer value"
"Show me critical path items"
```

### Batch Operations
```
"Assign all UI bugs to the frontend team"
"Set priority to high for all security issues"
"Add 'needs-triage' tag to all new issues"
"Close all issues older than 6 months with no activity"
```

## Tools Used

This recipe leverages the following Redmine MCP tools:

| Tool | Purpose |
|------|---------|
| `search_redmine_issues` | Find issues matching triage criteria |
| `get_redmine_issue` | Get detailed issue information for assessment |
| `update_redmine_issue` | Update priority, assignment, status, tags |
| `list_my_redmine_issues` | Check your triage queue |
| `summarize_project_status` | Understand overall project health |

## Tips & Best Practices

1. **Triage Daily** - Don't let issues pile up, review new items daily
2. **Use Templates** - Create standard triage workflows for consistency
3. **Set Clear Criteria** - Define what makes an issue urgent/high/normal/low
4. **Document Decisions** - Add comments explaining triage reasoning
5. **Batch Similar Items** - Group related issues for efficient processing
6. **Track Metrics** - Monitor triage velocity and backlog growth

## Triage Decision Framework

### Bug Severity Matrix

| Impact | User Affected | Workaround? | Priority |
|--------|--------------|-------------|----------|
| System down | All users | No | Critical |
| Major feature broken | Most users | No | High |
| Minor feature broken | Some users | Yes | Medium |
| Cosmetic issue | Few users | Yes | Low |

### Feature Prioritization

- **Customer Value**: Revenue impact, strategic accounts
- **Effort Estimate**: Development time required
- **Dependencies**: Blocking other work
- **Strategic Alignment**: Roadmap fit

## Automation Ideas

### Daily Triage Report
```
"Send me a daily summary of new issues at 9am"
```

### Auto-categorization
```
"Tag all issues with 'bug' in the title as tracker=Bug"
"Assign all database-related issues to @db-team"
```

### SLA Monitoring
```
"Flag any customer issues approaching SLA deadline"
"Show issues with no response for >24 hours"
```

## Troubleshooting

**Issue: Can't find issues to triage**
- Check project ID is correct
- Verify status filters (New vs Open)
- Ensure you have view permissions

**Issue: Can't update issues**
- Confirm you have update permissions
- Check issue is not locked/closed
- Verify field values are valid (e.g., valid assignee ID)

**Issue: Assignment failed**
- Ensure user has project membership
- Verify user ID is correct
- Check user is active (not disabled)

## Related Recipes

- [Sprint Planning Assistant](./sprint-planning.md) - Plan sprints after triage
- [Daily Standup Generator](./daily-standup.md) - Track triaged work
- [Health Check Monitor](./health-check.md) - Monitor triage metrics

## Learn More

- [Tool Reference](../docs/tool-reference.md) - Complete MCP tool documentation
- [Redmine Issue Tracking](https://www.redmine.org/projects/redmine/wiki/RedmineIssues) - Issue management guide
- [Bug Triage Best Practices](https://bugzilla.readthedocs.io/en/latest/using/understanding.html) - Industry standards
