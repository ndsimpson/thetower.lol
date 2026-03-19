"""Logging context utilities for per-interaction guild/user injection.

Uses Python contextvars so the guild ID and user ID are automatically
available throughout the entire async call chain for a Discord interaction,
without needing to pass them explicitly to every logger call.
"""

import logging
from contextvars import ContextVar
from typing import Optional

# Set once per interaction in bot.py's tree.interaction_check; automatically
# propagates to all coroutines called within that interaction's async task.
current_guild_id: ContextVar[Optional[int]] = ContextVar("guild_id", default=None)
current_user_id: ContextVar[Optional[int]] = ContextVar("user_id", default=None)


class GuildContextFilter(logging.Filter):
    """Adds interaction_ctx_str to every log record from the current interaction context.

    Attach this filter to the root logger's handlers so all loggers
    (cogs, utils, etc.) automatically include guild/user context when set.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        guild_id = current_guild_id.get()
        user_id = current_user_id.get()
        parts = []
        if guild_id is not None:
            parts.append(str(guild_id))
        if user_id is not None:
            parts.append(str(user_id))
        record.guild_id_str = f"[{'/'.join(parts)}] " if parts else ""
        return True
