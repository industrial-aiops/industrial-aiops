"""``iaiops approve`` — grant a one-shot approval token for a gated operation.

Approver-gated (dual/review tier) tools consume exactly one matching token per
call; tokens expire after ``--ttl`` seconds. This replaces the static
``OPCUA_AUDIT_APPROVED_BY`` env var pattern with an auditable, expiring,
single-use grant stored under ``~/.iaiops/approvals/`` (0600).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import typer

from iaiops.cli._common import cli_errors, console
from iaiops.core.governance.approvals import DEFAULT_TTL_SECONDS, record_approval


@cli_errors
def approve_cmd(
    tool: str = typer.Argument(..., help="Tool name to approve (e.g. s7_write_db)"),
    endpoint: str = typer.Option(
        "", "--endpoint", help="Target endpoint/env the approval is scoped to"
    ),
    by: str = typer.Option(..., "--by", help="Name of the authorizing human"),
    ttl: int = typer.Option(
        DEFAULT_TTL_SECONDS, "--ttl", help="Token lifetime in seconds"
    ),
    rationale: str = typer.Option(
        "", "--rationale", help="Why this operation is authorized (audit trail)"
    ),
) -> None:
    """Record a one-shot approval token (consumed by the next matching call)."""
    approval = record_approval(
        tool, endpoint, approved_by=by, ttl_seconds=ttl, rationale=rationale
    )
    console.print_json(
        json.dumps(
            {
                "approved": True,
                "tool": approval.tool,
                "endpoint": approval.endpoint or None,
                "approved_by": approval.approved_by,
                "expires_at": datetime.fromtimestamp(
                    approval.expires_at, tz=UTC
                ).isoformat(),
                "one_shot": True,
            }
        )
    )
