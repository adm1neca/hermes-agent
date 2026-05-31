"""Mission Control cost reporter for Hermes Agent.

Reports token usage to Mission Control database for cost tracking.
Works for all providers (cloud APIs and local models like Ollama).

Environment variables:
    MISSION_CONTROL_SESSION_ID: Session ID to report costs under
    MISSION_CONTROL_DB: Override database path (default: /workspace/mission_control.db)
"""
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Thread-local storage so each thread gets its own SQLite connection
_local = threading.local()


def _get_db_path() -> Optional[Path]:
    """Get Mission Control database path."""
    # Priority 1: Environment override
    env_path = os.environ.get("MISSION_CONTROL_DB")
    if env_path:
        return Path(env_path)
    
    # Priority 2: Workspace default
    workspace_path = Path("/workspace/mission_control.db")
    if workspace_path.exists():
        return workspace_path
    
    # Priority 3: User's hermes directory
    user_path = Path.home() / ".hermes" / "mission_control.db"
    if user_path.exists():
        return user_path
    
    # No MC database found - user hasn't spawned any agents
    return None


def _get_mc_session_id() -> Optional[str]:
    """Get Mission Control session ID from environment."""
    return os.environ.get("MISSION_CONTROL_SESSION_ID")


def report_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    reasoning_tokens: int = 0,
    estimated_cost_usd: Optional[float] = None,
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
) -> bool:
    """Report token usage to Mission Control.
    
    This function is called after each LLM response to track costs.
    It requires MISSION_CONTROL_SESSION_ID to be set (injected by gateway).
    
    Args:
        model: Model identifier (e.g., "glm-5:cloud", "ollama:llama3")
        input_tokens: Prompt tokens (excluding cache)
        output_tokens: Completion tokens
        cache_read_tokens: Tokens read from cache (Anthropic-style)
        cache_write_tokens: Tokens written to cache (Anthropic-style)
        reasoning_tokens: Reasoning tokens (OpenAI o1-style)
        estimated_cost_usd: Pre-computed cost if available (for subscription models)
        provider: Provider name (e.g., "anthropic", "openai", "ollama")
        base_url: API base URL (for local models)
    
    Returns:
        True if successfully reported, False otherwise
    """
    # Check for MC session ID
    session_id = _get_mc_session_id()
    if not session_id:
        # No MC session - this is fine, just skip reporting
        logger.debug("No MISSION_CONTROL_SESSION_ID set, skipping cost report")
        return False

    # Check for MC database
    db_path = _get_db_path()
    if not db_path:
        logger.debug("Mission Control database not found, skipping cost report")
        return False

    # Lazy-load per-thread connection (SQLite connections cannot cross threads)
    try:
        if not hasattr(_local, "db") or _local.db is None:
            # Import here to avoid import errors when MC isn't installed
            sys_path_backup = os.environ.get("PYTHONPATH", "")

            # Add mission_control to path if needed
            mc_path = db_path.parent
            if str(mc_path) not in sys_path_backup:
                os.environ["PYTHONPATH"] = f"{mc_path}:{sys_path_backup}"

            from mission_control.database import Database
            from mission_control.costs import CostTracker

            _local.db = Database(db_path)
            _local.cost_tracker = CostTracker(_local.db)
    except ImportError as e:
        logger.debug(f"Mission Control not available: {e}")
        return False
    except Exception as e:
        logger.warning(f"Failed to initialize Mission Control: {e}")
        return False
    
    # Only count non-cache input/output toward cost
    total_input = input_tokens + cache_read_tokens + cache_write_tokens
    total_output = output_tokens + reasoning_tokens
    
    # Strip provider prefix for cleaner model names
    model_name = model
    if ":" in model and not model.startswith(("http", "ollama")):
        # But keep ollama: prefix so we know it's local
        parts = model.split(":", 1)
        if len(parts) == 2 and parts[0] not in ("ollama", "lmstudio", "localhost"):
            model_name = parts[1]
    
    try:
        cost_id = _local.cost_tracker.record_cost(
            agent_id=session_id,
            model=model_name,
            input_tokens=total_input,
            output_tokens=total_output,
            is_estimated=(estimated_cost_usd is None)
        )
        logger.info(
            f"Mission Control: {session_id} | {model_name} | "
            f"{total_input} in / {total_output} out"
        )
        return True
    except Exception as e:
        logger.warning(f"Failed to report to Mission Control: {e}")
        return False


def clear_cache():
    """Clear cached database connection for the current thread (for testing)."""
    _local.db = None
    _local.cost_tracker = None