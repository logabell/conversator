"""System health and status endpoints."""

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health_check(request: Request):
    """Overall system health check.

    Returns:
        Comprehensive health status of all components
    """
    config = request.app.state.config
    state = request.app.state.state_store
    tool_handler = request.app.state.tool_handler
    ws_manager = request.app.state.ws_manager
    opencode_client = request.app.state.opencode_client
    opencode_manager = request.app.state.opencode_manager
    conversator_session = request.app.state.conversator_session

    components = {}
    overall_status = "healthy"

    # Check OpenCode orchestration (Layer 2)
    if opencode_client:
        try:
            healthy = await opencode_client.health_check()
            components["opencode_orchestration"] = {
                "status": "connected" if healthy else "disconnected",
                "port": config.opencode_port if config else 8001,
                "managed": opencode_manager.is_managed if opencode_manager else False,
                "running": opencode_manager.is_running if opencode_manager else False,
            }
            if not healthy:
                overall_status = "degraded"
        except Exception as e:
            components["opencode_orchestration"] = {
                "status": "error",
                "error": str(e)
            }
            overall_status = "degraded"
    else:
        components["opencode_orchestration"] = {"status": "not_configured"}

    # Check Gemini Live connection
    if conversator_session and hasattr(conversator_session, 'conversator'):
        conversator = conversator_session.conversator
        is_connected = getattr(conversator, '_connected', False)
        components["gemini_live"] = {
            "status": "connected" if is_connected else "disconnected",
            "model": "gemini-2.0-flash-exp"
        }
        if not is_connected:
            overall_status = "degraded"
    else:
        components["gemini_live"] = {"status": "not_configured"}

    # Check state store
    if state:
        try:
            # Try a simple query to verify DB is working
            state.get_active_tasks()
            components["state_store"] = {
                "status": "healthy",
                "path": str(state.db_path) if hasattr(state, 'db_path') else "unknown"
            }
        except Exception as e:
            components["state_store"] = {"status": "error", "error": str(e)}
            overall_status = "degraded"
    else:
        components["state_store"] = {"status": "not_configured"}

    # Check builders (Layer 3)
    builder_health = {}
    if tool_handler and hasattr(tool_handler, 'builders'):
        # Check if a builder manager is running (session-level)
        builder_manager_running = (
            hasattr(tool_handler, 'session_state') and
            tool_handler.session_state and
            tool_handler.session_state.builder_manager and
            tool_handler.session_state.builder_manager.is_running
        )

        for name, builder in tool_handler.builders.builders.items():
            try:
                healthy = await builder.health_check()
                if healthy:
                    builder_health[name] = "healthy"
                elif builder_manager_running:
                    # Builder was started but is not responding
                    builder_health[name] = "unreachable"
                    overall_status = "degraded"
                else:
                    # Builder was never started - expected state
                    builder_health[name] = "not_started"
                    # Don't degrade status for not_started - it's expected
            except Exception:
                if builder_manager_running:
                    builder_health[name] = "error"
                    overall_status = "degraded"
                else:
                    builder_health[name] = "not_started"

    components["builders"] = builder_health

    # Check WebSocket connections
    components["websocket"] = {
        "active_connections": ws_manager.connection_count if ws_manager else 0
    }

    # Config info
    if config:
        components["config"] = {
            "status": "loaded",
            "root_project_dir": config.root_project_dir,
            "conversator_port": config.conversator_port
        }
    else:
        components["config"] = {"status": "not_loaded"}

    return {
        "status": overall_status,
        "components": components
    }


@router.get("/config")
async def get_config(request: Request):
    """Get current configuration (non-sensitive).

    Returns:
        Configuration summary
    """
    config = request.app.state.config

    if not config:
        return {"error": "Config not available"}

    return {
        "root_project_dir": config.root_project_dir,
        "conversator_port": config.conversator_port,
        "builders": {
            name: {
                "type": b.type,
                "port": b.port,
                "model": b.model
            }
            for name, b in config.builders.items()
        },
        "models": config.models if hasattr(config, 'models') else {}
    }


@router.get("/stats")
async def get_stats(request: Request):
    """Get system statistics.

    Returns:
        Various system statistics
    """
    state = request.app.state.state_store
    logger = request.app.state.logger

    stats = {}

    if state:
        # Task stats
        all_tasks = state.get_tasks(limit=1000)
        active_tasks = state.get_active_tasks()

        status_counts = {}
        for task in all_tasks:
            status = task.status if hasattr(task, 'status') else "unknown"
            status_counts[status] = status_counts.get(status, 0) + 1

        stats["tasks"] = {
            "total": len(all_tasks),
            "active": len(active_tasks),
            "by_status": status_counts
        }

        # Inbox stats
        all_inbox = state.get_inbox()
        unread_inbox = state.get_inbox(unread_only=True)

        severity_counts = {}
        for item in all_inbox:
            severity = item.severity if hasattr(item, 'severity') else "unknown"
            severity_counts[severity] = severity_counts.get(severity, 0) + 1

        stats["inbox"] = {
            "total": len(all_inbox),
            "unread": len(unread_inbox),
            "by_severity": severity_counts
        }

    if logger:
        # Conversation stats
        entries = logger.get_entries(limit=1000)
        stats["conversation"] = {
            "total_entries": len(entries)
        }

    return stats


@router.get("/ws/status")
async def websocket_status(request: Request):
    """Get WebSocket connection status.

    Returns:
        WebSocket connection information
    """
    ws_manager = request.app.state.ws_manager

    return {
        "active_connections": ws_manager.connection_count if ws_manager else 0,
        "endpoint": "/ws/events"
    }


@router.get("/events/timeline")
async def get_event_timeline(
    request: Request,
    limit: int = 100,
    after_id: int = 0,
    event_types: str | None = None
):
    """Get unified event timeline for dashboard display.

    Combines task events and conversation entries into a single timeline.

    Args:
        limit: Maximum number of events to return
        after_id: Only return events after this ID (for pagination)
        event_types: Comma-separated list of event types to filter

    Returns:
        Timeline of events with unified format
    """
    state = request.app.state.state_store
    logger = request.app.state.logger

    timeline = []

    # Get task events from state store
    if state:
        try:
            events = state.get_events(after_id=after_id)
            for event in events[:limit]:
                timeline.append({
                    "id": f"task-{event.event_id}",
                    "timestamp": event.time.isoformat(),
                    "type": "task_event",
                    "subtype": event.type,
                    "status": "success",  # Task events are always recorded
                    "task_id": event.task_id,
                    "details": {
                        "event_type": event.type,
                        "payload": event.payload
                    }
                })
        except Exception:
            pass

    # Get conversation events from logger
    if logger:
        try:
            entries = logger.get_entries(limit=limit)
            for entry in entries:
                status = "success"
                if entry.role == "tool_call" and entry.tool_result:
                    status = "error" if entry.tool_result.get("error") else "success"

                timeline.append({
                    "id": f"conv-{entry.entry_id}",
                    "timestamp": entry.timestamp.isoformat(),
                    "type": "conversation",
                    "subtype": entry.role,
                    "status": status,
                    "details": {
                        "content": entry.content,
                        "tool_name": entry.tool_name,
                        "duration_ms": entry.duration_ms
                    }
                })
        except Exception:
            pass

    # Sort by timestamp descending
    timeline.sort(key=lambda x: x["timestamp"], reverse=True)

    # Filter by type if specified
    if event_types:
        types = [t.strip() for t in event_types.split(",")]
        timeline = [e for e in timeline if e["type"] in types or e["subtype"] in types]

    return {
        "events": timeline[:limit],
        "count": len(timeline)
    }
