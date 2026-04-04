#!/usr/bin/env python3
"""
Shared Task Tool — persistent cross-agent task board.

Agents (coder, reviewer, human) read and write a shared SQLite task store
(~/.hermes/tasks.db). Tasks flow through a defined lifecycle:

  pending → in_progress → in_review → needs_revision → in_progress → completed

On handover the tool optionally fires a Telegram DM notification to the
receiving agent's configured thread. Notifications are best-effort — failure
never blocks the handover itself.

Agent identity is determined (in priority order) by:
  1. HERMES_AGENT_NAME environment variable
  2. config.yaml → agent.name
  3. socket.gethostname() as a last resort
"""

import json
import logging
import os
import socket
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Agent identity helpers
# ─────────────────────────────────────────────

def _get_agent_name(kw_agent_name: Optional[str] = None) -> str:
    """Resolve the current agent's name from kwargs → env → config → hostname."""
    if kw_agent_name:
        return kw_agent_name

    env_name = os.getenv("HERMES_AGENT_NAME", "").strip()
    if env_name:
        return env_name

    try:
        from hermes_cli.config import load_config
        cfg = load_config()
        cfg_name = (cfg.get("agent") or {}).get("name", "").strip()
        if cfg_name:
            return cfg_name
    except Exception:
        pass

    return socket.gethostname()


def _resolve_agent_telegram_target(agent_name: str) -> Optional[str]:
    """Return the Telegram target string for *agent_name*, or None."""
    try:
        from hermes_cli.config import load_config
        cfg = load_config()
        notifications = (
            (cfg.get("shared_tasks") or {})
            .get("agent_notifications") or {}
        )
        return notifications.get(agent_name) or None
    except Exception:
        return None


# ─────────────────────────────────────────────
# Handover notification
# ─────────────────────────────────────────────

def _format_handover_message(task: Dict[str, Any], from_agent: str) -> str:
    lines = [
        f"[Task Handover from {from_agent}]",
        "",
        f"{task['id']}: {task['title']}",
        f"Status: {task['status']}",
        f"Priority: {task['priority']}",
    ]
    if task.get("branch"):
        lines.append(f"Branch: {task['branch']}")
    if task.get("pr_url"):
        lines.append(f"PR: {task['pr_url']}")
    if task.get("handover_notes"):
        lines.append("")
        lines.append(f"Notes: {task['handover_notes']}")
    return "\n".join(lines)


def _send_handover_notification(
    task: Dict[str, Any],
    from_agent: str,
    to_agent: str,
) -> bool:
    """Best-effort Telegram DM to the receiving agent's thread. Returns success."""
    try:
        target = _resolve_agent_telegram_target(to_agent)
        if not target:
            return False
        message = _format_handover_message(task, from_agent)
        from tools.send_message_tool import send_message_tool
        send_message_tool({"action": "send", "target": target, "message": message})
        return True
    except Exception as exc:
        logger.debug("Handover notification failed (non-fatal): %s", exc)
        return False


# ─────────────────────────────────────────────
# Tool handler
# ─────────────────────────────────────────────

def shared_task_tool(args: Dict[str, Any], **kw: Any) -> str:
    """Main handler dispatched by the tool registry."""
    action = args.get("action", "").strip().lower()
    agent_name = _get_agent_name(kw.get("agent_name"))

    try:
        from hermes_tasks import get_shared_task_db
        db = get_shared_task_db()
    except Exception as exc:
        return json.dumps({"error": f"Failed to open task database: {exc}"}, ensure_ascii=False)

    # ── create ──────────────────────────────────────────────────────────────
    if action == "create":
        title = (args.get("title") or "").strip()
        if not title:
            return json.dumps({"error": "title is required for create"}, ensure_ascii=False)
        try:
            task = db.create_task(
                title=title,
                created_by=agent_name,
                description=args.get("description"),
                assigned_to=args.get("assigned_to"),
                priority=args.get("priority", "normal"),
                branch=args.get("branch"),
                pr_url=args.get("pr_url"),
            )
            return json.dumps({"task": task, "action": "created"}, ensure_ascii=False)
        except ValueError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    # ── list ─────────────────────────────────────────────────────────────────
    elif action == "list":
        tasks = db.list_tasks(
            assigned_to=args.get("filter_assigned_to") or args.get("assigned_to"),
            status=args.get("filter_status") or args.get("status"),
            include_terminal=bool(args.get("include_terminal", False)),
            limit=int(args.get("limit", 100)),
        )
        return json.dumps(
            {"tasks": tasks, "count": len(tasks)},
            ensure_ascii=False,
        )

    # ── get ──────────────────────────────────────────────────────────────────
    elif action == "get":
        task_id = (args.get("task_id") or "").strip()
        if not task_id:
            return json.dumps({"error": "task_id is required for get"}, ensure_ascii=False)
        task = db.get_task(task_id)
        if not task:
            return json.dumps({"error": f"Task {task_id!r} not found"}, ensure_ascii=False)
        return json.dumps({"task": task}, ensure_ascii=False)

    # ── update ───────────────────────────────────────────────────────────────
    elif action == "update":
        task_id = (args.get("task_id") or "").strip()
        if not task_id:
            return json.dumps({"error": "task_id is required for update"}, ensure_ascii=False)
        updatable = {
            k: args[k] for k in (
                "title", "description", "status", "priority",
                "assigned_to", "branch", "pr_url", "handover_notes",
            ) if k in args and args[k] is not None
        }
        try:
            task = db.update_task(task_id, **updatable)
            return json.dumps({"task": task, "action": "updated"}, ensure_ascii=False)
        except ValueError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    # ── handover ─────────────────────────────────────────────────────────────
    elif action == "handover":
        task_id = (args.get("task_id") or "").strip()
        to_agent = (args.get("to_agent") or "").strip()
        handover_notes = (args.get("handover_notes") or "").strip()

        if not task_id:
            return json.dumps({"error": "task_id is required for handover"}, ensure_ascii=False)
        if not to_agent:
            return json.dumps({"error": "to_agent is required for handover"}, ensure_ascii=False)
        if not handover_notes:
            return json.dumps({"error": "handover_notes are required for handover"}, ensure_ascii=False)

        # Determine target status based on direction
        task = db.get_task(task_id)
        if not task:
            return json.dumps({"error": f"Task {task_id!r} not found"}, ensure_ascii=False)

        current_status = task["status"]
        # coder → reviewer: goes to in_review
        # reviewer → coder (revision): goes to needs_revision
        # default: in_review (for forward handover)
        new_status = args.get("status", "in_review")
        if new_status not in ("in_review", "needs_revision"):
            new_status = "in_review"

        try:
            updated = db.handover_task(
                task_id=task_id,
                from_agent=agent_name,
                to_agent=to_agent,
                handover_notes=handover_notes,
                new_status=new_status,
            )
        except ValueError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

        notified = _send_handover_notification(updated, agent_name, to_agent)
        return json.dumps(
            {"task": updated, "action": "handover", "notification_sent": notified},
            ensure_ascii=False,
        )

    # ── request_revision ─────────────────────────────────────────────────────
    elif action == "request_revision":
        task_id = (args.get("task_id") or "").strip()
        revision_notes = (args.get("handover_notes") or args.get("revision_notes") or "").strip()
        to_agent = (args.get("to_agent") or "").strip()

        if not task_id:
            return json.dumps({"error": "task_id is required"}, ensure_ascii=False)
        if not revision_notes:
            return json.dumps({"error": "handover_notes (revision notes) are required"}, ensure_ascii=False)

        try:
            updated = db.request_revision(
                task_id=task_id,
                reviewer=agent_name,
                revision_notes=revision_notes,
            )
            if to_agent:
                updated = db.update_task(task_id, assigned_to=to_agent)
        except ValueError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

        notified = False
        if to_agent:
            notified = _send_handover_notification(updated, agent_name, to_agent)

        return json.dumps(
            {"task": updated, "action": "request_revision", "notification_sent": notified},
            ensure_ascii=False,
        )

    # ── complete ─────────────────────────────────────────────────────────────
    elif action == "complete":
        task_id = (args.get("task_id") or "").strip()
        if not task_id:
            return json.dumps({"error": "task_id is required for complete"}, ensure_ascii=False)
        try:
            task = db.complete_task(task_id)
            return json.dumps({"task": task, "action": "completed"}, ensure_ascii=False)
        except ValueError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    # ── delete ───────────────────────────────────────────────────────────────
    elif action == "delete":
        task_id = (args.get("task_id") or "").strip()
        if not task_id:
            return json.dumps({"error": "task_id is required for delete"}, ensure_ascii=False)
        deleted = db.delete_task(task_id)
        if not deleted:
            return json.dumps({"error": f"Task {task_id!r} not found"}, ensure_ascii=False)
        return json.dumps({"action": "deleted", "task_id": task_id}, ensure_ascii=False)

    else:
        return json.dumps(
            {"error": f"Unknown action {action!r}. Valid: create, list, get, update, handover, request_revision, complete, delete"},
            ensure_ascii=False,
        )


def check_shared_task_requirements() -> bool:
    """Shared task tool has no external requirements — always available."""
    return True


# =============================================================================
# OpenAI Function-Calling Schema
# =============================================================================

SHARED_TASK_SCHEMA = {
    "name": "shared_task",
    "description": (
        "Manage the shared persistent task board visible to all agents and the human.\n\n"
        "Task lifecycle: pending → in_progress → in_review → needs_revision → in_progress → completed\n\n"
        "Actions:\n"
        "  create          — create a new task (title required)\n"
        "  list            — list tasks; filter by status or assigned_to\n"
        "  get             — fetch a single task by id\n"
        "  update          — change any field (status, notes, priority, branch, pr_url)\n"
        "  handover        — move task to another agent with context notes (sends Telegram DM)\n"
        "  request_revision — reviewer sends task back to coder with notes\n"
        "  complete        — mark a task completed\n"
        "  delete          — permanently remove a task\n\n"
        "Agent names are free-form: 'coder', 'reviewer', 'human', etc.\n"
        "Use handover when you finish your part and want the next agent to pick it up."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create", "list", "get", "update",
                    "handover", "request_revision", "complete", "delete",
                ],
                "description": "Operation to perform.",
            },
            "task_id": {
                "type": "string",
                "description": "Task ID (required for get/update/handover/request_revision/complete/delete).",
            },
            "title": {
                "type": "string",
                "description": "Short task title (required for create).",
            },
            "description": {
                "type": "string",
                "description": "Detailed task description.",
            },
            "status": {
                "type": "string",
                "enum": [
                    "pending", "in_progress", "in_review",
                    "needs_revision", "completed", "cancelled",
                ],
                "description": "New status. Must follow valid lifecycle transitions.",
            },
            "assigned_to": {
                "type": "string",
                "description": "Agent name to assign to (e.g. 'coder', 'reviewer', 'human').",
            },
            "priority": {
                "type": "string",
                "enum": ["low", "normal", "high", "urgent"],
                "description": "Task priority.",
            },
            "branch": {
                "type": "string",
                "description": "Git branch name associated with this task.",
            },
            "pr_url": {
                "type": "string",
                "description": "Pull request URL.",
            },
            "handover_notes": {
                "type": "string",
                "description": (
                    "Context for the receiving agent. Required for handover and request_revision. "
                    "Explain what was done, what to look for, any known edge cases."
                ),
            },
            "to_agent": {
                "type": "string",
                "description": "Agent to hand the task off to (required for handover and request_revision).",
            },
            "filter_status": {
                "type": "string",
                "description": "Filter list results by this status.",
            },
            "filter_assigned_to": {
                "type": "string",
                "description": "Filter list results by assigned agent name.",
            },
            "include_terminal": {
                "type": "boolean",
                "description": "Include completed/cancelled tasks in list results (default false).",
                "default": False,
            },
            "limit": {
                "type": "integer",
                "description": "Max tasks to return in list (default 100).",
                "default": 100,
            },
        },
        "required": ["action"],
    },
}


# ── Registry ──
from tools.registry import registry

registry.register(
    name="shared_task",
    toolset="shared_tasks",
    schema=SHARED_TASK_SCHEMA,
    handler=lambda args, **kw: shared_task_tool(args, **kw),
    check_fn=check_shared_task_requirements,
    emoji="🗂",
)
