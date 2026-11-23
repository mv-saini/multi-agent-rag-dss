from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage
from langfuse import get_client
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from starlette.concurrency import run_in_threadpool

import config
from core import graph, graph_runner
from core.storage import evidence_store
from services import evidence
from services.sse import EventStream, encode_sse
from utils import helpers

EMPTY_PLAN = {"selected_tools": [], "vector_tasks": [], "spatial_context": []}
GRAPH_BUILDER = graph.build()
_logger = logging.getLogger(__name__)


@dataclass
class ActiveCommand:
    owner_id: str
    stream: EventStream


active_commands: dict[str, ActiveCommand] = {}


def extract_reasoning(message: Any) -> str:
    blocks = getattr(message, "content_blocks", None) or getattr(message, "content", [])
    if not isinstance(blocks, list):
        return ""
    return "".join(
        block.get("reasoning", "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "reasoning"
    )


def extract_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content) if content else ""
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def serialize_messages(values: dict[str, Any]) -> list[dict[str, Any]]:
    messages = []
    for message in values.get("messages", []) or []:
        message_type = getattr(message, "type", None)
        if message_type not in {"human", "ai"}:
            continue
        metadata = getattr(message, "additional_kwargs", {})
        plan = metadata.get("plan", {})
        extras = {
            "feedback": metadata.get("feedback", []),
            "evidence_bundle_id": metadata.get("evidence_bundle_id"),
            "plan": helpers.build_display_plan(plan, []) if plan else None,
        }
        messages.append({
            "id": getattr(message, "id", None),
            "role": "user" if message_type == "human" else "assistant",
            "content": message.content if message_type == "human" else extract_text(message),
            "reasoning": "" if message_type == "human" else extract_reasoning(message),
            "isReasoningExpanded": False,
            "additional_kwargs": extras,
        })
    return messages


def checkpoint_id(state: Any) -> str | None:
    return (state.config or {}).get("configurable", {}).get("checkpoint_id")


def is_waiting_for_human(state: Any) -> bool:
    return bool(
        state.next
        and ("human_approval" in state.next or "human_clarification" in state.next)
    )


def scenario_editor_pending(state: Any) -> bool:
    """A retained draft is not itself a request to open the scenario editor."""
    values = state.values or {}
    return bool(
        state.next
        and "human_clarification" in state.next
        and values.get("resume_node") == "spatial_agent_node"
        and values.get("scenario_editor_requested", False)
        and values.get("scenario_request")
    )


def pending_interaction(state: Any) -> dict[str, Any] | None:
    if not is_waiting_for_human(state):
        return None
    values = state.values or {}
    if "human_clarification" in state.next:
        return {
            "kind": "clarification",
            "message": (values.get("feedback_requested") or "").strip(),
            "display_plan": None,
            "scenario_request": (
                {**values["scenario_request"], **({"draft": values["scenario_selection"]["scenario"]} if values.get("scenario_selection") else {})}
                if scenario_editor_pending(state)
                else None
            ),
        }
    retrieved_context = evidence_store.load(values.get("evidence_bundle_id"))["context"]
    return {
        "kind": "plan_approval",
        "message": (values.get("next_node_context") or "").strip(),
        "display_plan": helpers.build_display_plan(
            values.get("plan", EMPTY_PLAN), retrieved_context.get("web_results", [])
        ),
    }


def _approval_event(state: Any) -> str:
    return encode_sse(
        {
            "type": "approval_required",
            "interaction": pending_interaction(state),
            "checkpoint_id": checkpoint_id(state),
        }
    )


async def session_payload(thread_id: str, state: Any) -> dict[str, Any]:
    values = state.values or {}
    return {
        "thread_id": thread_id,
        "exists": bool(values),
        "is_running": thread_id in active_commands,
        "checkpoint_id": checkpoint_id(state),
        "messages": await run_in_threadpool(serialize_messages, values),
        "evidence_bundle_ids": evidence.bundle_ids(values),
        "is_errored": bool(state.next and not is_waiting_for_human(state)),
        "pending_interaction": await run_in_threadpool(pending_interaction, state),
    }


async def stream_graph(
    compiled_graph: Any,
    run_config: dict[str, Any],
    input_payload: dict[str, Any] | None,
) -> AsyncIterator[str]:
    async for event in graph_runner.stream_normalized_events(
        compiled_graph, input_payload, run_config
    ):
        if event.get("type") in {"tool_start", "custom_event"}:
            yield await run_in_threadpool(encode_sse, event)
        else:
            yield encode_sse(event)
    state = await compiled_graph.aget_state(run_config)
    values = state.values or {}
    messages = await run_in_threadpool(serialize_messages, values)
    for message in messages:
        if message["role"] == "user" and any(message["additional_kwargs"].values()):
            yield await run_in_threadpool(
                encode_sse, {"type": "message_update", "message": message}
            )
    if is_waiting_for_human(state):
        yield await run_in_threadpool(_approval_event, state)
        yield encode_sse(
            {
                "type": "stream_complete",
                "status": "paused",
                "checkpoint_id": checkpoint_id(state),
            }
        )
        return
    assistant_messages = [
        message for message in messages if message["role"] == "assistant"
    ]
    if assistant_messages:
        yield await run_in_threadpool(
            encode_sse, {"type": "message_update", "message": assistant_messages[-1]}
        )
    if values.get("evidence_bundle_id"):
        yield encode_sse({
            "type": "evidence_available",
            "evidence_bundle_id": values["evidence_bundle_id"],
        })
    yield encode_sse(
        {
            "type": "stream_complete",
            "status": "completed",
            "checkpoint_id": checkpoint_id(state),
        }
    )


def _flush_traces() -> None:
    get_client().flush()


async def execute_command(thread_id: str, command: Any) -> AsyncIterator[str]:
    run_config = graph_runner.get_run_config(thread_id)
    try:
        async with AsyncPostgresSaver.from_conn_string(
            config.get_postgres_dsn()
        ) as memory:
            await memory.setup()
            compiled_graph = GRAPH_BUILDER.compile(
                checkpointer=memory,
                interrupt_before=["human_approval", "human_clarification"],
            )
            state = await compiled_graph.aget_state(run_config)
            if command.action == "query":
                if is_waiting_for_human(state):
                    yield await run_in_threadpool(_approval_event, state)
                    yield encode_sse(
                        {
                            "type": "stream_error",
                            "code": "interaction_pending",
                            "message": "This conversation is waiting for a human response.",
                        }
                    )
                    return
                query = command.query.strip()
                if state.values:
                    message = HumanMessage(content=query, id=uuid.uuid4().hex)
                    input_payload = {
                        "messages": [message],
                        "supervisor_history": [message],
                        "evidence_bundle_id": None,
                        "web_research_state": None,
                    }
                    if command.user_profile and not state.values.get("user_profile"):
                        input_payload["user_profile"] = command.user_profile
                else:
                    input_payload = graph_runner.get_initial_state(
                        query, command.user_profile
                    )
                yield encode_sse({"type": "stream_started", "command": "query"})
                yield encode_sse(
                    {
                        "type": "message_started",
                        "message_id": input_payload["messages"][0].id,
                    }
                )
            elif command.action == "resume":
                if not is_waiting_for_human(state):
                    yield encode_sse(
                        {
                            "type": "stream_error",
                            "code": "not_paused",
                            "message": "This conversation is not waiting for human input.",
                        }
                    )
                    return
                actual_checkpoint = checkpoint_id(state)
                if (
                    command.checkpoint_id
                    and actual_checkpoint
                    and command.checkpoint_id != actual_checkpoint
                ):
                    yield encode_sse(
                        {
                            "type": "stream_error",
                            "code": "stale_checkpoint",
                            "message": "The conversation changed after it was loaded. Reload the thread before responding.",
                            "checkpoint_id": actual_checkpoint,
                        }
                    )
                    return
                selection = command.scenario_selection
                if selection and not scenario_editor_pending(state):
                    yield encode_sse({"type": "stream_error", "code": "unexpected_scenario", "message": "The spatial agent has not requested scenario selection."})
                    return
                await compiled_graph.aupdate_state(
                    run_config,
                    {
                        "user_feedback": command.response.strip(),
                        "sub_agent_message": "",
                        "scenario_editor_requested": False,
                        **({"scenario_selection": selection.model_dump(mode="json")} if selection else {}),
                    },
                )
                yield encode_sse({"type": "stream_started", "command": "resume"})
                input_payload = None
            else:
                if is_waiting_for_human(state):
                    yield encode_sse(
                        {
                            "type": "stream_error",
                            "code": "interaction_pending",
                            "message": "Cannot retry. The conversation is waiting for human input.",
                        }
                    )
                    return
                yield encode_sse({"type": "stream_started", "command": "retry"})
                input_payload = None
            async for event in stream_graph(compiled_graph, run_config, input_payload):
                yield event
    except Exception:
        _logger.exception("Conversation command failed for thread %s", thread_id)
        yield encode_sse(
            {
                "type": "stream_error",
                "code": "execution_failed",
                "message": "The graph command failed. The latest checkpoint remains available.",
            }
        )
    finally:
        await run_in_threadpool(_flush_traces)


async def run_background_command(
    thread_id: str, command: Any, active_command: ActiveCommand
) -> None:
    stream = active_command.stream
    try:
        async for event in execute_command(thread_id, command):
            await stream.append(event)
    except Exception:
        await stream.append(
            encode_sse(
                {
                    "type": "stream_error",
                    "code": "execution_failed",
                    "message": "The graph command failed. The latest checkpoint remains available.",
                }
            )
        )
    finally:
        try:
            await stream.close()
        finally:
            if active_commands.get(thread_id) is active_command:
                del active_commands[thread_id]


def start_command(thread_id: str, command: Any, owner_id: str) -> EventStream:
    active_command = active_commands.get(thread_id)
    if active_command is not None:
        if active_command.owner_id != owner_id:
            raise PermissionError("Command stream owner does not match thread owner.")
        return active_command.stream

    active_command = ActiveCommand(owner_id=owner_id, stream=EventStream())
    active_commands[thread_id] = active_command
    asyncio.create_task(run_background_command(thread_id, command, active_command))
    return active_command.stream
