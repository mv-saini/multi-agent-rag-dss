from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse, StreamingResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import config
from routers.auth import _require_authentication
from core import graph_runner
from services.evidence import display_bundle
from services.layer_export import shapefile_zip
from core.storage import evidence_store, sql_database
from services.conversations import (
    GRAPH_BUILDER,
    active_commands,
    session_payload,
    start_command,
)
from services.sse import SSE_HEADERS, encode_sse
from models.seismic import ScenarioSelection

router = APIRouter(prefix="/api")


class QueryCommand(BaseModel):
    action: Literal["query"]
    query: str = Field(min_length=1)
    user_profile: dict[str, Any] = Field(default_factory=dict)


class ResumeCommand(BaseModel):
    action: Literal["resume"]
    response: str = Field(min_length=1)
    checkpoint_id: str | None = None
    scenario_selection: ScenarioSelection | None = None


class RetryCommand(BaseModel):
    action: Literal["retry"]


class ThreadUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=100)


Command = Annotated[
    QueryCommand | ResumeCommand | RetryCommand,
    Field(discriminator="action"),
]


def _sse_response(stream) -> StreamingResponse:
    return StreamingResponse(
        stream.subscribe(), media_type="text/event-stream", headers=SSE_HEADERS
    )


def _thread_access_error(thread_id: str, user_id: str) -> JSONResponse | None:
    """Return an error if the thread does not belong to the authenticated user."""
    conn = None
    try:
        conn = sql_database.get_connection()
        conversation = conn.execute(
            "SELECT 1 FROM conversations WHERE conversationid = %s AND userid = %s",
            (thread_id, user_id),
        ).fetchone()
        conn.commit()
    except Exception:
        if conn is not None:
            conn.rollback()
        return JSONResponse(
            status_code=500,
            content={"data": None, "error": "Unable to verify conversation access."},
        )
    finally:
        if conn is not None:
            conn.close()

    if conversation is None:
        return JSONResponse(
            status_code=404,
            content={"data": None, "error": "Conversation not found."},
        )
    return None


@router.get("/threads")
def get_threads(
    _user: dict[str, str] = Depends(_require_authentication),
) -> Response:
    conn = sql_database.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, conversationid, title, datetime, userid FROM conversations WHERE userid = %s ORDER BY datetime DESC",
            (_user["id"],),
        ).fetchall()
        conn.commit()
    except Exception:
        conn.rollback()
        return JSONResponse(
            status_code=500, content={"data": None, "error": "Internal Server Error"}
        )
    finally:
        conn.close()
    return JSONResponse(
        status_code=200,
        content={
            "data": [
                {
                    "id": row[0],
                    "conversationid": row[1],
                    "title": row[2],
                    "datetime": row[3].isoformat() if row[3] else None,
                    "userid": row[4],
                }
                for row in rows
            ],
            "error": None,
        },
    )


@router.put("/threads/{thread_id}")
def update_thread(
    thread_id: str,
    update: ThreadUpdate,
    _user: dict[str, str] = Depends(_require_authentication),
) -> Response:
    title = update.title.strip()
    if not title:
        return JSONResponse(
            status_code=422,
            content={"data": None, "error": "Conversation title cannot be empty."},
        )

    conn = sql_database.get_connection()
    try:
        row = conn.execute(
            "UPDATE conversations SET title = %s WHERE conversationid = %s AND userid = %s RETURNING id, conversationid, title, datetime, userid",
            (title, thread_id, _user["id"]),
        ).fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        return JSONResponse(
            status_code=500,
            content={"data": None, "error": "Unable to rename the conversation."},
        )
    finally:
        conn.close()

    if row is None:
        return JSONResponse(
            status_code=404,
            content={"data": None, "error": "Conversation not found."},
        )
    return JSONResponse(
        status_code=200,
        content={
            "data": {
                "id": row[0],
                "conversationid": row[1],
                "title": row[2],
                "datetime": row[3].isoformat() if row[3] else None,
                "userid": row[4],
            },
            "error": None,
        },
    )


@router.delete("/threads/{thread_id}")
def delete_thread(
    thread_id: str,
    _user: dict[str, str] = Depends(_require_authentication),
) -> Response:
    conn = sql_database.get_connection()
    try:
        row = conn.execute(
            "DELETE FROM conversations WHERE conversationid = %s AND userid = %s RETURNING conversationid",
            (thread_id, _user["id"]),
        ).fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        return JSONResponse(
            status_code=500,
            content={"data": None, "error": "Unable to delete the conversation."},
        )
    finally:
        conn.close()

    if row is None:
        return JSONResponse(
            status_code=404,
            content={"data": None, "error": "Conversation not found."},
        )
    return JSONResponse(
        status_code=200,
        content={"data": {"conversationid": row[0]}, "error": None},
    )


@router.get("/threads/{thread_id}/evidence/{bundle_id}")
def get_evidence(
    thread_id: str, bundle_id: str,
    _user: dict[str, str] = Depends(_require_authentication),
) -> Response:
    access_error = _thread_access_error(thread_id, _user["id"])
    if access_error is not None:
        return access_error
    try:
        payload = display_bundle(bundle_id, thread_id)
    except LookupError:
        return JSONResponse(
            status_code=404, content={"data": None, "error": "Evidence bundle not found."}
        )
    return JSONResponse(content={"data": payload, "error": None})


@router.get("/threads/{thread_id}/evidence/{bundle_id}/shapefile")
def download_shapefile(
    thread_id: str, bundle_id: str, layer_id: str,
    _user: dict[str, str] = Depends(_require_authentication),
) -> Response:
    access_error = _thread_access_error(thread_id, _user["id"])
    if access_error is not None:
        return access_error
    try:
        bundle = evidence_store.load(bundle_id, thread_id)
        filename, content = shapefile_zip(bundle, layer_id)
    except LookupError as exc:
        return JSONResponse(status_code=404, content={"data": None, "error": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"data": None, "error": str(exc)})
    return Response(content=content, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "private, no-store",
    })


@router.get("/history/{thread_id}")
async def get_history(
    thread_id: str, _user: dict[str, str] = Depends(_require_authentication)
) -> Response:
    access_error = await run_in_threadpool(_thread_access_error, thread_id, _user["id"])
    if access_error is not None:
        return access_error

    run_config = graph_runner.get_run_config(thread_id)
    async with AsyncPostgresSaver.from_conn_string(config.get_postgres_dsn()) as memory:
        await memory.setup()
        compiled_graph = GRAPH_BUILDER.compile(
            checkpointer=memory,
            interrupt_before=["human_approval", "human_clarification"],
        )
        state = await compiled_graph.aget_state(run_config)
    payload = await session_payload(thread_id, state)
    return await run_in_threadpool(
        JSONResponse, status_code=200, content={"data": payload, "error": None}
    )


def _create_thread(
    thread_id: str, command: QueryCommand, user_id: str
) -> dict | JSONResponse:
    """Create a conversation thread."""
    conn = None
    try:
        conn = sql_database.get_connection()
        result = conn.execute(
            "INSERT INTO conversations (conversationid, title, datetime, userid) VALUES (%s, %s, CURRENT_TIMESTAMP, %s) RETURNING id, conversationid, title, datetime, userid",
            (thread_id, command.query.strip()[:100], user_id),
        ).fetchone()
        conn.commit()
    except Exception:
        if conn is not None:
            conn.rollback()
        return JSONResponse(
            status_code=500,
            content={"data": None, "error": "Unable to create the conversation."},
        )
    finally:
        if conn is not None:
            conn.close()
    return {
        "id": result[0],
        "conversationid": result[1],
        "title": result[2],
        "datetime": result[3].isoformat() if result[3] else None,
        "userid": result[4],
    }


@router.post("/threads/commands")
async def execute_new_command(
    command: Command, _user: dict[str, str] = Depends(_require_authentication)
) -> Response:
    if not isinstance(command, QueryCommand):
        return JSONResponse(
            status_code=400,
            content={
                "data": None,
                "error": "A new conversation must start with a query.",
            },
        )
    thread_id = uuid.uuid4().hex
    thread = await run_in_threadpool(_create_thread, thread_id, command, _user["id"])
    if isinstance(thread, JSONResponse):
        return thread
    stream = start_command(thread_id, command, _user["id"])

    async def events():
        yield encode_sse({"type": "new_thread", "thread": thread})
        async for event in stream.subscribe():
            yield event

    return StreamingResponse(
        events(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.post("/threads/{thread_id}/commands")
async def execute_command(
    thread_id: str,
    command: Command,
    _user: dict[str, str] = Depends(_require_authentication),
) -> Response:
    access_error = await run_in_threadpool(_thread_access_error, thread_id, _user["id"])
    if access_error is not None:
        return access_error

    return _sse_response(start_command(thread_id, command, _user["id"]))


@router.get("/threads/{thread_id}/events")
async def subscribe_to_command(
    thread_id: str, _user: dict[str, str] = Depends(_require_authentication)
) -> Response:
    access_error = await run_in_threadpool(_thread_access_error, thread_id, _user["id"])
    if access_error is not None:
        return access_error

    active_command = active_commands.get(thread_id)
    if active_command is None or active_command.owner_id != _user["id"]:
        return StreamingResponse(
            iter(()), status_code=204, media_type="text/event-stream"
        )
    return _sse_response(active_command.stream)
