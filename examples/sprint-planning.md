# Sprint Planning Assistant

A Claude Code recipe for streamlining sprint planning workflows with Redmine.

## Overview

This recipe helps you plan sprints by analyzing project status, creating sprint issues, and organizing work items. It combines multiple Redmine MCP tools to provide comprehensive sprint planning support.

## What This Recipe Does

1. **Analyzes project health** - Reviews recent activity and issue distribution
2. **Creates sprint structure** - Generates sprint milestone and planning issues
3. **Organizes backlog** - Helps prioritize and assign work items
4. **Tracks capacity** - Analyzes team workload and availability

## Prerequisites

- Redmine MCP Server installed and configured ([installation guide](../README.md#installation))
- MCP server running and connected to your Claude Code client
- Access to a Redmine project with issue creation/update permissions

## Usage Example

### Starting a Sprint Planning Session

```
Hi Claude! I need to plan our next 2-week sprint for the "Mobile App" project.

Please help me:
1. Review the current project status
2. Identify high-priority items from the backlog
3. Create a sprint planning issue
4. Break down large tasks into smaller work items
```

### Claude's Workflow

**Step 1: Analyze Project Status**

Claude will use `summarize_project_status` to understand the current state:

```
Let me check the project status for the last 30 days...
```

This provides:
- Recent activity metrics (issues created/updated)
- Status distribution (New, In Progress, Resolved)
- Priority breakdown
- Team workload by assignee

**Step 2: Search Backlog**

Claude will use `search_redmine_issues` to find backlog items:

```
Let me search for unassigned high-priority items...
```

**Step 3: Create Sprint Structure**

Claude will use `create_redmine_issue` to set up the sprint:

```
Creating sprint planning issue for Sprint 12 (Jan 15-28)...
```

**Step 4: Break Down Work**

Claude will help decompose large tasks:

```
I notice issue #456 is quite large. Let me create sub-tasks:
- API endpoint implementation
- Frontend integration
- Testing and documentation
```

## Interactive Examples

### Example 1: Quick Sprint Setup

**You:**
```
Create a sprint for project ID 5, duration 2 weeks starting Monday.
Focus on bug fixes and the "user authentication" feature.
```

**Claude:**
```
I'll set up Sprint 15 for you:

1. First, let me review the project status...
   [Uses: summarize_project_status(project_id=5, days=14)]

2. Found 8 critical bugs and 3 authentication-related issues.

3. Creating sprint planning issue...
   [Uses: create_redmine_issue(
       project_id=5,
       subject="Sprint 15: Bug Fixes & Authentication (Jan 15-28)",
       description="Sprint Goals:\n- Resolve 8 critical bugs\n- Complete user authentication feature\n- Team capacity: 80 hours"
   )]

4. Would you like me to:
   - Create individual work items for each bug?
   - Assign issues to team members?
   - Set up the sprint board?
```

### Example 2: Capacity Planning

**You:**
```
How much work is currently assigned to the team for project ID 3?
Can we take on 5 more issues this sprint?
```

**Claude:**
```
Let me analyze the team's current workload...

[Uses: summarize_project_status(project_id=3, days=14)]

Current Sprint Status:
- 12 issues in progress across 4 team members
- Average: 3 issues per person
- 8 issues still in "New" status

[Uses: list_my_redmine_issues(project_id=3)]

Recommendation: The team has capacity for 3-4 more issues this sprint.
5 additional issues may overload the sprint. Consider:
- Prioritizing the top 3 items
- Deferring 2 items to next sprint
- Re-assigning work if some team members have lighter loads

Would you like me to help prioritize which issues to include?
```

### Example 3: Sprint Retrospective Prep

**You:**
```
Prepare a sprint retrospective summary for project ID 7.
What did we complete vs. plan?
```

**Claude:**
```
Analyzing Sprint 14 performance...

[Uses: summarize_project_status(project_id=7, days=14)]
[Uses: search_redmine_issues(query="Sprint 14")]

Sprint 14 Retrospective (Jan 1-14):

Completed Work:
- ✓ 15 issues resolved (83% of planned 18)
- ✓ 3 critical bugs fixed
- ✓ User dashboard feature delivered

Incomplete Work:
- ✗ 3 issues carried over to Sprint 15
- ✗ API optimization postponed

Key Metrics:
- Velocity: 15 issues completed
- Cycle time: Average 3.2 days
- Bug ratio: 20% (3/15)

Team Activity:
- Most active: Alice (6 issues)
- Issues updated: 42 updates across 15 issues

Insights:
- Team slightly over-committed (18 planned vs 15 completed)
- Consider reducing commitment by 15% next sprint
- Bug fixes took longer than estimated

Would you like me to create a retrospective issue with these findings?
```

## Useful Prompts

### Project Analysis
```
"Analyze project ID [X]'s health for the last 30 days"
"What are the most active issues in project [name]?"
"Show me the priority distribution for project [X]"
```

### Sprint Creation
```
"Create a 2-week sprint starting [date] for project [X]"
"Set up sprint structure with planning, review, and retro issues"
"Generate sprint goals based on recent activity"
```

### Work Breakdown
```
"Break down issue #[X] into smaller tasks"
"Create sub-tasks for the [feature name] epic"
"Split this large issue into 3-5 manageable pieces"
```

### Capacity Management
```
"What's the current team workload for project [X]?"
"Can we fit [N] more issues this sprint?"
"Who has capacity for additional work?"
```

## Tools Used

This recipe leverages the following Redmine MCP tools:

| Tool | Purpose |
|------|---------|
| `list_redmine_projects` | Find project IDs and details |
| `summarize_project_status` | Analyze project health and metrics |
| `search_redmine_issues` | Find backlog and sprint items |
| `get_redmine_issue` | Get detailed issue information |
| `create_redmine_issue` | Create sprint issues and work items |
| `update_redmine_issue` | Assign issues and update status |
| `list_my_redmine_issues` | Check personal and team workload |

## Tips & Best Practices

1. **Start with Status Review** - Always analyze project status before planning
2. **Use Realistic Estimates** - Account for 70-80% capacity due to interruptions
3. **Break Down Large Items** - Tasks > 8 hours should be decomposed
4. **Track Consistently** - Update issues regularly for accurate metrics
5. **Review Velocity Trends** - Use past sprint data to improve estimates

## Troubleshooting

**Issue: Can't create issues in project**
- Verify you have "Add issues" permission in Redmine
- Check project ID is correct using `list_redmine_projects`

**Issue: Missing project data**
- Ensure date range covers the sprint period
- Check if project has recent activity

**Issue: Team capacity unclear**
- Use `list_my_redmine_issues` with filters for each team member
- Consider custom fields for time estimates if available

## Related Recipes

- [Daily Standup Assistant](./daily-standup.md) - Track daily progress
- [Issue Triage Helper](./issue-triage.md) - Organize incoming issues
- [Release Notes Generator](./release-notes.md) - Document sprint deliverables

## Learn More

- [Tool Reference](../docs/tool-reference.md) - Complete MCP tool documentation
- [Redmine Issues API](https://www.redmine.org/projects/redmine/wiki/Rest_Issues) - API details
- [Sprint Planning Guide](https://www.atlassian.com/agile/scrum/sprint-planning) - Best practices
