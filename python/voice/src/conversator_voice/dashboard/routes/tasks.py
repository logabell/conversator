"""Task-related API endpoints."""

from fastapi import APIRouter, Request
from typing import Optional

router = APIRouter()


@router.get("/")
async def list_tasks(
    request: Request,
    status: Optional[str] = None,
    limit: int = 50
):
    """List all tasks with optional status filter.

    Args:
        status: Filter by task status
        limit: Maximum number of tasks to return

    Returns:
        List of tasks with metadata
    """
    state = request.app.state.state_store

    if not state:
        return {"tasks": [], "total": 0, "error": "State store not available"}

    if status:
        tasks = state.get_tasks(status=status, limit=limit)
    else:
        tasks = state.get_tasks(limit=limit)

    return {
        "tasks": [t.to_dict() if hasattr(t, 'to_dict') else t for t in tasks],
        "total": len(tasks)
    }


@router.get("/active")
async def get_active_tasks(request: Request):
    """Get all active (non-terminal) tasks.

    Returns:
        List of active tasks with count
    """
    state = request.app.state.state_store

    if not state:
        return {"tasks": [], "count": 0, "error": "State store not available"}

    tasks = state.get_active_tasks()

    return {
        "tasks": [t.to_dict() if hasattr(t, 'to_dict') else t for t in tasks],
        "count": len(tasks)
    }


@router.get("/{task_id}")
async def get_task(request: Request, task_id: str):
    """Get a specific task by ID.

    Args:
        task_id: The task ID to retrieve

    Returns:
        Task details with associated events
    """
    state = request.app.state.state_store

    if not state:
        return {"error": "State store not available"}

    task = state.get_task(task_id)

    if not task:
        return {"error": "Task not found", "task_id": task_id}

    # Also get events for this task
    events = state.get_events(task_id=task_id)

    return {
        "task": task.to_dict() if hasattr(task, 'to_dict') else task,
        "events": [e.to_dict() if hasattr(e, 'to_dict') else e for e in events]
    }


@router.get("/{task_id}/events")
async def get_task_events(
    request: Request,
    task_id: str,
    after_id: int = 0,
    limit: int = 100
):
    """Get events for a task, optionally after a specific event ID.

    Args:
        task_id: The task ID
        after_id: Only return events after this ID
        limit: Maximum events to return

    Returns:
        List of events for the task
    """
    state = request.app.state.state_store

    if not state:
        return {"events": [], "error": "State store not available"}

    events = state.get_events(task_id=task_id, after_id=after_id)

    # Apply limit
    events = events[:limit]

    return {
        "events": [e.to_dict() if hasattr(e, 'to_dict') else e for e in events],
        "count": len(events)
    }
