from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal
from copy import deepcopy

import uuid
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langfuse import get_client
from pydantic import BaseModel, Field

import config
from core import graph, graph_runner
from core.storage import sql_database
from utils import helpers

load_dotenv()


class QueryCommand(BaseModel):
    action: Literal["query"]
    query: str = Field(min_length=1)
    user_profile: dict[str, Any] = Field(default_factory=dict)


class ResumeCommand(BaseModel):
    action: Literal["resume"]
    response: str = Field(min_length=1)
    checkpoint_id: str | None = None


class RetryCommand(BaseModel):
    action: Literal["retry"]


Command = QueryCommand | ResumeCommand | RetryCommand

app = FastAPI(title="Backend")
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GRAPH_BUILDER = graph.build()
EMPTY_PLAN = {
    "selected_tools": [],
    "vector_tasks": [],
    "spatial_context": [],
}


@dataclass
class _BackgroundCommand:
    events: list[str] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    done: bool = False


_background_commands: dict[str, _BackgroundCommand] = {}


def encode_sse(event: dict[str, Any]) -> str:
    """Encodes a dictionary as a Server-Sent Event (SSE) string."""
    event_type = str(event.get("type", "message"))
    payload = json.dumps(event, default=str, ensure_ascii=False)

    return f"event: {event_type}\n" f"data: {payload}\n\n"


def _extract_reasoning(message: Any) -> str:
    reasoning_parts: list[str] = []

    blocks = getattr(message, "content_blocks", None)

    if not blocks:
        content = getattr(message, "content", [])

        if isinstance(content, list):
            blocks = content
        else:
            blocks = []

    for block in blocks:
        if not isinstance(block, dict):
            continue

        if block.get("type") == "reasoning":
            reasoning = block.get("reasoning", "")

            if reasoning:
                reasoning_parts.append(reasoning)

    return "".join(reasoning_parts)


def _extract_text(message: Any) -> str:
    """Extract plain text from a LangChain message."""
    content = getattr(message, "content", "")

    if isinstance(content, str):
        return content

    if not isinstance(content, list):
        return str(content) if content else ""

    parts: list[str] = []

    for block in content:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type")

        if block_type == "text":
            text = block.get("text", "")
            if text:
                parts.append(text)

    return "".join(parts)


def _serialize_messages(values: dict[str, Any]) -> list[dict[str, Any]]:
    """Serializes the messages from the graph state into a list of dictionaries."""
    messages_out: list[dict[str, Any]] = []

    for message in values.get("messages", []) or []:
        message_type = getattr(message, "type", None)

        if message_type not in {"human", "ai"}:
            continue

        additional_kwargs = getattr(message, "additional_kwargs", {})

        retrieved_context = additional_kwargs.get("retrieved_context", {})
        plan = additional_kwargs.get("plan", {})

        role = "user" if message_type == "human" else "assistant"
        content = message.content if message_type == "human" else _extract_text(message)
        reasoning = "" if message_type == "human" else _extract_reasoning(message)

        messages_out.append(
            {
                "id": getattr(message, "id", None),
                "role": role,
                "content": content,
                "reasoning": reasoning,
                "isReasoningExpanded": False,
                "additional_kwargs": {
                    "feedback": additional_kwargs.get("feedback", []),
                    "retrieved_context": {
                        "web_results": helpers.format_web_results(
                            retrieved_context.get("web_results", [])
                        ),
                        "vector_docs": helpers.format_vector_docs(
                            retrieved_context.get("vector_docs", [])
                        ),
                        "spatial_analysis": helpers.format_spatial_analysis(
                            retrieved_context.get("spatial_analysis", [])
                        ),
                    },
                    "plan": (
                        helpers.build_display_plan(
                            plan, retrieved_context.get("web_results", [])
                        )
                        if plan
                        else {}
                    ),
                },
            }
        )

    return messages_out


def _checkpoint_id(state: Any) -> str | None:
    """Returns the checkpoint_id of the given state, if available."""
    configurable = (state.config or {}).get("configurable", {})
    return configurable.get("checkpoint_id")


def _is_waiting_for_human(state: Any) -> bool:
    """Returns True if the graph is waiting for human input."""
    return bool(
        state.next
        and ("human_approval" in state.next or "human_clarification" in state.next)
    )


def _is_errored(state: Any) -> bool:
    """Returns True if the graph execution stopped unexpectedly (crashed)."""
    return bool(state.next and not _is_waiting_for_human(state))


def _pending_interaction(state: Any) -> dict[str, Any] | None:
    """Returns the pending interaction if the graph is waiting for human input."""
    if not _is_waiting_for_human(state):
        return None

    values = state.values or {}

    # Check which type of human interruption is queued
    if "human_clarification" in state.next:
        feedback_requested = (values.get("feedback_requested") or "").strip()
        return {
            "kind": "clarification",
            "message": feedback_requested,
            "display_plan": None,
        }

    # Otherwise fallback to approval
    plan = values.get("plan", EMPTY_PLAN)
    retrieved_context = values.get("retrieved_context", {})
    web_results = retrieved_context.get("web_results", [])

    return {
        "kind": "plan_approval",
        "message": None,
        "display_plan": helpers.build_display_plan(plan, web_results),
    }


async def _build_session_payload(
    thread_id: str,
    state: Any,
) -> dict[str, Any]:
    """Builds the payload for the session history endpoint."""
    values = state.values or {}

    return {
        "thread_id": thread_id,
        "exists": bool(values),
        "is_running": thread_id in _background_commands,
        "checkpoint_id": _checkpoint_id(state),
        "messages": _serialize_messages(values),
        "map_layers": values.get("last_map_layers", []) or [],
        "is_errored": _is_errored(state),
        "pending_interaction": _pending_interaction(state),
    }


async def _stream_graph(
    compiled_graph: Any,
    run_config: dict[str, Any],
    input_payload: dict[str, Any] | None,
) -> AsyncIterator[str]:
    """Streams events from the graph to the client."""
    async for event in graph_runner.stream_normalized_events(
        graph=compiled_graph,
        input_payload=input_payload,
        run_config=run_config,
    ):
        yield encode_sse(event)

    state = await compiled_graph.aget_state(run_config)
    values = state.values or {}

    for message in _serialize_messages(values):
        if message["role"] == "user" and (
            message["additional_kwargs"].get("feedback")
            or message["additional_kwargs"].get("plan")
            or message["additional_kwargs"].get("retrieved_context")
        ):
            yield encode_sse({"type": "message_update", "message": message})

    if _is_waiting_for_human(state):
        # Notify the client that human input is required and pause the stream
        yield encode_sse(
            {
                "type": "approval_required",
                "interaction": _pending_interaction(state),
                "checkpoint_id": _checkpoint_id(state),
            }
        )
        yield encode_sse(
            {
                "type": "stream_complete",
                "status": "paused",
                "checkpoint_id": _checkpoint_id(state),
            }
        )
        return

    # Notify the client that the stream has completed
    new_layers = values.get("new_map_layers", []) or []

    if new_layers:
        yield encode_sse(
            {
                "type": "map_layers",
                "layers": new_layers,
            }
        )

        await compiled_graph.aupdate_state(
            run_config,
            {"new_map_layers": []},
        )
        state = await compiled_graph.aget_state(run_config)

    yield encode_sse(
        {
            "type": "stream_complete",
            "status": "completed",
            "checkpoint_id": _checkpoint_id(state),
        }
    )


async def _execute_query(
    compiled_graph: Any,
    run_config: dict[str, Any],
    command: QueryCommand,
) -> AsyncIterator[str]:
    """Executes a new query"""
    state = await compiled_graph.aget_state(run_config)

    if _is_waiting_for_human(state):
        # if the graph is waiting for human input, a new query cannot be executed
        yield encode_sse(
            {
                "type": "approval_required",
                "interaction": _pending_interaction(state),
                "checkpoint_id": _checkpoint_id(state),
            }
        )
        yield encode_sse(
            {
                "type": "stream_error",
                "code": "interaction_pending",
                "message": ("This conversation is waiting for a human response."),
            }
        )
        return

    query = command.query.strip()

    if state.values:
        # if there is an existing state
        message = HumanMessage(content=query, id=uuid.uuid4().hex)
        input_payload: dict[str, Any] = {
            "messages": [message],
            "supervisor_history": [message],
        }

        if command.user_profile and not state.values.get("user_profile"):
            input_payload["user_profile"] = command.user_profile
    else:
        # new conversation thread
        input_payload = graph_runner.get_initial_state(
            query,
            command.user_profile,
        )

    yield encode_sse(
        {
            "type": "stream_started",
            "command": "query",
        }
    )
    yield encode_sse(
        {
            "type": "message_started",
            "message_id": input_payload["messages"][0].id,
        }
    )

    async for event in _stream_graph(
        compiled_graph,
        run_config,
        input_payload,
    ):
        yield event


async def _execute_resume(
    compiled_graph: Any,
    run_config: dict[str, Any],
    command: ResumeCommand,
) -> AsyncIterator[str]:
    """Resumes a paused query after human input."""
    state = await compiled_graph.aget_state(run_config)

    if not _is_waiting_for_human(state):
        # if the graph is not waiting for human input, a resume command cannot be executed
        yield encode_sse(
            {
                "type": "stream_error",
                "code": "not_paused",
                "message": ("This conversation is not waiting for human input."),
            }
        )
        return

    actual_checkpoint_id = _checkpoint_id(state)

    if (
        command.checkpoint_id
        and actual_checkpoint_id
        and command.checkpoint_id != actual_checkpoint_id
    ):
        # if the checkpoint_id provided by the client does not match the current state, notify the client and pause the stream
        yield encode_sse(
            {
                "type": "stream_error",
                "code": "stale_checkpoint",
                "message": (
                    "The conversation changed after it was loaded. "
                    "Reload the thread before responding."
                ),
                "checkpoint_id": actual_checkpoint_id,
            }
        )
        return

    response = command.response.strip()

    state_update = {
        "user_feedback": response,
        "next_node_context": "",
        "sub_agent_message": "",
    }

    await compiled_graph.aupdate_state(
        run_config,
        state_update,
    )

    yield encode_sse(
        {
            "type": "stream_started",
            "command": "resume",
        }
    )

    async for event in _stream_graph(
        compiled_graph,
        run_config,
        None,
    ):
        yield event


async def _execute_retry(
    compiled_graph: Any,
    run_config: dict[str, Any],
) -> AsyncIterator[str]:
    """Retries the graph execution from the latest checkpoint."""
    state = await compiled_graph.aget_state(run_config)

    if _is_waiting_for_human(state):
        yield encode_sse(
            {
                "type": "stream_error",
                "code": "interaction_pending",
                "message": "Cannot retry. The conversation is waiting for human input.",
            }
        )
        return

    yield encode_sse(
        {
            "type": "stream_started",
            "command": "retry",
        }
    )

    # Passing None to resume from the latest checkpoint
    async for event in _stream_graph(
        compiled_graph,
        run_config,
        None,
    ):
        yield event


async def _command_event_stream(
    thread_id: str,
    command: Command,
) -> AsyncIterator[str]:
    """Executes a command and streams events back to the client."""
    run_config = graph_runner.get_run_config(thread_id)

    try:
        async with AsyncSqliteSaver.from_conn_string(config.CHECKPOINT_DB) as memory:
            compiled_graph = GRAPH_BUILDER.compile(
                checkpointer=memory,
                interrupt_before=["human_approval", "human_clarification"],
            )

            if command.action == "query":
                # execute a new query
                async for event in _execute_query(
                    compiled_graph,
                    run_config,
                    command,
                ):
                    yield event
            elif command.action == "resume":
                # resume a paused query
                async for event in _execute_resume(
                    compiled_graph,
                    run_config,
                    command,
                ):
                    yield event
            elif command.action == "retry":
                # retry the graph execution from the latest checkpoint
                async for event in _execute_retry(
                    compiled_graph,
                    run_config,
                ):
                    yield event
    except Exception:
        yield encode_sse(
            {
                "type": "stream_error",
                "code": "execution_failed",
                "message": (
                    "The graph command failed. "
                    "The latest checkpoint remains available."
                ),
            }
        )
    finally:
        get_client().flush()


async def _run_background_command(
    thread_id: str,
    command: Command,
    background_command: _BackgroundCommand,
) -> None:
    """Runs a command independently from any one client's SSE connection."""
    try:
        async for event in _command_event_stream(thread_id, command):
            async with background_command.condition:
                background_command.events.append(event)
                background_command.condition.notify_all()
    except Exception:
        async with background_command.condition:
            background_command.events.append(
                encode_sse(
                    {
                        "type": "stream_error",
                        "code": "execution_failed",
                        "message": (
                            "The graph command failed. "
                            "The latest checkpoint remains available."
                        ),
                    }
                )
            )
            background_command.condition.notify_all()
    finally:
        async with background_command.condition:
            background_command.done = True
            background_command.condition.notify_all()

        if _background_commands.get(thread_id) is background_command:
            del _background_commands[thread_id]


async def _subscribe_to_background_command(
    background_command: _BackgroundCommand,
) -> AsyncIterator[str]:
    """Delivers buffered command events without owning the command task."""
    event_index = 0

    while True:
        async with background_command.condition:
            while (
                event_index >= len(background_command.events)
                and not background_command.done
            ):
                await background_command.condition.wait()

            events = background_command.events[event_index:]
            event_index += len(events)
            is_done = background_command.done

        for event in events:
            yield event

        if is_done and event_index >= len(background_command.events):
            return


@app.get("/api/documents")
async def get_documents() -> dict[str, Any]:
    """Returns documents registered in the index metadata database."""
    return {"documents": sql_database.get_indexed_docs()}


@app.get("/api/history/{thread_id}")
async def get_history(thread_id: str) -> dict[str, Any]:
    """Returns the current state of a conversation thread."""
    run_config = graph_runner.get_run_config(thread_id)

    async with AsyncSqliteSaver.from_conn_string(config.CHECKPOINT_DB) as memory:
        compiled_graph = GRAPH_BUILDER.compile(
            checkpointer=memory,
            interrupt_before=["human_approval", "human_clarification"],
        )
        state = await compiled_graph.aget_state(run_config)

        return await _build_session_payload(
            thread_id,
            state,
        )


@app.post("/api/threads/{thread_id}/commands")
async def execute_command(
    thread_id: str,
    command: Command,
) -> StreamingResponse:
    """Starts or subscribes to a background command and streams its events."""
    background_command = _background_commands.get(thread_id)

    if background_command is None:
        background_command = _BackgroundCommand()
        _background_commands[thread_id] = background_command
        asyncio.create_task(
            _run_background_command(thread_id, command, background_command)
        )

    return StreamingResponse(
        _subscribe_to_background_command(background_command),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/threads/{thread_id}/events")
async def subscribe_to_command(thread_id: str) -> StreamingResponse:
    """Subscribes to a command already running for a thread."""
    background_command = _background_commands.get(thread_id)

    if background_command is None:
        return StreamingResponse(
            iter(()),
            status_code=204,
            media_type="text/event-stream",
        )

    return StreamingResponse(
        _subscribe_to_background_command(background_command),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# uvicorn api:app --reload
