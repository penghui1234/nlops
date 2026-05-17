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
    from src.orchestrator.engine import Orchestrator
    from src.agents.router import RouterAgent
    orch = Orchestrator()
    orch.register(RouterAgent.__new__(RouterAgent))  # bypass __init__ (no Bedrock client)
    assert "router" in orch.tools


def test_mcp_server_lists_allowed_tools():
    from src.mcp_server.private_tools import server
    resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert "result" in resp
    assert any(t["name"] == "get_service_owner" for t in resp["result"]["tools"])
