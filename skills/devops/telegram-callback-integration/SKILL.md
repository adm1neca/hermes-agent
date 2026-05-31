---
name: telegram-callback-integration
description: How to add custom Telegram callback handlers to Hermes without running a separate bot. Extends the existing TelegramAdapter to handle custom callback_data patterns.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [Telegram, callback, integration, platform, adapter]
    related_skills: []
---

# Telegram Callback Integration

When integrating a third-party service that uses Telegram inline button callbacks, do NOT run a separate polling bot. Instead, extend Hermes's existing Telegram adapter.

## The Problem

Running two bots with the same Telegram token causes a "409 Conflict" error:
```
telegram.error.Conflict: Conflict: terminated by other getUpdates request; 
make sure that only one bot instance is running
```

Telegram only allows ONE polling connection per bot token. If your service needs to handle button callbacks, those handlers must be added to Hermes's existing bot.

## The Solution

Extend `_handle_callback_query` in `/workspace/hermes-agent/gateway/platforms/telegram.py`.

### Step 1: Identify Your Callback Pattern

Your service sends buttons with `callback_data` like:
```
accept:PAPER_ID
reject:PAPER_ID
rate:PAPER_ID:5
```

Choose a prefix pattern that won't conflict with existing handlers.

### Step 2: Add a Handler Method

Add a new async method to the `TelegramAdapter` class:

```python
async def _handle_my_service_callback(self, query, data: str) -> None:
    """Handle MyService button callbacks."""
    try:
        # Parse callback data: "action:id" or "action:id:extra"
        parts = data.split(":")
        action = parts[0]
        item_id = parts[1] if len(parts) > 1 else None
        
        if not item_id:
            await query.answer("Invalid callback")
            return
        
        # Do your processing here
        # - Import your service's database/models
        # - Record feedback, update state, etc.
        
        # Send confirmation
        await query.answer(f"✓ {action} recorded")
        
        # Optionally edit message or send reply
        # await query.message.reply_text(...)
        
    except Exception as e:
        logger.error(f"Error in my_service callback: {e}")
        await query.answer("Error processing callback")
```

### Step 3: Route in `_handle_callback_query`

Modify the existing routing:

```python
async def _handle_callback_query(
    self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"
) -> None:
    """Handle inline keyboard button clicks."""
    query = update.callback_query
    if not query or not query.data:
        return
    data = query.data
    
    # Existing handlers (update prompts, etc.)
    if data.startswith("update_prompt:"):
        await self._handle_update_prompt_callback(query, data)
        return
    
    # NEW: Add your callback routing
    if data.startswith(("accept:", "reject:", "rate:")):
        await self._handle_my_service_callback(query, data)
        return
```

### Step 4: Database Access Pattern

Your callback handler needs to access the service's data:

```python
async def _handle_paper_feedback_callback(self, query, data: str) -> None:
    try:
        parts = data.split(":")
        action = parts[0]
        paper_id = parts[1]
        
        # Find the database - check common locations
        from pathlib import Path
        db_paths = [
            Path("/workspace/paper-digest/paper-digest/data/papers.db"),
            Path.home() / ".paper-digest" / "data" / "papers.db",
        ]
        
        # Also check environment variable
        db_env = os.environ.get("PAPER_DIGEST_DB")
        if db_env:
            db_paths.insert(0, Path(db_env))
        
        db = None
        for db_path in db_paths:
            if db_path.exists():
                # Import service module
                sys.path.insert(0, str(db_path.parent.parent))
                from paper_digest.storage.db import PaperDatabase
                db = PaperDatabase(str(db_path))
                break
        
        if not db:
            await query.answer("Database not connected")
            return
        
        # Process feedback...
        paper = db.get_paper(paper_id)
        db.record_feedback(paper_id, category, action)
        db.close()
        
        await query.answer("✓ Saved")
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        await query.answer("Error")
```

## What NOT to Do

❌ Create a separate `bot.py` entry point with `app.run_polling()`
❌ Define a new `FeedbackBot` class with its own ApplicationBuilder
❌ Add another `CallbackQueryHandler` in a separate file

These will conflict with Hermes's existing Telegram connection.

## Existing Callback Patterns

Current patterns in `telegram.py`:
- `update_prompt:y` / `update_prompt:n` — Hermes update confirmations

Add your pattern with a distinct prefix.

## Testing

1. Start Hermes with Telegram enabled
2. Have your service send a message with inline buttons
3. Click a button — your handler should receive the callback
4. Check logs for: `Recorded {action} feedback for {item}`

## Debugging

Add logging at the start of your handler:

```python
logger.info(f"Received callback: {data} from user {query.from_user.id}")
```

If callbacks aren't received:
1. Verify Hermes Telegram adapter is running
2. Check `pyproject.toml` — don't define a separate `CommandHandler` entry
3. Ensure your callback prefix doesn't conflict
4. Check Telegram logs for errors