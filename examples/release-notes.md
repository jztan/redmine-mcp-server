# Release Notes Generator

A Claude Code recipe for automatically generating professional release notes from Redmine issues.

## Overview

This recipe automates release notes creation by analyzing completed issues, grouping them by type, and formatting them in a user-friendly way. Perfect for product releases, sprint reviews, and customer communications.

## What This Recipe Does

1. **Gathers completed work** - Finds all resolved issues in a release period
2. **Categorizes changes** - Groups by type (features, bugs, improvements, etc.)
3. **Formats professionally** - Creates customer-ready release notes
4. **Generates changelogs** - Produces technical CHANGELOG.md format
5. **Highlights impacts** - Identifies breaking changes and migrations

## Prerequisites

- Redmine MCP Server installed and configured ([installation guide](../README.md#installation))
- MCP server running and connected to your Claude Code client
- Access to project with completed issues

## Usage Example

### Generating Release Notes

```
Hi Claude! Generate release notes for version 2.5.0.
Include all issues resolved between Jan 1-15, 2025 for project ID 3.
```

### Claude's Workflow

**Step 1: Find Completed Issues**

Claude will use `search_redmine_issues` to find resolved items:

```
Searching for issues closed between Jan 1-15...
```

**Step 2: Categorize Issues**

Claude groups issues by tracker type and impact:

```
Analyzing 47 completed issues...
- 15 Bug fixes
- 12 New features
- 8 Enhancements
- 5 Performance improvements
- 7 Documentation updates
```

**Step 3: Generate Formatted Notes**

Claude creates professional release notes:

```
# Release Notes - Version 2.5.0
Released: January 15, 2025

## Highlights
...
```

## Interactive Examples

### Example 1: Standard Release Notes

**You:**
```
Generate release notes for version 3.0.0 from issues resolved in the last 30 days
for project ID 5. Format for customers.
```

**Claude:**
```
Searching for completed issues in project 5...

[Uses: search_redmine_issues(project_id=5, status_id=5, updated_on=">=2024-12-15")]

Found 52 resolved issues. Let me categorize and format them...

[Uses: get_redmine_issue() for each to get full details]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 RELEASE NOTES - Version 3.0.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Release Date:** January 15, 2025
**Project:** Mobile Banking App
**Type:** Major Release

## 🎉 Highlights

This major release brings significant improvements to performance, security,
and user experience. We've resolved 52 issues including 18 new features,
22 bug fixes, and major architectural improvements.

## ✨ New Features (18)

**Account Management**
- **Biometric Login** (#701) - Support for Face ID and fingerprint authentication
- **Account Sharing** (#702) - Share read-only access with family members
- **Custom Account Names** (#703) - Personalize account nicknames

**Payments & Transfers**
- **Scheduled Payments** (#705) - Set up recurring and future-dated payments
- **International Transfers** (#706) - Send money to 50+ countries
- **Split Payments** (#707) - Divide bills among multiple accounts
- **Payment Templates** (#708) - Save frequently used payment details

**Cards**
- **Virtual Cards** (#710) - Generate instant virtual debit cards
- **Card Controls** (#711) - Set spending limits and restrictions
- **Card Freeze** (#712) - Temporarily freeze/unfreeze cards instantly

**Notifications**
- **Custom Alerts** (#715) - Configure notifications for specific transaction types
- **Weekly Digest** (#716) - Receive weekly spending summaries
- **Fraud Alerts** (#717) - Real-time security notifications

**Other Features**
- **Dark Mode** (#720) - Full dark theme support across the app
- **Spending Analytics** (#721) - Visualize spending patterns and trends
- **Budget Tracking** (#722) - Set and monitor monthly budgets
- **Document Vault** (#723) - Securely store financial documents
- **Export Data** (#724) - Download transaction history as CSV/PDF

## 🐛 Bug Fixes (22)

**Critical Fixes**
- Fixed crash when viewing large transaction history (#801)
- Resolved payment processing timeout issues (#802)
- Fixed incorrect balance display after transfers (#803)
- Corrected currency conversion calculation errors (#804)

**High Priority Fixes**
- Fixed Face ID authentication failure on iOS 17 (#810)
- Resolved push notification delivery issues (#811)
- Fixed search not returning recent transactions (#812)
- Corrected timezone handling for scheduled payments (#813)
- Fixed PDF statement generation errors (#814)

**General Fixes**
- Fixed UI overlap on small screen devices (#820)
- Resolved animation stuttering on account switching (#821)
- Fixed keyboard covering input fields (#822)
- Corrected sorting order in transaction list (#823)
- Fixed profile photo upload failures (#824)
- Resolved session timeout issues (#825)
- Fixed card number masking inconsistencies (#826)
- Corrected accessibility labels for screen readers (#827)
- [... 8 more minor fixes ...]

## ⚡ Performance Improvements (7)

- **50% faster app launch time** (#901) - Optimized initial data loading
- **Reduced memory usage by 30%** (#902) - Improved caching strategy
- **Instant transaction search** (#903) - Added local database indexing
- **Smoother scrolling** (#904) - Optimized list rendering
- **Faster sync** (#905) - Improved backend API performance
- **Reduced battery drain** (#906) - Optimized background refresh
- **Smaller app size** (#907) - Reduced download size by 15MB

## 🔧 Technical Improvements (5)

- Upgraded to React Native 0.73 (#950)
- Migrated to TypeScript 5.0 (#951)
- Updated all security dependencies (#952)
- Implemented automated testing for payments (#953)
- Added comprehensive error logging (#954)

## 📚 Documentation

- Added biometric setup guide (#960)
- Updated API documentation for v3 (#961)
- Created video tutorials for new features (#962)

## ⚠️ Breaking Changes

**For Developers:**
- API v2 deprecated - migrate to v3 by March 2025
- Minimum iOS version now 15.0 (was 13.0)
- Minimum Android version now 8.0 / API 26 (was 6.0 / API 23)

**For Users:**
- Older devices (iPhone 6s and earlier) are no longer supported
- Previous payment templates need to be recreated in new format

## 🔄 Migration Guide

**Updating from v2.x:**
1. Backup your data using "Export Data" before updating
2. Update to version 3.0.0 from your app store
3. Re-authenticate using biometric if you had PIN enabled
4. Recreate any payment templates
5. Review new privacy settings

## 📊 Statistics

- **52** issues resolved
- **18** new features
- **22** bugs fixed
- **7** performance improvements
- **40+** contributors
- **500+** commits

## 🙏 Acknowledgments

Special thanks to our beta testers and the community for reporting issues
and providing feedback that made this release possible.

## 📝 Full Changelog

For a complete list of changes, see [CHANGELOG.md](./CHANGELOG.md)

## 🐞 Known Issues

- Dark mode not applied to settings on some Android devices (#1001)
- Occasional sync delay on slow connections (#1002)

These will be addressed in v3.0.1 (planned for Jan 22, 2025).

## 💬 Feedback

Have feedback or found a bug? Please report it at:
- GitHub Issues: https://github.com/yourorg/mobile-app/issues
- Support Email: support@yourbank.com
- In-app feedback: Settings → Help & Feedback

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Would you like me to:
- Generate a technical CHANGELOG.md version?
- Create a blog post announcement?
- Draft customer email notification?
- Generate social media posts?
```

### Example 2: Technical Changelog

**You:**
```
Create a CHANGELOG.md entry for version 2.3.1 (patch release)
from issues resolved last week for project 8.
```

**Claude:**
```
Generating technical changelog...

[Uses: search_redmine_issues(project_id=8, status_id=5, updated_on=">=2025-01-08")]

Found 8 resolved issues (patch release). Creating CHANGELOG.md format...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## [2.3.1] - 2025-01-15

### Fixed

- Fixed memory leak in WebSocket connection handler (#456)
  - Properly cleanup event listeners on disconnect
  - Reduces memory usage by ~50MB over 24h period
  - Resolves: Issue #456

- Resolved race condition in payment processing (#457)
  - Added transaction locking mechanism
  - Prevents duplicate charge attempts
  - Fixes: Duplicate payments reported by 3 customers
  - Resolves: Issue #457

- Corrected timestamp handling for UTC+12 timezone (#458)
  - Fixed date calculation edge case
  - Affects users in Pacific/Auckland timezone
  - Resolves: Issue #458

- Fixed API rate limit header parsing (#459)
  - Correctly parse X-RateLimit-* headers
  - Prevents unnecessary request throttling
  - Resolves: Issue #459

### Security

- Updated cryptography dependency to 42.0.0 (#460)
  - Addresses CVE-2024-XXXXX
  - No code changes required
  - Resolves: Issue #460

### Performance

- Optimized database query in user lookup (#461)
  - Added index on users.email column
  - Reduces lookup time from 120ms to 8ms
  - Resolves: Issue #461

### Documentation

- Updated API rate limit documentation (#462)
  - Clarified rate limit headers
  - Added code examples
  - Resolves: Issue #462

- Fixed typos in deployment guide (#463)
  - Corrected Docker commands
  - Updated environment variable names
  - Resolves: Issue #463

### Technical Details

**Database Migrations:**
```sql
-- Migration 2025011501: Add index to users table
CREATE INDEX idx_users_email ON users(email);
```

**Dependency Updates:**
- cryptography: 41.0.0 → 42.0.0
- requests: 2.31.0 → 2.32.0

**Upgrade Notes:**
- No breaking changes
- Database migration runs automatically
- Recommended restart after deployment

**Commits:** 14
**Contributors:** 3 (@alice, @bob, @carol)
**Files Changed:** 18
**Lines Added:** 247
**Lines Removed:** 189

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This can be added to your CHANGELOG.md file. Would you like me to:
- Format this for keep-a-changelog.com standard?
- Generate git commit message for the release?
- Create GitHub release notes?
```

### Example 3: Sprint Release Summary

**You:**
```
Create a sprint release summary for Sprint 14 (project ID 2).
Suitable for sharing with stakeholders.
```

**Claude:**
```
Generating stakeholder-friendly sprint summary...

[Uses: summarize_project_status(project_id=2, days=14)]
[Uses: search_redmine_issues(project_id=2, fixed_version="Sprint 14")]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Sprint 14 Release Summary
**E-Commerce Platform**
**Sprint Period:** January 1-14, 2025
**Status:** ✅ Successfully Completed

## Executive Summary

Sprint 14 focused on checkout optimization and mobile experience improvements.
We completed 23 of 25 planned items (92% completion rate), delivering key
features that reduce cart abandonment and improve mobile conversion.

## Key Deliverables

### 🎯 Strategic Goals Achieved (3/3)

✅ **Reduce Checkout Friction**
- Implemented one-click checkout for returning customers
- Added guest checkout option
- Reduced checkout steps from 5 to 3
- **Impact:** Expected 15-20% improvement in conversion rate

✅ **Improve Mobile Experience**
- Redesigned mobile product pages
- Optimized images for mobile loading
- Added touch-friendly navigation
- **Impact:** 40% faster mobile page load

✅ **Payment Options Expansion**
- Integrated Apple Pay and Google Pay
- Added buy-now-pay-later option
- **Impact:** Supports 95% of customer payment preferences

## Completed Work Breakdown

### Features Delivered (8)
- One-click checkout (#301)
- Guest checkout flow (#302)
- Apple Pay integration (#303)
- Google Pay integration (#304)
- Buy-now-pay-later via Affirm (#305)
- Saved payment methods (#306)
- Mobile navigation redesign (#307)
- Product image optimization (#308)

### Bugs Fixed (12)
- Cart items disappearing on page refresh (#401)
- Promo code not applying correctly (#402)
- Shipping calculator errors (#403)
- Mobile payment form issues (#404)
- [... 8 more bug fixes ...]

### Technical Improvements (3)
- Checkout performance optimization (#501)
- Mobile analytics tracking (#502)
- Payment security audit (#503)

## Customer Impact

**Improvements Users Will Notice:**
- ⚡ 60% faster checkout process
- 📱 Smoother mobile shopping experience
- 💳 More payment options (Apple Pay, Google Pay, BNPL)
- 🛒 Cart persistence across devices
- 🎁 Easier promo code application

**Behind the Scenes:**
- Enhanced security for payment processing
- Better error handling and recovery
- Improved analytics for business insights

## Metrics & Performance

**Sprint Velocity:**
- Planned: 25 story points
- Completed: 23 story points
- Completion Rate: 92%

**Quality:**
- Bugs introduced: 2 (low severity)
- Test coverage: 94% (+2% from last sprint)
- Production incidents: 0

**Team Performance:**
- Average cycle time: 2.8 days
- Issues completed: 23
- Code reviews: 47

## Deferred Items (2)

**#309 - Wishlist Feature**
- Reason: Deprioritized for payment features
- Status: Moved to Sprint 15

**#310 - Product Recommendations**
- Reason: Requires ML model training
- Status: Moved to Sprint 16

## Risks & Mitigations

**Identified Risks:**
- New payment integrations need monitoring
- Mobile changes require thorough testing

**Mitigations Implemented:**
- Extended QA period for payment flows
- Phased rollout for mobile changes (10% → 50% → 100%)
- Enhanced monitoring and alerting

## Next Sprint Preview

**Sprint 15 Focus (Jan 15-28):**
- Wishlist functionality
- Email cart recovery
- Loyalty program integration
- Performance monitoring dashboard

## Recognition

**MVP Contributors:**
- @alice - Led payment integration effort
- @bob - Mobile optimization wizard
- @carol - Solved complex cart persistence issue

**Team Feedback:**
- "Best sprint yet in terms of collaboration"
- "Payment integration was complex but well executed"
- "Mobile improvements look fantastic"

## Attachments

- 📊 [Sprint Metrics Dashboard](link)
- 📱 [Mobile Screenshots](link)
- 📈 [Performance Benchmarks](link)
- 🎥 [Feature Demo Video](link)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Would you like me to:
- Create a presentation version (slides)?
- Generate email announcement?
- Create customer-facing release notes?
- Export to PDF?
```

### Example 4: Hotfix Release Notes

**You:**
```
Generate emergency hotfix release notes for version 4.2.1
Critical security fix deployed today, project ID 6.
```

**Claude:**
```
Creating hotfix release notes...

[Uses: search_redmine_issues(project_id=6, fixed_version="4.2.1")]
[Uses: get_redmine_issue() for critical issues]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚨 SECURITY HOTFIX RELEASE - Version 4.2.1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Release Date:** January 15, 2025 (Emergency Release)
**Release Type:** Security Hotfix
**Severity:** CRITICAL
**Action Required:** Update immediately

## ⚠️ Critical Security Fix

This hotfix addresses a critical security vulnerability that could allow
unauthorized access to user accounts under specific conditions.

**Issue Fixed:**
- **CVE-2025-XXXXX: Authentication bypass vulnerability** (#999)
  - Severity: Critical (CVSS 9.8)
  - Impact: Potential unauthorized account access
  - Affected Versions: 4.0.0 - 4.2.0
  - Fixed in: 4.2.1

**Technical Details:**
Under specific race conditions, the authentication middleware could skip
validation checks, allowing unauthenticated requests to access protected
endpoints.

**Affected Systems:**
- All deployments running versions 4.0.0 through 4.2.0
- Estimated 1,200 active installations affected

**Evidence of Exploitation:**
- No evidence of active exploitation detected
- Identified through internal security audit
- Reported responsibly by security team

## 🔒 What We Fixed

- Implemented additional authentication check in middleware
- Added request validation before route handler execution
- Enhanced logging for authentication failures
- Added automated tests for edge cases

**Code Changes:**
- Files modified: 3
- Lines changed: 47
- Test coverage: 100% for auth flows

## ⚡ Immediate Action Required

**For System Administrators:**

1. **Update immediately** to version 4.2.1
   ```bash
   # Update via package manager
   npm install app@4.2.1

   # Or pull latest Docker image
   docker pull yourorg/app:4.2.1
   ```

2. **Restart all services**
   ```bash
   systemctl restart your-app
   ```

3. **Verify the fix**
   ```bash
   # Check version
   your-app --version
   # Should output: 4.2.1
   ```

4. **Review logs** for suspicious activity
   - Check authentication logs from past 30 days
   - Look for: "AUTH_BYPASS_ATTEMPT" entries
   - Report any findings to security@yourorg.com

**For Users:**
- Web app: No action needed (automatically updated)
- Desktop app: Restart application to auto-update
- Mobile app: Update from App Store/Google Play

## 📊 Additional Fixes

While deploying the security fix, we included:

**Bug Fixes (2):**
- Fixed session timeout calculation (#997)
- Corrected CORS header handling (#998)

## 🔍 Security Measures Implemented

**Immediate:**
- Deployed fix to production within 4 hours of discovery
- Notified all enterprise customers via email
- Published security advisory

**Ongoing:**
- Enhanced automated security scanning
- Additional penetration testing scheduled
- Security audit of related authentication code

## 📅 Timeline

- **Jan 15, 06:00 UTC** - Vulnerability discovered during audit
- **Jan 15, 08:00 UTC** - Fix developed and tested
- **Jan 15, 09:00 UTC** - Emergency release approved
- **Jan 15, 10:00 UTC** - Version 4.2.1 released
- **Jan 15, 10:30 UTC** - Enterprise customers notified
- **Jan 15, 11:00 UTC** - Public security advisory published

## 🆘 Support

**Urgent Issues:**
- Emergency hotline: +1-555-SECURITY
- Email: security@yourorg.com
- Slack: #security-incident

**Update Assistance:**
- Support portal: https://support.yourorg.com
- Email: support@yourorg.com

## 📝 Security Advisory

Full security advisory: https://security.yourorg.com/CVE-2025-XXXXX

**Disclosure:**
We follow responsible disclosure practices. Details will be published
30 days after 95% of installations have updated.

## ✅ Verification

After updating, verify the fix:

```bash
# Check version
curl http://localhost:8080/version
# Expected: {"version": "4.2.1"}

# Test authentication (should fail appropriately)
curl http://localhost:8080/api/protected -H "Authorization: invalid"
# Expected: 401 Unauthorized
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**This is a critical security release. Update immediately.**

For questions or concerns: security@yourorg.com

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Would you like me to:
- Draft customer notification email?
- Create internal incident report?
- Generate security advisory details?
- Prepare social media announcement?
```

## Useful Prompts

### Release Notes Generation
```
"Generate release notes for version [X.Y.Z]"
"Create changelog for issues resolved last [timeframe]"
"Release notes for sprint [N] in project [ID]"
"Customer-facing release announcement for [version]"
```

### Filtering & Grouping
```
"Show only bug fixes in version [X.Y.Z]"
"List new features from sprint [N]"
"Group changes by priority/impact"
"Highlight breaking changes"
```

### Formatting
```
"Format as CHANGELOG.md"
"Create customer announcement email"
"Generate blog post about release"
"Format for GitHub releases"
```

### Analysis
```
"What are the highlights of this release?"
"Identify breaking changes"
"Which issues had most impact?"
"Compare this release to [previous version]"
```

## Tools Used

This recipe leverages the following Redmine MCP tools:

| Tool | Purpose |
|------|---------|
| `search_redmine_issues` | Find issues in release/version/timeframe |
| `get_redmine_issue` | Get detailed issue descriptions |
| `summarize_project_status` | Get overall project metrics |
| `list_redmine_projects` | Identify project for release notes |

## Tips & Best Practices

1. **Use Version/Milestone Tracking** - Tag issues with target version in Redmine
2. **Write Clear Issue Titles** - They become release note line items
3. **Categorize Issues** - Use trackers (Bug, Feature, etc.) consistently
4. **Document Breaking Changes** - Flag breaking changes in issue description
5. **Include Migration Steps** - Document upgrade procedures
6. **Review Before Publishing** - Always review generated notes for accuracy

## Release Note Templates

### Keep a Changelog Format
```markdown
## [Version] - YYYY-MM-DD
### Added
- New features

### Changed
- Changes to existing functionality

### Deprecated
- Soon-to-be removed features

### Removed
- Removed features

### Fixed
- Bug fixes

### Security
- Security fixes
```

### Semantic Versioning
- **Major** (X.0.0): Breaking changes
- **Minor** (x.Y.0): New features, backwards compatible
- **Patch** (x.y.Z): Bug fixes, backwards compatible

## Automation Ideas

### Auto-generate on Tag
```bash
# Git hook: Generate notes when tagging release
git tag -a v1.2.3 -m "Release 1.2.3"
claude "Generate release notes for version 1.2.3"
```

### Scheduled Sprint Notes
```
"Every Friday at 5pm, generate sprint release summary"
```

### Customer Communication
```
"After generating notes, draft customer email and blog post"
```

## Troubleshooting

**Issue: Missing issues in notes**
- Check version/milestone tags in Redmine
- Verify date range covers all resolved issues
- Ensure issues are marked as "Resolved" or "Closed"

**Issue: Incorrect categorization**
- Verify tracker types are set correctly
- Check custom fields are populated
- Update issue metadata before generating

**Issue: Too much technical detail**
- Specify "customer-facing" format
- Ask to "summarize for non-technical audience"
- Request "executive summary" version

## Related Recipes

- [Sprint Planning Assistant](./sprint-planning.md) - Plan releases
- [Health Check Monitor](./health-check.md) - Verify release quality
- [Issue Triage Helper](./issue-triage.md) - Prepare issues for release

## Learn More

- [Tool Reference](../docs/tool-reference.md) - Complete MCP tool documentation
- [Keep a Changelog](https://keepachangelog.com/) - Changelog best practices
- [Semantic Versioning](https://semver.org/) - Version numbering guide
