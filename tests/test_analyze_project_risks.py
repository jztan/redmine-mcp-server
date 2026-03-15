"""
Test cases for the analyze_project_risks MCP tool.
"""

import os
import sys
from datetime import datetime, timedelta, date

import pytest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import analyze_project_risks  # noqa: E402
from redminelib.exceptions import ResourceNotFoundError  # noqa: E402


def _make_project(pid=1, name="Test Project", identifier="test-project"):
    p = Mock()
    p.id = pid
    p.name = name
    p.identifier = identifier
    return p


def _make_issue(
    issue_id,
    subject="Issue",
    status_name="New",
    priority_name="Normal",
    assigned_to_name=None,
    updated_on=None,
    estimated_hours=None,
    spent_hours=None,
):
    issue = Mock()
    issue.id = issue_id
    issue.subject = subject

    status = Mock()
    status.name = status_name
    issue.status = status

    priority = Mock()
    priority.name = priority_name
    issue.priority = priority

    if assigned_to_name:
        assigned = Mock()
        assigned.name = assigned_to_name
        issue.assigned_to = assigned
    else:
        issue.assigned_to = None

    issue.updated_on = updated_on or datetime.now()
    issue.estimated_hours = estimated_hours
    issue.spent_hours = spent_hours

    return issue


def _make_version(
    vid, name="v1.0", status="open", due_date=None
):
    v = Mock()
    v.id = vid
    v.name = name
    v.status = status
    v.due_date = due_date
    return v


def _make_relation(rel_id, issue_id, issue_to_id, relation_type):
    r = Mock()
    r.id = rel_id
    r.issue_id = issue_id
    r.issue_to_id = issue_to_id
    r.relation_type = relation_type
    return r


class TestAnalyzeProjectRisks:
    """Test cases for the analyze_project_risks tool."""

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_project_not_found(self, mock_redmine):
        """Test error when project doesn't exist."""
        mock_redmine.project.get.side_effect = ResourceNotFoundError()

        result = await analyze_project_risks(999)

        assert "error" in result
        assert "999" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_healthy_project(self, mock_redmine):
        """Test a project with no risks returns low risk score."""
        project = _make_project()
        mock_redmine.project.get.return_value = project
        mock_redmine.project_version.filter.return_value = []

        # Open issues: all recently updated, assigned, normal priority
        issues = [
            _make_issue(1, "Issue 1", assigned_to_name="Alice"),
            _make_issue(2, "Issue 2", assigned_to_name="Bob"),
        ]
        mock_redmine.issue.filter.return_value = issues
        mock_redmine.issue.get.side_effect = lambda iid, **kw: _make_issue_with_no_relations(iid)

        result = await analyze_project_risks(1)

        assert result["risk_summary"]["level"] == "low"
        assert result["risk_summary"]["score"] == 0
        assert result["overdue_versions"] == []
        assert result["blocked_issues"] == []
        assert result["stale_issues"] == []
        assert result["unassigned_high_priority"] == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_overdue_versions(self, mock_redmine):
        """Test detection of overdue versions."""
        project = _make_project()
        mock_redmine.project.get.return_value = project

        yesterday = date.today() - timedelta(days=5)
        versions = [
            _make_version(1, "v1.0", "open", yesterday),
            _make_version(2, "v2.0", "open", date.today() + timedelta(days=30)),
            _make_version(3, "v0.9", "closed", yesterday),  # closed, ignored
        ]
        mock_redmine.project_version.filter.return_value = versions

        # Version issues query for overdue version
        version_issues = [_make_issue(10, "Incomplete")]

        def filter_side_effect(**kwargs):
            if kwargs.get("fixed_version_id") == 1:
                return version_issues
            return []

        mock_redmine.issue.filter.side_effect = filter_side_effect
        mock_redmine.issue.get.side_effect = lambda iid, **kw: _make_issue_with_no_relations(iid)

        result = await analyze_project_risks(1)

        assert len(result["overdue_versions"]) == 1
        assert result["overdue_versions"][0]["id"] == 1
        assert result["overdue_versions"][0]["days_overdue"] == 5
        assert result["overdue_versions"][0]["open_issues"] == 1
        assert "overdue version" in result["risk_summary"]["factors"][0]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_stale_issues(self, mock_redmine):
        """Test detection of stale issues."""
        project = _make_project()
        mock_redmine.project.get.return_value = project
        mock_redmine.project_version.filter.return_value = []

        stale_date = datetime.now() - timedelta(days=30)
        issues = [
            _make_issue(1, "Stale issue", updated_on=stale_date),
            _make_issue(2, "Fresh issue", updated_on=datetime.now()),
        ]
        mock_redmine.issue.filter.return_value = issues
        mock_redmine.issue.get.side_effect = lambda iid, **kw: _make_issue_with_no_relations(iid)

        result = await analyze_project_risks(1, stale_days=14)

        assert len(result["stale_issues"]) == 1
        assert result["stale_issues"][0]["id"] == 1
        assert "stale issue" in result["risk_summary"]["factors"][0].lower()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_unassigned_high_priority(self, mock_redmine):
        """Test detection of unassigned high-priority issues."""
        project = _make_project()
        mock_redmine.project.get.return_value = project
        mock_redmine.project_version.filter.return_value = []

        issues = [
            _make_issue(1, "Critical bug", priority_name="High"),
            _make_issue(2, "Urgent fix", priority_name="Urgent"),
            _make_issue(3, "Normal task", priority_name="Normal"),
            _make_issue(4, "Assigned high", priority_name="High", assigned_to_name="Alice"),
        ]
        mock_redmine.issue.filter.return_value = issues
        mock_redmine.issue.get.side_effect = lambda iid, **kw: _make_issue_with_no_relations(iid)

        result = await analyze_project_risks(1)

        assert len(result["unassigned_high_priority"]) == 2
        ids = {i["id"] for i in result["unassigned_high_priority"]}
        assert ids == {1, 2}
        assert any("unassigned" in f.lower() for f in result["risk_summary"]["factors"])

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_blocked_issues(self, mock_redmine):
        """Test detection of blocked issues via relations."""
        project = _make_project()
        mock_redmine.project.get.return_value = project
        mock_redmine.project_version.filter.return_value = []

        issues = [
            _make_issue(1, "Blocked task"),
            _make_issue(2, "Blocker task"),
        ]
        mock_redmine.issue.filter.return_value = issues

        # Issue 1 is blocked by issue 2
        def get_with_relations(iid, **kwargs):
            issue = _make_issue(iid, f"Issue {iid}")
            if iid == 1:
                rel = _make_relation(100, 2, 1, "blocked")
                issue.relations = [rel]
            elif iid == 2:
                rel = _make_relation(100, 2, 1, "blocks")
                issue.relations = [rel]
            else:
                issue.relations = []
            return issue

        mock_redmine.issue.get.side_effect = get_with_relations

        result = await analyze_project_risks(1)

        assert len(result["blocked_issues"]) == 1
        assert result["blocked_issues"][0]["id"] == 1
        assert result["blocked_issues"][0]["blocked_by"] == 2
        assert len(result["blocking_chains"]) == 1
        assert result["blocking_chains"][0]["blocker_id"] == 2

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_workload_imbalance(self, mock_redmine):
        """Test detection of workload imbalance."""
        project = _make_project()
        mock_redmine.project.get.return_value = project
        mock_redmine.project_version.filter.return_value = []

        # Alice has 15 issues, Bob has 1, Charlie has 1 — Alice > 2x average
        issues = [
            _make_issue(i, f"Issue {i}", assigned_to_name="Alice")
            for i in range(1, 16)
        ] + [
            _make_issue(16, "Issue 16", assigned_to_name="Bob"),
            _make_issue(17, "Issue 17", assigned_to_name="Charlie"),
        ]

        mock_redmine.issue.filter.return_value = issues
        mock_redmine.issue.get.side_effect = lambda iid, **kw: _make_issue_with_no_relations(iid)

        result = await analyze_project_risks(1)

        assert "Alice" in result["workload"]["distribution"]
        assert result["workload"]["distribution"]["Alice"] == 15
        assert "imbalance_warning" in result["workload"]
        assert any("imbalance" in f.lower() for f in result["risk_summary"]["factors"])

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_time_analysis(self, mock_redmine):
        """Test time tracking analysis (estimated vs actual)."""
        project = _make_project()
        mock_redmine.project.get.return_value = project
        mock_redmine.project_version.filter.return_value = []

        issues = [
            _make_issue(1, "On track", estimated_hours=10, spent_hours=5),
            _make_issue(2, "Over budget", estimated_hours=8, spent_hours=20),
            _make_issue(3, "No estimate"),
        ]
        mock_redmine.issue.filter.return_value = issues
        mock_redmine.issue.get.side_effect = lambda iid, **kw: _make_issue_with_no_relations(iid)

        result = await analyze_project_risks(1)

        assert "time_analysis" in result
        ta = result["time_analysis"]
        assert ta["total_estimated_hours"] == 18.0
        assert ta["total_spent_hours"] == 25.0
        assert len(ta["over_budget_issues"]) == 1
        assert ta["over_budget_issues"][0]["id"] == 2
        assert ta["over_budget_issues"][0]["overage_pct"] == 150.0

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_time_analysis_disabled(self, mock_redmine):
        """Test that time analysis can be disabled."""
        project = _make_project()
        mock_redmine.project.get.return_value = project
        mock_redmine.project_version.filter.return_value = []
        mock_redmine.issue.filter.return_value = []
        mock_redmine.issue.get.side_effect = lambda iid, **kw: _make_issue_with_no_relations(iid)

        result = await analyze_project_risks(1, include_time_analysis=False)

        assert "time_analysis" not in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_risk_score_capped_at_100(self, mock_redmine):
        """Test that risk score never exceeds 100."""
        project = _make_project()
        mock_redmine.project.get.return_value = project

        # Many overdue versions
        yesterday = date.today() - timedelta(days=10)
        versions = [
            _make_version(i, f"v{i}", "open", yesterday) for i in range(1, 6)
        ]
        mock_redmine.project_version.filter.return_value = versions

        # Many stale, unassigned high-priority issues
        stale_date = datetime.now() - timedelta(days=60)
        issues = [
            _make_issue(
                i,
                f"Bad issue {i}",
                priority_name="High",
                updated_on=stale_date,
                estimated_hours=1,
                spent_hours=100,
            )
            for i in range(1, 20)
        ]

        def filter_side_effect(**kwargs):
            if kwargs.get("fixed_version_id"):
                return issues[:3]
            return issues

        mock_redmine.issue.filter.side_effect = filter_side_effect
        mock_redmine.issue.get.side_effect = lambda iid, **kw: _make_issue_with_no_relations(iid)

        result = await analyze_project_risks(1)

        assert result["risk_summary"]["score"] <= 100
        assert result["risk_summary"]["level"] == "high"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_empty_project(self, mock_redmine):
        """Test analysis of a project with no issues or versions."""
        project = _make_project()
        mock_redmine.project.get.return_value = project
        mock_redmine.project_version.filter.return_value = []
        mock_redmine.issue.filter.return_value = []

        result = await analyze_project_risks(1)

        assert result["risk_summary"]["score"] == 0
        assert result["risk_summary"]["level"] == "low"
        assert result["risk_summary"]["factors"] == []
        assert result["project"]["id"] == 1

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_general_error(self, mock_redmine):
        """Test general exception handling."""
        mock_redmine.project.get.side_effect = Exception("Connection failed")

        result = await analyze_project_risks(1)

        assert "error" in result
        assert "analyzing risks for project 1" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_version_fetch_failure_graceful(self, mock_redmine):
        """Test that version fetch failure doesn't break the analysis."""
        project = _make_project()
        mock_redmine.project.get.return_value = project
        mock_redmine.project_version.filter.side_effect = Exception("Version API error")
        mock_redmine.issue.filter.return_value = []

        result = await analyze_project_risks(1)

        # Should still return a result, just without version data
        assert "error" not in result
        assert result["overdue_versions"] == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_relation_fetch_failure_graceful(self, mock_redmine):
        """Test that failing to fetch relations for one issue doesn't crash."""
        project = _make_project()
        mock_redmine.project.get.return_value = project
        mock_redmine.project_version.filter.return_value = []

        issues = [_make_issue(1, "Issue 1"), _make_issue(2, "Issue 2")]
        mock_redmine.issue.filter.return_value = issues
        mock_redmine.issue.get.side_effect = Exception("Cannot fetch")

        result = await analyze_project_risks(1)

        # Should still complete without error
        assert "error" not in result
        assert result["blocked_issues"] == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_medium_risk_level(self, mock_redmine):
        """Test that medium risk level is assigned for scores 30-59."""
        project = _make_project()
        mock_redmine.project.get.return_value = project

        # One overdue version (15 points) + some unassigned high priority (20 points)
        yesterday = date.today() - timedelta(days=1)
        mock_redmine.project_version.filter.return_value = [
            _make_version(1, "v1.0", "open", yesterday)
        ]

        issues = [
            _make_issue(1, "Urgent 1", priority_name="High"),
            _make_issue(2, "Urgent 2", priority_name="Urgent"),
        ]

        def filter_side_effect(**kwargs):
            if kwargs.get("fixed_version_id"):
                return [_make_issue(10)]
            return issues

        mock_redmine.issue.filter.side_effect = filter_side_effect
        mock_redmine.issue.get.side_effect = lambda iid, **kw: _make_issue_with_no_relations(iid)

        result = await analyze_project_risks(1, include_time_analysis=False)

        assert result["risk_summary"]["level"] == "medium"
        assert 30 <= result["risk_summary"]["score"] < 60

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_stale_days_parameter(self, mock_redmine):
        """Test that stale_days parameter controls stale threshold."""
        project = _make_project()
        mock_redmine.project.get.return_value = project
        mock_redmine.project_version.filter.return_value = []

        # Issue updated 5 days ago
        five_days_ago = datetime.now() - timedelta(days=5)
        issues = [_make_issue(1, "Recent-ish", updated_on=five_days_ago)]
        mock_redmine.issue.filter.return_value = issues
        mock_redmine.issue.get.side_effect = lambda iid, **kw: _make_issue_with_no_relations(iid)

        # With default 14 days: not stale
        result = await analyze_project_risks(1, stale_days=14)
        assert len(result["stale_issues"]) == 0

        # With 3 days: stale
        result = await analyze_project_risks(1, stale_days=3)
        assert len(result["stale_issues"]) == 1

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_many_unassigned_issues_risk(self, mock_redmine):
        """Test risk score increases when many issues are unassigned."""
        project = _make_project()
        mock_redmine.project.get.return_value = project
        mock_redmine.project_version.filter.return_value = []

        # 8 out of 10 unassigned
        issues = [_make_issue(i, f"Issue {i}") for i in range(1, 9)] + [
            _make_issue(9, "Assigned 1", assigned_to_name="Alice"),
            _make_issue(10, "Assigned 2", assigned_to_name="Bob"),
        ]
        mock_redmine.issue.filter.return_value = issues
        mock_redmine.issue.get.side_effect = lambda iid, **kw: _make_issue_with_no_relations(iid)

        result = await analyze_project_risks(1, include_time_analysis=False)

        assert any("unassigned issues" in f.lower() for f in result["risk_summary"]["factors"])

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_project_info_in_result(self, mock_redmine):
        """Test that project info is included in result."""
        project = _make_project(42, "My Project", "my-proj")
        mock_redmine.project.get.return_value = project
        mock_redmine.project_version.filter.return_value = []
        mock_redmine.issue.filter.return_value = []

        result = await analyze_project_risks(42)

        assert result["project"]["id"] == 42
        assert result["project"]["name"] == "My Project"
        assert result["project"]["identifier"] == "my-proj"


def _make_issue_with_no_relations(issue_id):
    """Helper to create a mock issue with empty relations for get() calls."""
    issue = _make_issue(issue_id, f"Issue {issue_id}")
    issue.relations = []
    return issue
