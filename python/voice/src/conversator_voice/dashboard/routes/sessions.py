"""OpenCode session API endpoints for dashboard.

Supports multiple OpenCode instances (Layer 2 orchestration + dynamic builders)
via MultiSourceSSEManager.

This is backed by OpenCode SSE as the source of truth.
"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter()


class RegisterSourceRequest(BaseModel):
    """Request body for registering a new session source."""

    name: str
    base_url: str
    source_type: str = "builder"  # "orchestration" or "builder"


@router.get("")
async def list_sessions_no_slash(request: Request):
    return await list_sessions(request)


@router.get("/")
async def list_sessions(request: Request):
    """List all OpenCode sessions from all sources.

    Sessions are grouped by source:
    - conversator: cvtr-* subagents
    - builder: Builder layer sessions
    - external: Other sessions

    Returns:
        List of sessions with metadata and instance tagging
    """
    sse_manager = getattr(request.app.state, "sse_manager", None)

    if not sse_manager:
        print("[Sessions API] SSE manager not available")
        return {"sessions": [], "total": 0, "error": "SSE manager not available"}

    # Get aggregated sessions from all sources with instance tagging
    sessions = sse_manager.get_aggregated_sessions()

    # Log session counts for debugging
    sources_info = {
        name: len(list(client.sessions.keys())) for name, client in sse_manager.sources.items()
    }
    print(f"[Sessions API] Returning {len(sessions)} sessions. Sources: {sources_info}")

    return {
        "sessions": sessions,
        "total": len(sessions),
        "by_source": {
            "conversator": len([s for s in sessions if s.get("source") == "conversator"]),
            "builder": len([s for s in sessions if s.get("source") == "builder"]),
            "external": len([s for s in sessions if s.get("source") == "external"]),
        },
    }


@router.get("/sources")
async def list_sources(request: Request):
    """List all registered session sources.

    Returns:
        List of registered sources with connection status
    """
    sse_manager = getattr(request.app.state, "sse_manager", None)

    if not sse_manager:
        return {"sources": [], "error": "SSE manager not available"}

    sources = []
    for name, client in sse_manager.sources.items():
        status = client.connection_status
        sources.append(
            {
                "name": name,
                "base_url": client.base_url,
                "type": "orchestration" if name == "layer2" else "builder",
                "status": "polling"
                if status.get("mode") == "polling"
                else "connected"
                if status.get("running")
                else "disconnected",
                "session_count": status.get("session_count", 0),
            }
        )

    return {"sources": sources, "total": len(sources)}


@router.post("/sources/register")
async def register_source(request: Request, body: RegisterSourceRequest):
    """Register a new session source dynamically.

    This is called when a builder starts and needs to be tracked.

    Args:
        body: Source registration details

    Returns:
        Registration status
    """
    sse_manager = getattr(request.app.state, "sse_manager", None)
    ws_manager = getattr(request.app.state, "ws_manager", None)

    if not sse_manager:
        raise HTTPException(status_code=503, detail="SSE manager not available")

    # Add the source
    await sse_manager.add_source(
        name=body.name,
        base_url=body.base_url,
        start=True,
    )

    # Broadcast to connected clients
    if ws_manager:
        await ws_manager.broadcast(
            "source_registered",
            {
                "name": body.name,
                "base_url": body.base_url,
                "type": body.source_type,
                "status": "connected",
            },
        )

    return {"success": True, "name": body.name}


@router.delete("/sources/{name}")
async def deregister_source(request: Request, name: str):
    """Remove a session source.

    This is called when a builder stops.

    Args:
        name: Source name to remove

    Returns:
        Deregistration status
    """
    sse_manager = getattr(request.app.state, "sse_manager", None)
    ws_manager = getattr(request.app.state, "ws_manager", None)

    if not sse_manager:
        raise HTTPException(status_code=503, detail="SSE manager not available")

    # Don't allow removing layer2 orchestration
    if name == "layer2":
        raise HTTPException(status_code=400, detail="Cannot remove Layer 2 orchestration source")

    # Remove the source
    await sse_manager.remove_source(name)

    # Broadcast to connected clients
    if ws_manager:
        await ws_manager.broadcast(
            "source_deregistered",
            {
                "name": name,
            },
        )

    return {"success": True, "name": name}


@router.get("/{session_id}")
async def get_session(request: Request, session_id: str):
    """Get session details from any source.

    Args:
        session_id: Session ID

    Returns:
        Session details with instance info
    """
    sse_manager = getattr(request.app.state, "sse_manager", None)

    if not sse_manager:
        raise HTTPException(status_code=503, detail="SSE manager not available")

    # Find session across all sources
    source_name, session = sse_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    result = session.to_dict()
    result["instance"] = source_name
    return result


@router.get("/{session_id}/messages")
async def get_session_messages(request: Request, session_id: str):
    """Get messages for a session from any source.

    Args:
        session_id: Session ID

    Returns:
        List of messages with content
    """
    sse_manager = getattr(request.app.state, "sse_manager", None)

    if not sse_manager:
        raise HTTPException(status_code=503, detail="SSE manager not available")

    # First check cached messages across all sources
    messages = sse_manager.get_session_messages(session_id)

    # If no cached messages, fetch from API
    if not messages:
        messages = await sse_manager.fetch_session_messages(session_id)

    return {
        "session_id": session_id,
        "messages": [m.to_dict() for m in messages],
        "count": len(messages),
    }


@router.post("/{session_id}/refresh")
async def refresh_session(request: Request, session_id: str):
    """Force refresh session data from OpenCode.

    Args:
        session_id: Session ID

    Returns:
        Updated session with messages
    """
    sse_manager = getattr(request.app.state, "sse_manager", None)

    if not sse_manager:
        raise HTTPException(status_code=503, detail="SSE manager not available")

    # Fetch fresh data from appropriate source
    messages = await sse_manager.fetch_session_messages(session_id)
    source_name, session = sse_manager.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    result = session.to_dict()
    result["instance"] = source_name
    return {
        "session": result,
        "messages": [m.to_dict() for m in messages],
    }
