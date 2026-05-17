"""Policy guard for Agent actions.

Each Agent declares its capability matrix here. Before any side-effecting
call (write to AWS, write to KB, etc.) the Agent must invoke ``guard``
which raises ``PolicyDenied`` on violation.

This complements IAM (which is the actual enforcement boundary) by:
  * giving early, human-readable error messages,
  * requiring an explicit user-confirmation token for destructive ops,
  * emitting an audit log line per check.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .logging_utils import get_logger

logger = get_logger(__name__)


class PolicyDenied(PermissionError):
    """Raised when an Agent attempts an action outside its policy."""


@dataclass(frozen=True)
class AgentPolicy:
    name: str
    read_resources: frozenset[str] = field(default_factory=frozenset)
    write_resources: frozenset[str] = field(default_factory=frozenset)
    requires_confirm: bool = False  # writes need user confirm token


# ---------------------------------------------------------------------- #
# Policy registry — keep in sync with infra/nlops_stack.py IAM roles.
# ---------------------------------------------------------------------- #
POLICIES: dict[str, AgentPolicy] = {
    "Router": AgentPolicy(
        name="Router",
        read_resources=frozenset({"bedrock", "session"}),
    ),
    "Discovery": AgentPolicy(
        name="Discovery",
        read_resources=frozenset(
            {"bedrock", "cloudwatch", "logs", "xray", "ec2", "ecs", "rds", "elb"}
        ),
    ),
    "Analysis": AgentPolicy(
        name="Analysis",
        read_resources=frozenset(
            {"bedrock", "cloudwatch", "logs", "xray", "devops_agent_ro"}
        ),
    ),
    "Execution": AgentPolicy(
        name="Execution",
        read_resources=frozenset({"bedrock"}),
        write_resources=frozenset(
            {"ecs", "autoscaling", "rds", "ec2", "devops_agent_rw"}
        ),
        requires_confirm=True,
    ),
    "Knowledge": AgentPolicy(
        name="Knowledge",
        read_resources=frozenset({"bedrock", "kb"}),
        write_resources=frozenset({"kb"}),
        requires_confirm=False,
    ),
    "Report": AgentPolicy(
        name="Report",
        read_resources=frozenset({"bedrock"}),
        write_resources=frozenset({"s3:reports"}),
        requires_confirm=False,
    ),
}


@dataclass
class GuardContext:
    """Per-request context passed to ``guard``."""
    user_id: str
    trace_id: str
    user_confirmed: bool = False
    confirm_token: str | None = None


def guard(
    agent: str,
    action: str,            # "read" | "write"
    resources: Iterable[str],
    ctx: GuardContext,
) -> None:
    """Validate that ``agent`` may perform ``action`` on ``resources``.

    Raises :class:`PolicyDenied` on violation.
    """
    policy = POLICIES.get(agent)
    if policy is None:
        raise PolicyDenied(f"unknown agent: {agent}")

    allowed = policy.read_resources if action == "read" else policy.write_resources
    not_allowed = [r for r in resources if r not in allowed]
    if not_allowed:
        logger.warning(
            "policy.deny",
            extra={
                "agent": agent,
                "action": action,
                "resources": list(resources),
                "denied": not_allowed,
                "user_id": ctx.user_id,
                "trace_id": ctx.trace_id,
            },
        )
        raise PolicyDenied(
            f"{agent} cannot {action} {not_allowed} (allowed: {sorted(allowed)})"
        )

    if action == "write" and policy.requires_confirm and not ctx.user_confirmed:
        logger.warning(
            "policy.confirm_required",
            extra={"agent": agent, "user_id": ctx.user_id, "trace_id": ctx.trace_id},
        )
        raise PolicyDenied(
            f"{agent} write requires user confirmation (missing confirm_token)"
        )

    logger.info(
        "policy.allow",
        extra={
            "agent": agent,
            "action": action,
            "resources": list(resources),
            "user_id": ctx.user_id,
            "trace_id": ctx.trace_id,
        },
    )
