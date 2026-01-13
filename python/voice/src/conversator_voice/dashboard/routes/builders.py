"""Builder status API endpoints."""

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/")
async def list_builders(request: Request):
    """List all configured builders with status.

    Returns:
        List of builders with health status
    """
    config = request.app.state.config
    tool_handler = request.app.state.tool_handler

    if not config:
        return {"builders": [], "error": "Config not available"}

    builders_info = []

    for name, builder_config in config.builders.items():
        info = {
            "name": name,
            "type": builder_config.type,
            "port": builder_config.port,
            "model": builder_config.model,
            "status": "unknown",
            "active_tasks": 0
        }

        # Check health if tool_handler is available
        if tool_handler and hasattr(tool_handler, 'builders'):
            builder = tool_handler.builders.get(name)
            if builder:
                try:
                    healthy = await builder.health_check()
                    info["status"] = "healthy" if healthy else "unreachable"
                    if hasattr(builder, 'active_sessions'):
                        info["active_tasks"] = len(builder.active_sessions)
                except Exception:
                    info["status"] = "error"

        builders_info.append(info)

    return {"builders": builders_info}


@router.get("/health/all")
async def health_check_all(request: Request):
    """Check health of all builders.

    Returns:
        Health status for each builder
    """
    tool_handler = request.app.state.tool_handler

    if not tool_handler or not hasattr(tool_handler, 'builders'):
        return {"health": {}, "error": "Builders not available"}

    results = {}

    for name, builder in tool_handler.builders.builders.items():
        try:
            healthy = await builder.health_check()
            results[name] = "healthy" if healthy else "unreachable"
        except Exception as e:
            results[name] = f"error: {str(e)}"

    return {"health": results}


@router.get("/{name}")
async def get_builder(request: Request, name: str):
    """Get detailed status for a specific builder.

    Args:
        name: Builder name

    Returns:
        Detailed builder status
    """
    config = request.app.state.config
    tool_handler = request.app.state.tool_handler

    if not config:
        return {"error": "Config not available"}

    if name not in config.builders:
        return {"error": f"Builder '{name}' not found"}

    builder_config = config.builders[name]

    info = {
        "name": name,
        "type": builder_config.type,
        "port": builder_config.port,
        "model": builder_config.model,
        "base_url": f"http://localhost:{builder_config.port}",
        "status": "unknown",
        "active_sessions": [],
        "plan_sessions": []
    }

    if tool_handler and hasattr(tool_handler, 'builders'):
        builder = tool_handler.builders.get(name)
        if builder:
            try:
                healthy = await builder.health_check()
                info["status"] = "healthy" if healthy else "unreachable"
                if hasattr(builder, 'active_sessions'):
                    info["active_sessions"] = list(builder.active_sessions.keys())
                if hasattr(builder, 'plan_sessions'):
                    info["plan_sessions"] = list(builder.plan_sessions.keys())
            except Exception as e:
                info["status"] = f"error: {str(e)}"

    return info
