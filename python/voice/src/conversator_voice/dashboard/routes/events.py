"""Events and conversation log API endpoints."""

from fastapi import APIRouter, Request
from typing import Optional

router = APIRouter()


@router.get("/recent")
async def get_recent_events(
    request: Request,
    after_id: int = 0,
    limit: int = 100
):
    """Get recent events across all tasks.

    Args:
        after_id: Only return events after this ID
        limit: Maximum events to return

    Returns:
        List of recent events
    """
    state = request.app.state.state_store

    if not state:
        return {"events": [], "latest_id": after_id, "error": "State store not available"}

    events = state.get_events(after_id=after_id)

    # Limit results
    events = events[:limit]

    latest_id = events[-1].event_id if events and hasattr(events[-1], 'event_id') else after_id

    return {
        "events": [e.to_dict() if hasattr(e, 'to_dict') else e for e in events],
        "latest_id": latest_id,
        "count": len(events)
    }


@router.get("/conversation")
async def get_conversation_log(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    roles: Optional[str] = None
):
    """Get conversation log entries.

    Args:
        limit: Max entries to return
        offset: Skip this many entries
        roles: Comma-separated roles to filter (user,assistant,tool_call)

    Returns:
        List of conversation entries
    """
    logger = request.app.state.logger

    if not logger:
        return {"entries": [], "count": 0, "error": "Logger not available"}

    role_list = roles.split(",") if roles else None
    entries = logger.get_entries(
        limit=limit,
        offset=offset,
        roles=role_list
    )

    return {
        "entries": [e.to_dict() for e in entries],
        "count": len(entries)
    }


@router.get("/conversation/transcript")
async def get_transcript(request: Request, count: int = 20):
    """Get recent conversation as plain text transcript.

    Args:
        count: Number of recent entries to include

    Returns:
        Plain text transcript
    """
    logger = request.app.state.logger

    if not logger:
        return {"transcript": "", "error": "Logger not available"}

    return {"transcript": logger.get_recent_transcript(count)}


@router.get("/conversation/stats")
async def get_conversation_stats(request: Request):
    """Get conversation statistics.

    Returns:
        Statistics about the conversation log
    """
    logger = request.app.state.logger

    if not logger:
        return {"error": "Logger not available"}

    all_entries = logger.get_entries(limit=1000)

    # Count by role
    role_counts = {}
    for entry in all_entries:
        role = entry.role
        role_counts[role] = role_counts.get(role, 0) + 1

    # Count tool calls
    tool_calls = [e for e in all_entries if e.role == "tool_call"]
    tool_counts = {}
    for entry in tool_calls:
        tool = entry.tool_name or "unknown"
        tool_counts[tool] = tool_counts.get(tool, 0) + 1

    return {
        "total_entries": len(all_entries),
        "by_role": role_counts,
        "tool_calls": {
            "total": len(tool_calls),
            "by_tool": tool_counts
        }
    }
