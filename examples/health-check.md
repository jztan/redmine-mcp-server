# Project Health Check Monitor

A Claude Code recipe for monitoring project health, identifying risks, and tracking key metrics in Redmine.

## Overview

This recipe provides comprehensive project health monitoring by analyzing issue trends, team activity, and potential bottlenecks. Perfect for project managers, team leads, and stakeholders who need visibility into project status.

## What This Recipe Does

1. **Analyzes project health** - Reviews activity, velocity, and issue distribution
2. **Identifies risks** - Flags stale issues, overdue items, and blockers
3. **Tracks metrics** - Monitors velocity, cycle time, and completion rates
4. **Generates reports** - Creates executive summaries and detailed analyses
5. **Provides recommendations** - Suggests actions to improve project health

## Prerequisites

- Redmine MCP Server installed and configured ([installation guide](../README.md#installation))
- MCP server running and connected to your Claude Code client
- Access to project with historical data

## Usage Example

### Running a Health Check

```
Hi Claude! Run a health check on project ID 5.
Analyze the last 30 days and identify any risks or issues.
```

### Claude's Workflow

**Step 1: Gather Project Data**

Claude will use `summarize_project_status` for overview:

```
Analyzing project health for the last 30 days...
```

**Step 2: Deep Dive Analysis**

Claude searches for specific issues:

```
Checking for stale issues, blockers, and overdue items...
```

**Step 3: Generate Health Report**

Claude creates a comprehensive health assessment:

```
PROJECT HEALTH REPORT
Overall Status: ⚠️ NEEDS ATTENTION
Score: 72/100
```

## Interactive Examples

### Example 1: Comprehensive Health Check

**You:**
```
Run a complete health check on project ID 3
```

**Claude:**
```
Running comprehensive health analysis for project 3...

[Uses: summarize_project_status(project_id=3, days=30)]
[Uses: search_redmine_issues() with various filters]
[Uses: list_my_redmine_issues(project_id=3)]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏥 PROJECT HEALTH REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Project:** E-Commerce Platform (ID: 3)
**Analysis Period:** Last 30 days (Dec 16, 2024 - Jan 15, 2025)
**Generated:** January 15, 2025 at 10:30 AM

## 📊 Overall Health Score: 72/100

**Status:** ⚠️ NEEDS ATTENTION

**Health Indicators:**
- ✅ Velocity: Good (85/100)
- ⚠️ Issue Aging: Concerning (60/100)
- ⚠️ Team Capacity: At Risk (65/100)
- ✅ Bug Ratio: Healthy (90/100)
- ⚠️ Blocker Count: Elevated (55/100)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 📈 Key Metrics (Last 30 Days)

**Activity Summary:**
- Issues created: 42
- Issues resolved: 38
- Net change: +4 (backlog growing slowly)
- Issues updated: 156
- Average updates per issue: 3.7

**Velocity & Throughput:**
- Completion rate: 90% (38/42)
- Average cycle time: 5.2 days
- Velocity trend: ↑ +12% vs previous period
- Work in progress: 23 issues

**Issue Distribution:**
```
Status Breakdown:
  New................... 12 (26%)
  In Progress.......... 18 (39%)
  Waiting Review....... 8 (17%)
  Resolved............. 6 (13%)
  Closed............... 2 (4%)

Priority Distribution:
  Immediate............ 2 (4%)
  High................. 15 (33%)
  Normal............... 22 (48%)
  Low.................. 7 (15%)

Tracker Distribution:
  Bug.................. 18 (39%)
  Feature.............. 16 (35%)
  Enhancement.......... 8 (17%)
  Support.............. 4 (9%)
```

**Team Metrics:**
```
Issues by Assignee:
  Alice................ 12 issues (52% utilization) ✅
  Bob.................. 15 issues (65% utilization) ⚠️
  Carol................ 8 issues (35% utilization) ✅
  Dave................. 18 issues (78% utilization) ⚠️
  Unassigned........... 12 issues ❌
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 🚨 Critical Issues & Risks

### HIGH SEVERITY (3 issues)

**1. Stale Blockers** ⚠️ HIGH RISK
- 2 issues marked as "Blocked" with no activity for >14 days
- Issues: #456, #457
- Impact: Blocking downstream work
- **Action Required:** Review blockers, escalate or unblock

**2. Overdue High-Priority Items** ⚠️ HIGH RISK
- 3 high-priority issues past due date
- Issues: #501, #502, #503
- Average overdue: 8 days
- **Action Required:** Re-prioritize or extend deadlines

**3. Team Capacity Imbalance** ⚠️ MEDIUM RISK
- Dave at 78% capacity (overloaded)
- 12 unassigned issues in queue
- **Action Required:** Rebalance workload, assign issues

### MEDIUM SEVERITY (4 issues)

**4. Aging New Issues** ⚠️
- 6 issues in "New" status for >7 days
- No assignee or priority set
- **Action Required:** Triage and assign

**5. Bug Backlog Growing** ⚠️
- Bug count increased from 14 to 18 (+29%)
- Bug resolution rate: 60% (below 75% target)
- **Action Required:** Focus sprint on bug fixes

**6. Long Review Cycles** ⚠️
- 8 issues in "Waiting Review" status
- Average review time: 4.5 days (target: 2 days)
- **Action Required:** Streamline review process

**7. Missing Documentation** ⚠️
- 12 completed features without documentation
- **Action Required:** Add docs before next release

### LOW SEVERITY (2 issues)

**8. Test Coverage Gaps** ℹ️
- 3 features merged without tests
- **Action Required:** Add tests retroactively

**9. Technical Debt Accumulating** ℹ️
- 5 "refactoring needed" comments in last sprint
- **Action Required:** Schedule tech debt sprint

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 📉 Concerning Trends

**1. Backlog Growth** ⚠️
```
Week 1: +2 issues
Week 2: +1 issue
Week 3: +3 issues
Week 4: +4 issues
Trend: Accelerating ↗️
```
**Analysis:** Input rate exceeding completion rate
**Recommendation:** Reduce new work, focus on completion

**2. Increasing Cycle Time** ⚠️
```
Week 1: 4.2 days avg
Week 2: 4.8 days avg
Week 3: 5.5 days avg
Week 4: 6.1 days avg
Trend: Degrading ↗️
```
**Analysis:** Work taking longer to complete
**Recommendation:** Identify bottlenecks, reduce WIP

**3. Bug Introduction Rate** ⚠️
```
Bugs fixed: 8
New bugs reported: 12
Bug ratio: 40% (target: <20%)
Trend: Above target ↗️
```
**Analysis:** Quality may be declining
**Recommendation:** Add testing, code reviews

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## ✅ Positive Indicators

**1. High Completion Rate** ✅
- 90% of started issues completed
- Above 80% target
- Excellent follow-through

**2. Active Collaboration** ✅
- 156 issue updates (high engagement)
- Average 3.7 comments per issue
- Strong team communication

**3. Velocity Improving** ✅
- +12% velocity vs last period
- Team productivity increasing
- Sprint commitments met

**4. Priority Management** ✅
- Only 4% immediate priority items (controlled)
- Good priority distribution
- Urgent issues handled promptly

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 🎯 Recommended Actions

### IMMEDIATE (This Week)

1. **Resolve Blockers** (Priority: CRITICAL)
   - Review issues #456, #457
   - Escalate or remove blocker status
   - Estimated impact: Unblock 5 downstream tasks

2. **Address Overdue Items** (Priority: HIGH)
   - Issues #501, #502, #503
   - Re-estimate or extend deadlines
   - Communicate new timeline to stakeholders

3. **Rebalance Team Load** (Priority: HIGH)
   - Move 3-4 issues from Dave to Alice/Carol
   - Assign 6 of 12 unassigned issues
   - Target: All team members at 50-60% capacity

### SHORT TERM (This Sprint)

4. **Triage Aged New Issues** (Priority: MEDIUM)
   - Review 6 issues in "New" >7 days
   - Assign priority and owner
   - Move to "In Progress" or defer

5. **Bug Fix Focus** (Priority: MEDIUM)
   - Dedicate 30% of sprint to bug fixes
   - Reduce bug backlog from 18 to 12
   - Target: <20% bug ratio

6. **Streamline Reviews** (Priority: MEDIUM)
   - Reduce review time from 4.5 to 2 days
   - Consider pair programming
   - Set SLA for review responses

### LONG TERM (Next Month)

7. **Reduce Backlog Growth** (Priority: MEDIUM)
   - Limit new work intake
   - Focus on completion over starting
   - Target: Backlog neutral or shrinking

8. **Improve Quality** (Priority: LOW)
   - Increase test coverage
   - Enhance code review process
   - Add automated testing

9. **Tech Debt Sprint** (Priority: LOW)
   - Schedule dedicated tech debt week
   - Address accumulated refactoring needs
   - Improve code maintainability

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 📅 Monitoring Plan

**Daily:**
- Monitor blocker status
- Track high-priority item progress
- Check team capacity

**Weekly:**
- Review backlog growth
- Analyze velocity trends
- Assess bug ratio

**Monthly:**
- Comprehensive health check (like this report)
- Strategic planning based on trends
- Team retrospective on metrics

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 📋 Summary

**Current State:**
- Project is generally healthy but showing warning signs
- Velocity is good but sustainability is a concern
- Team capacity issues need immediate attention

**Key Concerns:**
- Blockers not being resolved
- Work taking longer (cycle time increasing)
- Bug ratio above target

**Action Priority:**
1. Resolve blockers (#456, #457)
2. Rebalance team workload
3. Focus on bug fixes this sprint

**Outlook:**
With corrective actions, project should improve to 80+ health score
within 2 weeks. Continue monitoring backlog growth and cycle time.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Would you like me to:
- Create action items for recommended fixes?
- Generate a presentation for stakeholders?
- Set up weekly health check reminders?
- Dive deeper into specific metrics?
```

### Example 2: Quick Health Pulse

**You:**
```
Give me a quick health pulse for project 8. Just the key numbers.
```

**Claude:**
```
Running quick health check...

[Uses: summarize_project_status(project_id=8, days=7)]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚡ QUICK HEALTH PULSE - Project 8
Last 7 days

**Overall:** 🟢 HEALTHY (Score: 85/100)

**Key Metrics:**
- Velocity: 12 issues completed
- Cycle time: 3.1 days (↓ -15% improvement)
- Backlog: 34 issues (↓ -3 this week)
- Bug ratio: 18% (✅ below 20% target)
- Team capacity: 58% avg (✅ healthy)

**Status:**
- New: 5 | In Progress: 15 | Review: 4 | Done: 10

**Alerts:**
- 🟢 No blockers
- 🟢 No overdue high-priority items
- 🟡 2 issues aging >14 days (low priority)

**Trend:** ↗️ Improving
**Action needed:** None - continue current pace

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Example 3: Risk Assessment

**You:**
```
What are the biggest risks to completing Sprint 15 on time? Project ID 4.
```

**Claude:**
```
Analyzing sprint risks for Sprint 15...

[Uses: search_redmine_issues(project_id=4, fixed_version="Sprint 15")]
[Uses: get_redmine_issue() for in-progress items]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 SPRINT 15 RISK ASSESSMENT
Project: Mobile App | Sprint End: Jan 22 (7 days remaining)

**Overall Risk Level:** 🟠 MEDIUM-HIGH

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 🔴 HIGH RISK ITEMS (3)

**1. Blocked Critical Feature** 🚨
- Issue: #789 "Payment integration"
- Status: Blocked by external API documentation
- Risk: May miss sprint deadline
- Impact: High - Committed to customer
- Mitigation:
  * Escalate to vendor for API docs today
  * Prepare alternative mock implementation
  * Communicate potential delay to stakeholders
- Probability: 70% of slipping

**2. Underestimated Complexity** ⚠️
- Issue: #790 "Database migration"
- Status: In progress, 40% complete
- Risk: More complex than estimated (3d → 7d actual)
- Impact: High - Blocking 3 other tasks
- Mitigation:
  * Add second developer to pair
  * Extend sprint by 2 days if needed
  * Identify tasks to defer if necessary
- Probability: 60% of slipping

**3. Key Developer Availability** ⚠️
- Developer: @alice
- Capacity: Out sick last 2 days, 5 issues assigned
- Risk: May not complete assigned work
- Impact: Medium - 5 issues at risk
- Mitigation:
  * Reassign 2-3 issues to @bob
  * Defer lowest priority items
  * Pair programming when @alice returns
- Probability: 50% some issues slip

## 🟡 MEDIUM RISK ITEMS (2)

**4. Testing Bandwidth** ⚠️
- 8 features need QA testing
- QA team has capacity for 5-6 this sprint
- Risk: Some features won't be tested
- Mitigation: Developers do smoke testing, defer 2 features

**5. Dependencies on External Team** ⚠️
- Issue #795 needs design mockups from UX team
- UX team backlogged, may deliver late
- Risk: Development may start late
- Mitigation: Use wireframes to start, refine with final designs

## 🟢 LOW RISK ITEMS (12)

- 12 issues on track for completion
- No blockers or dependencies
- Team has capacity

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 📊 Sprint Progress

**Commitment:**
- Planned: 18 issues / 45 story points
- Completed: 5 issues / 12 story points (27%)
- In Progress: 11 issues / 28 story points (62%)
- Not Started: 2 issues / 5 story points (11%)

**Velocity Projection:**
- Current pace: 1.7 points/day
- Days remaining: 7
- Projected completion: 32/45 points (71%)
- **Risk: Will likely miss 13 points of work**

**Burn-down Status:**
```
Ideal:   45 → 33 → 21 → 9 → 0
Actual:  45 → 43 → 38 → 33 → ...
Status:  Behind by ~10 points ⚠️
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 🎯 RECOMMENDATIONS

**Immediate Actions (Today):**
1. Escalate API documentation request for #789
2. Add second dev to #790 (database migration)
3. Reassign 3 issues from @alice to @bob

**Sprint Adjustments:**
1. **Defer to Sprint 16:** (5 points)
   - #796 "Settings page redesign" (low priority)
   - #797 "Analytics dashboard" (nice-to-have)

2. **Fast-track:** (focus resources)
   - #789 "Payment integration" (critical)
   - #790 "Database migration" (blocking)

3. **Risk Acceptance:**
   - Accept that 2-3 features may not be fully tested
   - Plan hotfix sprint if issues arise

**Probability of Success:**
- As-is: 30% (complete all 18 issues)
- With adjustments: 75% (complete 15/18 critical issues)
- Recommended: Defer 2 items, focus on 16

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Would you like me to:
- Create a risk mitigation plan issue?
- Draft email to stakeholders about sprint risk?
- Suggest specific tasks to defer?
- Set up daily risk monitoring?
```

### Example 4: Team Health Check

**You:**
```
How is the team doing? Check workload balance and burnout risk for project 5.
```

**Claude:**
```
Analyzing team health and workload...

[Uses: summarize_project_status(project_id=5, days=30)]
[Uses: list_my_redmine_issues() for each team member]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

👥 TEAM HEALTH ASSESSMENT
Project: Backend Services | Last 30 days

**Overall Team Health:** 🟡 MODERATE (68/100)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 📊 Team Capacity & Workload

**Alice (@alice)** - Senior Developer
```
Active issues: 8
Capacity: 45% ✅ Healthy
Velocity: 2.5 issues/week (consistent)
Trend: Stable
Burnout risk: 🟢 LOW

Recent activity:
  • Completed 12 issues last month
  • Average cycle time: 3.2 days
  • No overdue items
  • Balanced mix of features and bugs

Health indicators:
  ✅ Consistent velocity
  ✅ Good work-life balance signals
  ✅ Active code reviewer
  ⚠️ Could take on 2-3 more issues
```

**Bob (@bob)** - Developer
```
Active issues: 16
Capacity: 85% ⚠️ High
Velocity: 4 issues/week (above average)
Trend: Increasing ↗️
Burnout risk: 🟡 MODERATE

Recent activity:
  • Completed 19 issues last month (↑ +40% vs previous)
  • Average cycle time: 4.8 days (increasing)
  • 2 overdue items
  • Working late hours (commits at 11pm+)

Health indicators:
  ⚠️ Capacity at 85% (target: 50-70%)
  ⚠️ Cycle time increasing (overload signal)
  ⚠️ Late-night activity pattern
  🚨 Comments: "This is taking longer than expected"

RECOMMENDATION: Reduce Bob's load immediately
  • Move 4-5 issues to other team members
  • Check in on work-life balance
  • Review time estimates (may be underestimating)
```

**Carol (@carol)** - Junior Developer
```
Active issues: 6
Capacity: 40% ✅ Healthy
Velocity: 1.8 issues/week (appropriate for junior)
Trend: Improving ↗️
Burnout risk: 🟢 LOW

Recent activity:
  • Completed 8 issues last month
  • Average cycle time: 5.5 days
  • Frequent questions/help requests (learning)
  • Good progress on skill development

Health indicators:
  ✅ Appropriate capacity for junior dev
  ✅ Receiving mentorship (20+ review comments)
  ✅ Velocity improving month-over-month
  💡 Ready for slightly more complex tasks

RECOMMENDATION: Increase Carol's capacity gradually
  • Assign 2-3 medium complexity issues
  • Continue pairing with senior devs
  • Consider as backup for Bob's work
```

**Dave (@dave)** - Tech Lead
```
Active issues: 14 (4 high priority)
Capacity: 75% ⚠️ High
Velocity: 3 issues/week
Trend: Variable
Burnout risk: 🟡 MODERATE-HIGH

Recent activity:
  • Completed 14 issues last month
  • Split between coding (60%) and reviews/planning (40%)
  • 15 code reviews performed
  • Leading architectural decisions

Health indicators:
  ⚠️ Balancing IC work + tech lead duties
  ⚠️ Context switching (many interruptions)
  ⚠️ Some blocked issues waiting on decisions
  💡 May need to delegate more

RECOMMENDATION: Reduce IC work, focus on leading
  • Move 3-4 coding tasks to team
  • Focus on unblocking others
  • Dedicate time for architecture/planning
  • Consider protected "focus time" blocks
```

**Unassigned Issues:** 14 ⚠️
```
Priority breakdown:
  High: 3 (assign immediately)
  Normal: 8 (triage this week)
  Low: 3 (backlog)

RECOMMENDATION: Assign high priority to Alice, normal to Carol
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## ⚠️ Burnout Risk Factors Detected

**1. Bob - Overload Pattern** 🚨
- Capacity: 85% (too high)
- Working after hours
- Cycle time increasing
- **Action:** Immediate workload reduction

**2. Dave - Context Switching** ⚠️
- Wearing too many hats
- Blocked on architectural decisions
- **Action:** Delegate IC work, focus on leading

**3. Team Imbalance** ⚠️
- Bob/Dave overloaded (80%+)
- Alice/Carol underutilized (40-45%)
- **Action:** Rebalance distribution

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 💡 Team Dynamics Insights

**Collaboration:**
- Code review distribution: Healthy (all members reviewing)
- Knowledge sharing: Good (pairing sessions logged)
- Communication: Active (3.7 comments per issue avg)

**Skill Development:**
- Carol progressing well (velocity ↑ 25% month-over-month)
- Team mentoring junior dev effectively
- No skill bottlenecks identified

**Bottlenecks:**
- Dave as single architectural decision maker
- Bob carrying too much individual work
- Some tasks blocked waiting on external dependencies

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 🎯 Recommended Actions

**IMMEDIATE (Today):**

1. **Rebalance Bob's Workload** (Priority: CRITICAL)
   ```
   Move from Bob to Alice:
     - #501 "API refactoring" (medium complexity)
     - #502 "Add caching layer" (Alice has expertise)
     - #503 "Update documentation" (low priority)

   Move from Bob to Carol:
     - #504 "Fix form validation" (good learning opportunity)
     - #505 "Add unit tests" (junior-appropriate)
   ```

2. **Check in with Bob** (Priority: HIGH)
   - 1-on-1 to discuss workload
   - Identify if personal factors contributing
   - Set boundaries for working hours
   - Review sprint commitments

3. **Assign High-Priority Unassigned Issues** (Priority: HIGH)
   ```
   To Alice:
     - #601 "Security patch" (high priority)
     - #602 "Performance optimization" (high priority)

   To Carol:
     - #603 "UI bug fix" (normal priority)
   ```

**THIS WEEK:**

4. **Restructure Dave's Role**
   - Block 4 hours daily for "focus time" (no meetings)
   - Delegate 3-4 IC tasks to team
   - Empower team to make more decisions independently

5. **Team Capacity Planning**
   - Target: 50-65% capacity per person
   - Buffer: 20% for unplanned work
   - Leave 15-20% for learning/improvement

6. **Implement WIP Limits**
   - Max 5 "In Progress" issues per person
   - Finish before starting new work
   - Reduce context switching

**ONGOING:**

7. **Weekly Team Health Check**
   - Monitor individual capacity
   - Track burnout indicators
   - Adjust workload proactively

8. **Promote Sustainable Pace**
   - No regular after-hours work
   - Encourage breaks and time off
   - Celebrate sustainable productivity

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 📈 Target State (4 weeks)

**Ideal Team Distribution:**
```
Alice:   10-12 issues (55% capacity) ← +5%
Bob:      8-10 issues (55% capacity) ← -30% 🎯
Carol:    8-10 issues (55% capacity) ← +15%
Dave:     6-8 issues (50% capacity)  ← -25% 🎯
```

**Success Metrics:**
- All team members at 50-65% capacity
- No after-hours work patterns
- Cycle time stable or decreasing
- Team velocity sustainable
- Burnout risk: All 🟢 LOW

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Would you like me to:
- Draft workload rebalancing plan?
- Create 1-on-1 discussion guides?
- Set up weekly health monitoring?
- Generate capacity planning spreadsheet?
```

## Useful Prompts

### Overall Health
```
"Run a health check on project [ID]"
"How healthy is project [name]?"
"Show me project health metrics for last [timeframe]"
"Generate a health report for all projects"
```

### Specific Analysis
```
"What are the risks to completing [sprint/release]?"
"Identify stale issues in project [ID]"
"Show me overdue items"
"Find blockers across all projects"
```

### Team Health
```
"Check team workload balance"
"Who is overloaded?"
"Assess burnout risk"
"Show team capacity distribution"
```

### Trends
```
"What's the velocity trend for project [ID]?"
"Is our backlog growing or shrinking?"
"Show cycle time trends"
"Track bug ratio over time"
```

## Tools Used

This recipe leverages the following Redmine MCP tools:

| Tool | Purpose |
|------|---------|
| `summarize_project_status` | Get comprehensive project metrics |
| `search_redmine_issues` | Find stale, overdue, or blocked issues |
| `get_redmine_issue` | Analyze specific issues in detail |
| `list_my_redmine_issues` | Check individual/team workload |
| `list_redmine_projects` | Multi-project health checks |

## Tips & Best Practices

1. **Regular Monitoring** - Run health checks weekly for early risk detection
2. **Track Trends** - Compare current vs previous periods for patterns
3. **Define Thresholds** - Set clear boundaries for healthy metrics
4. **Act Promptly** - Address warning signs before they become critical
5. **Automate Reporting** - Schedule regular health reports
6. **Share Transparently** - Keep stakeholders informed of health status

## Health Metrics Glossary

### Velocity
- **What:** Issues/points completed per time period
- **Healthy:** Consistent and sustainable
- **Warning:** Highly variable or declining

### Cycle Time
- **What:** Time from start to completion
- **Healthy:** 2-5 days for typical issues
- **Warning:** >7 days or increasing trend

### Bug Ratio
- **What:** Bugs / total issues
- **Healthy:** <20%
- **Warning:** >30% or increasing

### Team Capacity
- **What:** Active issues / theoretical capacity
- **Healthy:** 50-65%
- **Warning:** >75% (overload) or <30% (underutilized)

### Backlog Growth
- **What:** Net change in open issues
- **Healthy:** Stable or slightly decreasing
- **Warning:** Growing >10% per month

## Health Score Interpretation

- **90-100:** 🟢 Excellent - Project running smoothly
- **75-89:** 🟢 Good - Minor improvements possible
- **60-74:** 🟡 Fair - Some issues need attention
- **45-59:** 🟠 Concerning - Multiple risks present
- **<45:** 🔴 Critical - Immediate intervention required

## Automation Ideas

### Daily Health Pulse
```bash
# Morning check-in
alias health-check='claude "Quick health pulse for project 5"'
```

### Weekly Reports
```
"Every Monday at 9am, run comprehensive health check and email report"
```

### Alert on Risks
```
"Alert me if any project has blockers >7 days or health score <60"
```

### Dashboard Integration
```
"Export health metrics to spreadsheet weekly for tracking"
```

## Troubleshooting

**Issue: Incomplete health data**
- Ensure sufficient historical data (>30 days)
- Verify issues have status/priority set
- Check date fields are populated

**Issue: Inaccurate metrics**
- Review issue workflow configuration
- Ensure consistent use of statuses
- Validate time tracking practices

**Issue: Too many false positives**
- Adjust threshold values for your context
- Customize health score weights
- Filter for specific issue types

## Related Recipes

- [Sprint Planning Assistant](./sprint-planning.md) - Plan based on health insights
- [Issue Triage Helper](./issue-triage.md) - Address health issues
- [Daily Standup Generator](./daily-standup.md) - Daily team health pulse

## Learn More

- [Tool Reference](../docs/tool-reference.md) - Complete MCP tool documentation
- [Agile Metrics](https://www.atlassian.com/agile/project-management/metrics) - Understanding health metrics
- [Team Health](https://www.atlassian.com/team-playbook/health-monitor) - Assessing team well-being
