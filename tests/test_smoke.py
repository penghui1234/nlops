"""Smoke tests — verify imports and basic policy / plan logic."""
from __future__ import annotations

import os

import pytest

# Ensure DOA stays in mock mode for these unit tests
os.environ.setdefault("DOA_AGENT_SPACE_ID", "")
os.environ.setdefault("REPORT_BUCKET", "")
os.environ.setdefault("SESSIONS_TABLE", "")


def test_import_all_modules():
    """All top-level modules import without errors."""
    import src                           # noqa: F401
    import src.common.llm                # noqa: F401
    import src.common.policy             # noqa: F401
    import src.common.session            # noqa: F401
    import src.common.audit              # noqa: F401
    import src.agents.base               # noqa: F401
    import src.agents.router             # noqa: F401
    import src.agents.discovery          # noqa: F401
    import src.agents.analysis           # noqa: F401
    import src.agents.knowledge          # noqa: F401
    import src.agents.execution          # noqa: F401
    import src.agents.report             # noqa: F401
    import src.orchestrator.engine       # noqa: F401
    import src.tools.devops_agent        # noqa: F401
    import src.mcp_server.server         # noqa: F401
    import src.mcp_server.private_tools  # noqa: F401
    import src.mcp_server._real_impl     # noqa: F401


def test_policy_router_read_only():
    from src.common.policy import GuardContext, guard, PolicyDenied
    ctx = GuardContext(user_id="u", trace_id="t")
    # Router: read OK
    guard("Router", "read", ["bedrock"], ctx)
    # Router: write denied
    with pytest.raises(PolicyDenied):
        guard("Router", "write", ["s3:reports"], ctx)


def test_policy_execution_requires_confirm():
    from src.common.policy import GuardContext, guard, PolicyDenied
    ctx_no = GuardContext(user_id="u", trace_id="t", user_confirmed=False)
    with pytest.raises(PolicyDenied):
        guard("Execution", "write", ["devops_agent_rw"], ctx_no)
    ctx_ok = GuardContext(user_id="u", trace_id="t", user_confirmed=True)
    guard("Execution", "write", ["devops_agent_rw"], ctx_ok)


def test_orchestrator_register_and_schema():
    """Strands-based orchestrator: build_default returns NLOpsStrandsAgent
    with a tools registry (5 high-level + Router subsumed by Strands)."""
    from src.orchestrator.factory import build_default
    orch = build_default()
    # NLOpsStrandsAgent exposes legacy 'tools' dict for compat.
    # In environments without strands-agents installed it's None.
    assert orch is not None
    if hasattr(orch, "tools") and orch.tools:
        # Should have the 5 high-level agents
        assert "discovery" in orch.tools
        assert "analysis" in orch.tools
        assert "knowledge" in orch.tools
        assert "execution" in orch.tools
        assert "report" in orch.tools


def test_mcp_server_lists_allowed_tools():
    from src.mcp_server.private_tools import server
    resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert "result" in resp
    assert any(t["name"] == "get_service_owner" for t in resp["result"]["tools"])


# ---------------------------------------------------------------------------
# MOCK_MODE switch — tools should return canned demo data when set, and
# attempt real calls when unset (which we don't exercise here, but we
# verify the module's _is_mock helper behaves correctly).
# ---------------------------------------------------------------------------
def test_mock_mode_true_returns_canned_incidents(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    from src.mcp_server import private_tools as pt
    assert pt._is_mock() is True
    out = pt.discover_incidents.__wrapped__(status="open", time_range_hours=24) \
        if hasattr(pt.discover_incidents, "__wrapped__") else pt.discover_incidents(status="open", time_range_hours=24)
    # mock returns 2 canned incidents
    assert out["count"] == 2
    assert any(i["id"] == "INC-001" for i in out["incidents"])


def test_mock_mode_false_default(monkeypatch):
    monkeypatch.delenv("MOCK_MODE", raising=False)
    from src.mcp_server import private_tools as pt
    assert pt._is_mock() is False


def test_mock_mode_handles_truthy_strings(monkeypatch):
    from src.mcp_server import private_tools as pt
    for v in ("true", "TRUE", "1", "yes", "  true  "):
        monkeypatch.setenv("MOCK_MODE", v)
        assert pt._is_mock() is True, f"failed for {v!r}"
    for v in ("false", "0", "no", ""):
        monkeypatch.setenv("MOCK_MODE", v)
        assert pt._is_mock() is False, f"failed for {v!r}"


def test_mock_mode_get_service_owner_returns_catalog(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    from src.mcp_server import private_tools as pt
    out = pt.get_service_owner(service_name="payment-api")
    assert out["team"] == "payment-team"
    assert out["service"] == "payment-api"
