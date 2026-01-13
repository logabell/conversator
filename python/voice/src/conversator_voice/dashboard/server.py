"""Dashboard FastAPI server integrated with Conversator voice app."""

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse

from .websocket import ConnectionManager
from .conversation_logger import ConversationLogger

if TYPE_CHECKING:
    from ..state import StateStore
    from ..config import ConversatorConfig


def create_dashboard_app(
    state: "StateStore | None" = None,
    conversation_logger: "ConversationLogger | None" = None,
    config: "ConversatorConfig | None" = None,
    tool_handler: "any" = None,
    opencode_client: "any" = None,
    opencode_manager: "any" = None,
    conversator_session: "any" = None,
) -> FastAPI:
    """Create FastAPI app with injected dependencies.

    Args:
        state: StateStore instance for task/inbox queries
        conversation_logger: ConversationLogger for transcript access
        config: ConversatorConfig for system info
        tool_handler: ToolHandler for builder access
        opencode_client: OpenCodeClient for health checks
        opencode_manager: OpenCodeManager for process status
        conversator_session: ConversatorSession for Gemini status

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="Conversator Dashboard",
        description="Real-time monitoring for Conversator voice assistant",
        version="0.1.0"
    )

    # CORS for development (Vite dev server)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",  # Vite dev server
            "http://localhost:8080",  # Production
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8080",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store dependencies in app state
    app.state.state_store = state
    app.state.logger = conversation_logger or ConversationLogger()
    app.state.config = config
    app.state.tool_handler = tool_handler
    app.state.ws_manager = ConnectionManager()
    app.state.opencode_client = opencode_client
    app.state.opencode_manager = opencode_manager
    app.state.conversator_session = conversator_session

    # Wire up conversation logger to broadcast to WebSocket
    async def broadcast_entry(entry):
        await app.state.ws_manager.broadcast_conversation_entry(entry.to_dict())

    app.state.logger.add_listener(broadcast_entry)

    # Wire up state store to broadcast task events
    if state:
        import asyncio

        def broadcast_task_event(event):
            """Broadcast task events via WebSocket."""
            try:
                asyncio.create_task(
                    app.state.ws_manager.broadcast("task_event", {
                        "event_id": event.event_id,
                        "type": event.type,
                        "task_id": event.task_id,
                        "timestamp": event.time.isoformat(),
                        "payload": event.payload
                    })
                )
            except Exception:
                pass

        state.add_event_listener(broadcast_task_event)

    # Import and include routers
    from .routes import tasks, inbox, builders, events, system

    app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
    app.include_router(inbox.router, prefix="/api/inbox", tags=["inbox"])
    app.include_router(builders.router, prefix="/api/builders", tags=["builders"])
    app.include_router(events.router, prefix="/api/events", tags=["events"])
    app.include_router(system.router, prefix="/api/system", tags=["system"])

    # WebSocket endpoint for real-time updates
    @app.websocket("/ws/events")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time event streaming."""
        await app.state.ws_manager.connect(websocket)
        try:
            while True:
                # Keep connection alive, receive any client messages
                data = await websocket.receive_text()
                # Could handle client messages here (e.g., subscriptions)
        except WebSocketDisconnect:
            app.state.ws_manager.disconnect(websocket)

    # Health check endpoint at root for quick verification
    @app.get("/health")
    async def health():
        """Quick health check."""
        return {"status": "ok", "service": "conversator-dashboard"}

    # Root endpoint - serve dashboard or API info
    @app.get("/", response_class=HTMLResponse)
    async def root():
        """Dashboard root - serve React app or API info."""
        static_path = Path(__file__).parent / "static" / "index.html"
        if static_path.exists():
            return static_path.read_text()

        # Development fallback - show API info
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Conversator Dashboard</title>
            <style>
                body { font-family: system-ui; background: #1a1a2e; color: #eee; padding: 2rem; }
                h1 { color: #7c3aed; }
                a { color: #60a5fa; }
                pre { background: #0f0f1a; padding: 1rem; border-radius: 0.5rem; }
            </style>
        </head>
        <body>
            <h1>Conversator Dashboard API</h1>
            <p>The dashboard frontend is not yet built. API endpoints are available:</p>
            <ul>
                <li><a href="/api/tasks">/api/tasks</a> - Task list</li>
                <li><a href="/api/inbox">/api/inbox</a> - Notifications</li>
                <li><a href="/api/builders">/api/builders</a> - Builder status</li>
                <li><a href="/api/events/conversation">/api/events/conversation</a> - Conversation log</li>
                <li><a href="/api/system/health">/api/system/health</a> - System health</li>
                <li><a href="/docs">/docs</a> - OpenAPI documentation</li>
            </ul>
            <p>WebSocket: <code>ws://localhost:8080/ws/events</code></p>
            <h2>To build the frontend:</h2>
            <pre>cd dashboard-ui && npm install && npm run build</pre>
        </body>
        </html>
        """

    # Serve static files in production
    # Mount assets at /assets to avoid intercepting WebSocket and API routes
    static_dir = Path(__file__).parent / "static"
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # Catch-all route for SPA client-side routing
    # This must be defined last and only serves index.html for unmatched paths
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """Serve SPA for client-side routing."""
        index_path = static_dir / "index.html"
        if index_path.exists():
            return FileResponse(index_path, media_type="text/html")
        # Fallback if no static build
        return HTMLResponse(
            content="<h1>Dashboard not built</h1><p>Run: cd dashboard-ui && npm run build</p>",
            status_code=404
        )

    return app
