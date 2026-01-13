"""Inbox/notification API endpoints."""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter()


class AcknowledgeRequest(BaseModel):
    """Request body for acknowledging inbox items."""
    inbox_ids: Optional[List[str]] = None


@router.get("/")
async def get_inbox(
    request: Request,
    unread_only: bool = False,
    severity: Optional[str] = None,
    limit: int = 50
):
    """Get inbox items.

    Args:
        unread_only: Only return unread notifications
        severity: Filter by severity (info, success, warning, error, blocking)
        limit: Maximum items to return

    Returns:
        List of inbox items with unread count
    """
    state = request.app.state.state_store

    if not state:
        return {"items": [], "unread_count": 0, "total": 0, "error": "State store not available"}

    items = state.get_inbox(
        unread_only=unread_only,
        severity=severity,
        limit=limit
    )

    unread_count = len(state.get_inbox(unread_only=True))

    return {
        "items": [i.to_dict() if hasattr(i, 'to_dict') else i for i in items],
        "unread_count": unread_count,
        "total": len(items)
    }


@router.get("/unread/count")
async def get_unread_count(request: Request):
    """Get count of unread notifications.

    Returns:
        Unread notification count
    """
    state = request.app.state.state_store

    if not state:
        return {"count": 0, "error": "State store not available"}

    items = state.get_inbox(unread_only=True)
    return {"count": len(items)}


@router.post("/acknowledge")
async def acknowledge(request: Request, body: AcknowledgeRequest):
    """Acknowledge inbox items.

    Args:
        body: Request with optional inbox_ids. If empty, acknowledges all.

    Returns:
        Number of items acknowledged
    """
    state = request.app.state.state_store

    if not state:
        return {"acknowledged": 0, "error": "State store not available"}

    if body.inbox_ids:
        count = 0
        for inbox_id in body.inbox_ids:
            state.acknowledge_inbox(inbox_id)
            count += 1
    else:
        count = state.acknowledge_all_inbox()

    return {"acknowledged": count}


@router.get("/{inbox_id}")
async def get_inbox_item(request: Request, inbox_id: str):
    """Get a specific inbox item.

    Args:
        inbox_id: The inbox item ID

    Returns:
        Inbox item details
    """
    state = request.app.state.state_store

    if not state:
        return {"error": "State store not available"}

    # Get all items and find the one we want
    items = state.get_inbox()
    for item in items:
        item_dict = item.to_dict() if hasattr(item, 'to_dict') else item
        if item_dict.get("inbox_id") == inbox_id:
            return {"item": item_dict}

    return {"error": "Inbox item not found", "inbox_id": inbox_id}
