import json

import httpx
import pytest

from conversator_voice.builder_client import OpenCodeBuilder


class RequestRecorder:
    def __init__(self):
        self.requests: list[httpx.Request] = []

    def record(self, request: httpx.Request) -> None:
        self.requests.append(request)


@pytest.mark.asyncio
async def test_dispatch_task_plan_mode_sends_plan_agent(tmp_path):
    recorder = RequestRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.record(request)

        if request.url.path == "/session":
            return httpx.Response(200, json={"id": "ses_123"})

        if request.url.path == "/session/ses_123/prompt_async":
            body = json.loads(request.content.decode() or "{}")
            assert body["agent"] == "plan"
            assert body["parts"][0]["type"] == "text"
            return httpx.Response(204)

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    builder = OpenCodeBuilder(name="opencode", base_url="http://localhost:4096", model="test")
    await builder.client.aclose()
    builder.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10)

    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("# Test Prompt\n")

    result = await builder.dispatch_task_plan_mode(task_id="task-1", prompt_path=str(prompt_path))
    assert result["dispatched"] is True
    assert builder.plan_sessions["task-1"] == "ses_123"

    await builder.close()


@pytest.mark.asyncio
async def test_approve_and_build_sends_build_agent(tmp_path):
    recorder = RequestRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.record(request)

        if request.url.path == "/session/ses_123/prompt_async":
            body = json.loads(request.content.decode() or "{}")
            assert body["agent"] == "build"
            assert body["parts"][0]["type"] == "text"
            assert body["parts"][0]["text"].startswith("implement the plan")
            return httpx.Response(204)

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    builder = OpenCodeBuilder(name="opencode", base_url="http://localhost:4096", model="test")
    await builder.client.aclose()
    builder.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10)

    builder.plan_sessions["task-1"] = "ses_123"

    result = await builder.approve_and_build("task-1")
    assert result.get("building") is True
    assert builder.active_sessions["task-1"] == "ses_123"
    assert "task-1" not in builder.plan_sessions

    await builder.close()
