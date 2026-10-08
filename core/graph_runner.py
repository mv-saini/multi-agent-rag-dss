from langfuse.langchain import CallbackHandler
from langchain_core.messages import HumanMessage
import config
from langgraph.graph.state import CompiledStateGraph
from models.agents import GraphState
import uuid


def get_run_config(thread_id: str):
    """Returns the run configuration."""
    langfuse_handler = CallbackHandler(trace_context={"trace_id": uuid.uuid4().hex})
    llm_config = {"callbacks": [langfuse_handler]} if langfuse_handler else {}

    config.llm_config = llm_config

    return {**llm_config, "configurable": {"thread_id": thread_id}}


def get_initial_state(query: str, user_profile: dict = None):
    """Returns the starting state for a new query."""
    query_content = query.strip() if query else ""
    uuid_id = uuid.uuid4().hex
    msg = HumanMessage(content=query_content, id=uuid_id)

    return {
        "messages": [msg],
        "supervisor_history": [msg],
        "spatial_search_history": [],
        "vector_search_history": [],
        "web_search_history": [],
        "plan": {"selected_tools": [], "vector_tasks": [], "spatial_context": []},
        "retrieved_context": {
            "vector_docs": [],
            "spatial_analysis": [],
            "web_results": [],
        },
        "user_feedback": "",
        "feedback_requested": "",
        "next_node": "",
        "resume_node": "",
        "user_profile": user_profile,
        "last_map_layers": [],
        "new_map_layers": [],
    }


async def stream_normalized_events(
    graph: CompiledStateGraph[GraphState, None, GraphState, GraphState],
    input_payload: dict,
    run_config: dict,
):
    """Streams events from the graph to the client."""
    async for event in graph.astream_events(
        input_payload, config=run_config, version="v2"
    ):
        kind = event["event"]

        if kind == "on_chat_model_stream":
            if event.get("metadata", {}).get("is_background_task"):
                continue

            chunk = event["data"]["chunk"]

            for block in chunk.content_blocks:
                block_type = block.get("type")

                if block_type == "text":
                    text = block.get("text", "")
                    if text:
                        yield {
                            "type": "token",
                            "content": text,
                        }

                elif block_type == "reasoning":
                    reasoning = block.get("reasoning", "")
                    if reasoning:
                        yield {
                            "type": "reasoning",
                            "content": reasoning,
                        }

                # elif block_type == "tool_call_chunk":
                #     yield {
                #         "type": "tool_call",
                #         "name": block.get("name"),
                #         "args": block.get("args"),
                #         "id": block.get("id"),
                #     }

        elif kind == "on_tool_start":
            yield {
                "type": "tool_start",
                "name": event["name"],
                "input": event["data"].get("input"),
            }

        elif kind == "on_tool_end":
            yield {"type": "tool_end", "name": event["name"]}

        elif kind == "on_retriever_start":
            yield {
                "type": "retriever_start",
                "name": event["name"],
                "query": event["data"].get("input", {}).get("query", ""),
            }

        elif kind == "on_custom_event":
            yield {"type": "custom_event", "name": event["name"], "data": event["data"]}
