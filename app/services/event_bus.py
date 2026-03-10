"""In-process async event bus for domain events.

All gamification, analytics, and side-effect logic subscribes here
instead of being coupled into business logic.

Usage
-----
    from app.services.event_bus import event_bus

    # Subscribe (at module / startup time)
    @event_bus.on(GameEventType.HABIT_LOGGED)
    async def handle_habit(event: GameEvent) -> None: ...

    # Emit (from business logic)
    await event_bus.emit(GameEvent(...))
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Awaitable, Callable

from loguru import logger

from app.config import settings
from app.services.gamification.schemas import GameEvent, GameEventType

Listener = Callable[[GameEvent], Awaitable[None]]


class EventBus:
    """Lightweight async pub/sub bus."""

    def __init__(self) -> None:
        self._listeners: dict[GameEventType, list[Listener]] = defaultdict(list)
        self._global_listeners: list[Listener] = []

    # ── registration ──────────────────────────────────────────
    def on(self, event_type: GameEventType) -> Callable[[Listener], Listener]:
        """Decorator to register a listener for a specific event type."""
        def decorator(fn: Listener) -> Listener:
            self._listeners[event_type].append(fn)
            return fn
        return decorator

    def on_all(self, fn: Listener) -> Listener:
        """Register a listener that receives ALL events (analytics sink)."""
        self._global_listeners.append(fn)
        return fn

    def subscribe(self, event_type: GameEventType, fn: Listener) -> None:
        """Imperative subscription (for dynamic wiring at startup)."""
        self._listeners[event_type].append(fn)

    # ── emission ──────────────────────────────────────────────
    async def emit(self, event: GameEvent) -> None:
        """Emit an event to all matching listeners.

        Listener exceptions are logged but never propagate — the emitter
        must not be disrupted by subscriber failures.
        """
        if not settings.is_feature_enabled("F002_EVENT_BUS"):
            return

        targets = list(self._listeners.get(event.event, [])) + list(self._global_listeners)
        if not targets:
            return

        results = await asyncio.gather(
            *(self._safe_call(fn, event) for fn in targets),
            return_exceptions=True,
        )
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.exception(
                    "Event listener {} failed for {}: {}",
                    targets[i].__qualname__,
                    event.event.value,
                    result,
                )

    @staticmethod
    async def _safe_call(fn: Listener, event: GameEvent) -> None:
        await fn(event)


# Module-level singleton — import this everywhere.
event_bus = EventBus()
