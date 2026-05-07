"""T125: Dashboard realtime — WebSocket channel for reactive widgets.

Backend WS channel ``dashboard:{tenant}:{role}`` emitting invalidation events.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class DashboardChannel:
    """Manages WebSocket connections for dashboard widget invalidation."""

    def __init__(self):
        self._connections: dict[str, set] = {}

    def _channel_key(self, tenant_id: str, role: str) -> str:
        return f"dashboard:{tenant_id}:{role}"

    async def subscribe(self, tenant_id: str, role: str, websocket: Any) -> None:
        """Subscribe a WebSocket to a dashboard channel."""
        key = self._channel_key(tenant_id, role)
        if key not in self._connections:
            self._connections[key] = set()
        self._connections[key].add(websocket)
        logger.debug("Subscribed to channel: %s", key)

    async def unsubscribe(self, tenant_id: str, role: str, websocket: Any) -> None:
        """Unsubscribe a WebSocket from a dashboard channel."""
        key = self._channel_key(tenant_id, role)
        if key in self._connections:
            self._connections[key].discard(websocket)

    async def emit_invalidation(self, tenant_id: str, role: str, widget_keys: list[str]) -> None:
        """Emit an invalidation event to all subscribers of a dashboard channel.

        Args:
            tenant_id: Tenant identifier.
            role: Dashboard role.
            widget_keys: List of widget keys that need refetch.
        """
        key = self._channel_key(tenant_id, role)
        connections = self._connections.get(key, set())

        if not connections:
            return

        message = json.dumps({"widget_keys": widget_keys})
        dead = set()

        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)

        # Clean up dead connections
        for ws in dead:
            connections.discard(ws)

        logger.debug("Emitted invalidation to %d subscribers: %s", len(connections) - len(dead), widget_keys)


# Singleton
dashboard_channel = DashboardChannel()


async def emit_dashboard_invalidation(tenant_id: str, event: str, widget_keys: list[str]) -> None:
    """Emit invalidation for all roles that care about this event.

    Called by the cache invalidation registry when domain events fire.
    """
    # For now, emit to all roles (can be refined per-event)
    for role in ["admin", "accountant", "manager", "executive"]:
        await dashboard_channel.emit_invalidation(tenant_id, role, widget_keys)
