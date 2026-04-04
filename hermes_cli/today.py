"""
Team task board dashboard — `hermes today` and `/today` CLI command.

Renders a concise view of all agents' tasks grouped by agent, with status
colours and priority indicators. Think of it as the morning standup read-out:
who is working on what, what's waiting for review, what's stuck.

Usage:
    hermes today                     # full board (all active tasks)
    hermes today --agent coder       # filter to one agent
    hermes today --status in_review  # filter to one status
    hermes today --all               # include completed/cancelled too
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from hermes_cli.colors import Colors, color, should_use_color


# ─────────────────────────────────────────────────────────────
# Status display metadata
# ─────────────────────────────────────────────────────────────

_STATUS_LABEL: Dict[str, str] = {
    "in_progress":    "IN PROGRESS",
    "in_review":      "IN REVIEW",
    "needs_revision": "NEEDS REVISION",
    "pending":        "PENDING",
    "completed":      "COMPLETED",
    "cancelled":      "CANCELLED",
}

_STATUS_COLOR: Dict[str, str] = {
    "in_progress":    Colors.GREEN,
    "in_review":      Colors.CYAN,
    "needs_revision": Colors.YELLOW,
    "pending":        Colors.DIM,
    "completed":      Colors.DIM,
    "cancelled":      Colors.DIM,
}

_PRIORITY_COLOR: Dict[str, str] = {
    "urgent": Colors.RED,
    "high":   Colors.YELLOW,
    "normal": "",
    "low":    Colors.DIM,
}

_STATUS_ORDER = [
    "in_progress",
    "in_review",
    "needs_revision",
    "pending",
    "completed",
    "cancelled",
]


# ─────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────

def _fmt_status(status: str) -> str:
    label = _STATUS_LABEL.get(status, status.upper())
    clr = _STATUS_COLOR.get(status, "")
    if clr:
        return color(f"[{label}]", clr)
    return f"[{label}]"


def _fmt_priority(priority: str) -> str:
    if priority in ("normal", None):
        return ""
    clr = _PRIORITY_COLOR.get(priority, "")
    badge = f"({priority})"
    if clr:
        return color(badge, clr)
    return badge


def _fmt_age(ts: float) -> str:
    """Human-readable age: '3h ago', '2d ago', etc."""
    try:
        delta = datetime.now(timezone.utc).timestamp() - ts
        if delta < 3600:
            mins = int(delta / 60)
            return f"{mins}m ago"
        if delta < 86400:
            hrs = int(delta / 3600)
            return f"{hrs}h ago"
        days = int(delta / 86400)
        return f"{days}d ago"
    except Exception:
        return ""


def _truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


# ─────────────────────────────────────────────────────────────
# Board rendering
# ─────────────────────────────────────────────────────────────

def _render_task_row(task: Dict[str, Any], indent: str = "  ") -> List[str]:
    lines = []

    status_str = _fmt_status(task["status"])
    priority_str = _fmt_priority(task.get("priority", "normal"))
    title = _truncate(task.get("title") or "(untitled)", 60)
    age = _fmt_age(task.get("updated_at", 0))

    priority_part = f" {priority_str}" if priority_str else ""
    age_part = color(f"  {age}", Colors.DIM) if age else ""
    task_id = color(task["id"], Colors.DIM)

    lines.append(
        f"{indent}{status_str} {task_id}  {title}{priority_part}{age_part}"
    )

    # Sub-details
    if task.get("branch"):
        lines.append(
            f"{indent}  {color('branch:', Colors.DIM)} {task['branch']}"
        )
    if task.get("pr_url"):
        lines.append(
            f"{indent}  {color('PR:', Colors.DIM)} {task['pr_url']}"
        )
    if task.get("handover_notes") and task["status"] in (
        "needs_revision", "in_review"
    ):
        note = _truncate(task["handover_notes"], 100)
        lines.append(
            f"{indent}  {color('notes:', Colors.DIM)} {note}"
        )

    return lines


def _render_board(
    tasks: List[Dict[str, Any]],
    filter_agent: Optional[str] = None,
    filter_status: Optional[str] = None,
    show_all: bool = False,
) -> str:
    """Render the full team board as a string."""
    lines: List[str] = []

    # ── Header ──────────────────────────────────────────────
    today_str = datetime.now().strftime("%a %b %-d, %Y")
    header = f"Team Task Board — {today_str}"
    width = max(62, len(header) + 4)
    lines.append(color("┌" + "─" * (width - 2) + "┐", Colors.BOLD))
    lines.append(
        color("│", Colors.BOLD)
        + f"  {header}".center(width - 2)
        + color("│", Colors.BOLD)
    )
    lines.append(color("└" + "─" * (width - 2) + "┘", Colors.BOLD))
    lines.append("")

    if not tasks:
        if filter_agent:
            lines.append(
                f"  No tasks for agent {color(filter_agent, Colors.BOLD)}."
            )
        else:
            lines.append("  No active tasks.")
        lines.append("")
        return "\n".join(lines)

    # ── Group by agent ──────────────────────────────────────
    agents: Dict[str, List[Dict]] = {}
    for task in tasks:
        owner = task.get("assigned_to") or "(unassigned)"
        agents.setdefault(owner, []).append(task)

    # Sort agent groups: unassigned last
    sorted_agents = sorted(agents.keys(), key=lambda a: ("zzz" if a == "(unassigned)" else a))

    for agent in sorted_agents:
        agent_tasks = agents[agent]
        # Sort within group by status priority, then priority rank
        agent_tasks.sort(key=lambda t: (
            _STATUS_ORDER.index(t["status"]) if t["status"] in _STATUS_ORDER else 99,
            ["urgent", "high", "normal", "low"].index(t.get("priority", "normal"))
            if t.get("priority", "normal") in ("urgent", "high", "normal", "low") else 2,
        ))

        active_count = sum(
            1 for t in agent_tasks
            if t["status"] not in ("completed", "cancelled")
        )
        count_label = f"[{active_count} active]" if active_count > 0 else "[0 active]"

        lines.append(
            color(f"◆ {agent}", Colors.BOLD)
            + "  "
            + color(count_label, Colors.DIM)
        )

        for task in agent_tasks:
            for row in _render_task_row(task, indent="  "):
                lines.append(row)

        lines.append("")

    # ── Summary footer ───────────────────────────────────────
    total = len(tasks)
    by_status: Dict[str, int] = {}
    for t in tasks:
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1

    footer_parts = [f"Total: {total}"]
    for s in _STATUS_ORDER:
        if s in by_status:
            label = _STATUS_LABEL[s].lower().replace(" ", "_")
            footer_parts.append(f"{by_status[s]} {label}")

    lines.append(color("─" * (width - 2), Colors.DIM))
    lines.append("  " + color("  |  ".join(footer_parts), Colors.DIM))

    if filter_agent:
        lines.append(
            "  " + color(f"Filtered to agent: {filter_agent}", Colors.DIM)
        )
    if not show_all:
        lines.append(
            "  " + color("Run with --all to include completed/cancelled tasks.", Colors.DIM)
        )
    lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

def today_command(args: Any = None) -> None:
    """
    Render the team task board.

    *args* is the argparse Namespace from `hermes today`, or None when called
    from the /today slash command (where we use defaults).
    """
    filter_agent = getattr(args, "agent", None) or None
    filter_status = getattr(args, "status", None) or None
    show_all = getattr(args, "all", False)

    try:
        from hermes_tasks import get_shared_task_db
        db = get_shared_task_db()
        tasks = db.list_tasks(
            assigned_to=filter_agent,
            status=filter_status,
            include_terminal=show_all,
            limit=200,
        )
    except Exception as exc:
        print(f"  Error reading task database: {exc}", file=sys.stderr)
        return

    board = _render_board(tasks, filter_agent, filter_status, show_all)
    print(board)
