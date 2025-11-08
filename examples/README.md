# Redmine MCP Server - Example Recipes

Welcome to the Redmine MCP Server recipe collection! These examples demonstrate real-world workflows using Claude Code with the Redmine MCP Server.

## Available Recipes

### 🎯 [Sprint Planning Assistant](./sprint-planning.md)
Plan and organize sprints with AI assistance. This recipe helps you:
- Analyze project health and recent activity
- Create sprint structure and planning issues
- Break down large tasks into manageable work items
- Track team capacity and velocity
- Prepare sprint retrospectives

**Best for:** Project managers, scrum masters, team leads

---

### 📊 [Daily Standup Generator](./daily-standup.md)
Automate your daily standup reports and track progress. Features:
- Generate daily standup summaries
- Analyze recent issue activity
- Identify blockers and dependencies
- Create weekly progress reports
- Team standup summaries

**Best for:** Individual contributors, team members, distributed teams

---

### 🏷️ [Issue Triage Helper](./issue-triage.md)
Efficiently triage and prioritize incoming issues. Includes:
- Identify untriaged and unassigned issues
- Categorize by severity and type
- Suggest priorities and assignments
- Batch update operations
- Customer support triage workflows

**Best for:** Project managers, support teams, team leads

---

### 📝 [Release Notes Generator](./release-notes.md)
Automatically generate professional release notes from completed work. Supports:
- Customer-facing release announcements
- Technical CHANGELOG.md generation
- Sprint release summaries
- Hotfix and security release notes
- Breaking change identification

**Best for:** Product managers, release managers, technical writers

---

### 🏥 [Health Check Monitor](./health-check.md)
Monitor project health and identify risks proactively. Provides:
- Comprehensive project health scoring
- Risk identification and recommendations
- Team workload and burnout analysis
- Velocity and cycle time tracking
- Trend analysis and forecasting

**Best for:** Project managers, team leads, stakeholders

---

## Getting Started

### Prerequisites

1. **Install Redmine MCP Server**
   ```bash
   pip install redmine-mcp-server
   ```

2. **Configure and start the server**
   - Create a `.env` file with your Redmine credentials
   - Start the server: `redmine-mcp-server`
   - See [installation guide](../README.md#installation) for details

3. **Connect to Claude Code**
   ```bash
   claude mcp add --transport http redmine http://127.0.0.1:8000/mcp
   ```

### Using a Recipe

1. **Choose a recipe** from the list above based on your workflow
2. **Read the recipe** to understand what it does and how it works
3. **Copy a prompt** from the "Useful Prompts" section
4. **Paste in Claude Code** and let the AI assist you
5. **Customize** the prompts for your specific needs

## Recipe Structure

Each recipe includes:

- **Overview** - What the recipe does and when to use it
- **Prerequisites** - What you need to get started
- **Interactive Examples** - Real conversations with Claude showing the workflow
- **Useful Prompts** - Copy-paste prompts you can use immediately
- **Tools Used** - Which MCP tools the recipe leverages
- **Tips & Best Practices** - Expert advice for getting the most value
- **Troubleshooting** - Common issues and solutions
- **Related Recipes** - Complementary workflows

## Common Workflows

### Morning Routine
```
1. Run daily standup report
2. Check project health pulse
3. Review high-priority items
```

### Sprint Cadence
```
Sprint Start:  Sprint Planning Assistant
Daily:         Daily Standup Generator
Weekly:        Health Check Monitor
Sprint End:    Release Notes Generator
```

### Project Management
```
Incoming Work: Issue Triage Helper
Planning:      Sprint Planning Assistant
Monitoring:    Health Check Monitor
Delivery:      Release Notes Generator
```

## Tips for Success

1. **Start Simple** - Begin with basic prompts, then customize
2. **Be Specific** - Include project IDs, dates, and specific criteria
3. **Iterate** - Refine prompts based on results
4. **Combine Recipes** - Use multiple recipes together for comprehensive workflows
5. **Automate** - Create shell aliases or scripts for frequent tasks

## Example Automation

### Shell Aliases
```bash
# Add to ~/.bashrc or ~/.zshrc
alias standup='claude "Generate my standup report for today"'
alias health='claude "Run quick health check on project 5"'
alias triage='claude "Triage new issues in project 5"'
```

### Scheduled Reports
```bash
# Cron job for weekly health check (every Monday at 9am)
0 9 * * 1 claude "Run comprehensive health check on all projects and email report"
```

## Customization

All recipes can be customized for your needs:

- **Project IDs** - Replace example IDs with your projects
- **Time Ranges** - Adjust days/weeks for analysis
- **Thresholds** - Set custom health score thresholds
- **Formatting** - Request different output formats (Slack, email, etc.)
- **Filters** - Add project-specific filters and criteria

## Contributing New Recipes

Have a great workflow to share? We welcome contributions!

1. Follow the recipe template structure
2. Include real-world examples
3. Test all prompts and examples
4. Submit a pull request

See [Contributing Guide](../docs/contributing.md) for details.

## Troubleshooting

### Common Issues

**"No issues found"**
- Check project ID is correct
- Verify date ranges
- Ensure you have permissions

**"Tool not available"**
- Confirm MCP server is running
- Check Claude Code connection
- Verify server URL in config

**"Inaccurate results"**
- Review Redmine data quality
- Check issue statuses are set
- Verify custom fields are populated

### Getting Help

- [Troubleshooting Guide](../docs/troubleshooting.md) - Detailed solutions
- [Tool Reference](../docs/tool-reference.md) - Complete tool documentation
- [GitHub Issues](https://github.com/jztan/redmine-mcp-server/issues) - Report bugs or request features

## Learn More

- [Main README](../README.md) - Project overview and installation
- [Tool Reference](../docs/tool-reference.md) - Complete MCP tool documentation
- [Redmine API Documentation](https://www.redmine.org/projects/redmine/wiki/Rest_api) - API details
- [MCP Documentation](https://modelcontextprotocol.io/) - Model Context Protocol

## Feedback

Found these recipes helpful? Have suggestions for improvements? We'd love to hear from you!

- Share your success stories
- Suggest new recipes
- Report issues or improvements
- Contribute your own recipes

Happy automating! 🚀
