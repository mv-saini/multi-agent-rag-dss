from langgraph.graph import StateGraph, START, END
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import HumanMessage, RemoveMessage, AIMessage
from langchain_core.callbacks import adispatch_custom_event
from copy import deepcopy
import json
from starlette.concurrency import run_in_threadpool
from utils.concurrency import run_spatial
import uuid
from agents import (
    answer_generator_agent,
    planning_agent,
    routing_node,
    vector_file_selection_agent,
    spatial_data_agent,
    web_agent,
)
from core.retrieval import doc_retriever, spatial_retriever
from core.storage import evidence_store
from models.agents import GraphState
from langgraph.graph.message import REMOVE_ALL_MESSAGES


async def _load_evidence(state: GraphState, config: RunnableConfig) -> dict:
    return await run_in_threadpool(
        evidence_store.load,
        state.get("evidence_bundle_id"),
        config["configurable"]["thread_id"],
    )


async def _save_evidence(
    state: GraphState, config: RunnableConfig, bundle: dict
) -> str:
    message_index = _get_last_human_index(state.get("messages", []))
    if message_index is None:
        raise ValueError("Evidence requires a query message.")
    execution_id = state["messages"][message_index].id
    if not execution_id:
        raise ValueError("Evidence requires a stable query message ID.")
    return await run_in_threadpool(
        evidence_store.save,
        config["configurable"]["thread_id"],
        execution_id,
        bundle,
    )


async def router_node(state: GraphState, config: RunnableConfig):
    """
    Routing agent.
    """
    router_state = {
        "messages": state.get("messages", []),
        "plan": state.get("plan", {}),
        "user_feedback": state.get("user_feedback", ""),
    }

    await adispatch_custom_event("reasoning_header", "Routing...", config=config)
    update = await routing_node.run(
        state=router_state,
        run_config=config,
    )

    return update


async def planning_node(state: GraphState, config: RunnableConfig):
    """
    Planning agent.
    """
    bundle = await _load_evidence(state, config)
    planner_state = {
        "supervisor_history": state.get("supervisor_history", []),
        "plan": state.get("plan", {}),
        "nodes_visited": state.get("nodes_visited", {}).get("planning_node", []),
        "sub_agent_message": state.get("sub_agent_message", ""),
        "user_profile": state.get("user_profile", {}),
        "web_results": bundle["context"].get("web_results", []),
    }

    await adispatch_custom_event("reasoning_header", "Planning...", config=config)
    update = await planning_agent.run(
        state=planner_state,
        run_config=config,
    )

    return update


async def vector_agent_node(state: GraphState, config: RunnableConfig):
    """
    Vector agent processing.
    """
    vector_state = {
        "vector_search_history": state.get("vector_search_history", []),
        "agent_query": state.get("next_node_context", ""),
        "vector_tasks": state.get("plan", {}).get("vector_tasks", []),
        "user_profile": state.get("user_profile", {}),
    }

    update = await vector_file_selection_agent.run(
        state=vector_state,
        run_config=config,
    )

    if not update.get("feedback_requested"):
        vector_tasks = update.pop("vector_tasks", [])
        if vector_tasks:
            plan_update = state.get("plan", {})
            if "vector_database" not in plan_update["selected_tools"]:
                plan_update["selected_tools"] = plan_update["selected_tools"] + [
                    "vector_database"
                ]
            plan_update["vector_tasks"] = vector_tasks
            update["plan"] = plan_update

    return update


async def spatial_agent_node(state: GraphState, config: RunnableConfig):
    """
    Spatial agent processing.
    """
    spatial_state = {
        "spatial_search_history": state.get("spatial_search_history", []),
        "agent_query": state.get("next_node_context", ""),
        "spatial_context": state.get("plan", {}).get("spatial_context", []),
        "user_profile": state.get("user_profile", {}),
        "scenario_request": state.get("scenario_request"),
        "scenario_selection": state.get("scenario_selection"),
    }

    update = await spatial_data_agent.run(
        state=spatial_state,
        run_config=config,
    )

    if not update.get("feedback_requested"):
        spatial_context = update.pop("spatial_context", [])
        plan_update = dict(state.get("plan", {}))
        selected_tools = list(plan_update.get("selected_tools", []))
        if spatial_context:
            if "spatial_database" not in selected_tools:
                selected_tools.append("spatial_database")
        else:
            selected_tools = [
                tool for tool in selected_tools if tool != "spatial_database"
            ]
        plan_update["selected_tools"] = selected_tools
        plan_update["spatial_context"] = spatial_context
        update["plan"] = plan_update

    return update


async def web_agent_node(state: GraphState, config: RunnableConfig):
    """
    Web agent processing.
    """
    bundle = await _load_evidence(state, config)
    web_state = {
        "web_search_history": state.get("web_search_history", []),
        "web_research_state": state.get("web_research_state"),
        "agent_query": state.get("next_node_context", ""),
        "web_results": bundle["context"].get("web_results", []),
        "user_profile": state.get("user_profile", {}),
    }

    update = await web_agent.run(
        state=web_state,
        run_config=config,
    )

    if "web_results" in update:
        bundle["context"]["web_results"] = update.pop("web_results")
        update["evidence_bundle_id"] = await _save_evidence(state, config, bundle)

    return update


async def human_approval_node(state: GraphState):
    state_update = {}
    response = state.get("user_feedback", "")
    response_message = HumanMessage(content=response, id=uuid.uuid4().hex)

    state_update["supervisor_history"] = [response_message]

    if response.lower() not in ["y", "yes"]:
        state_update["next_node"] = "router_node"
        message_history = state.get("messages", [])
        last_human_idx = next(
            (
                i
                for i in range(len(message_history) - 1, -1, -1)
                if getattr(message_history[i], "type", None) == "human"
            ),
            None,
        )

        if last_human_idx is not None:
            last_human_message = message_history[last_human_idx]
            updated_message = await run_in_threadpool(deepcopy, last_human_message)
            feedbackQA = {
                "id": response_message.id,
                "question": (
                    state.get("next_node_context")
                    or "Feedback requested for plan approval."
                ),
                "answer": response,
            }
            updated_message.additional_kwargs.setdefault("feedback", []).append(
                feedbackQA
            )

            state_update["messages"] = [updated_message]
    else:
        state_update["next_node"] = "execute_plan"

    state_update["next_node_context"] = ""

    return state_update


async def human_clarification_node(state: GraphState):
    resume_node = state.get("resume_node", "planning_node")
    state_update = {}

    response = state.get("user_feedback", "")
    response_message = HumanMessage(content=response, id=uuid.uuid4().hex)

    # Share clarification replies with the supervisor so it sees scope changes.
    state_update["supervisor_history"] = [
        HumanMessage(
            content=(
                f"User clarification for {resume_node}:\n"
                f"Question: {state.get('feedback_requested', '')}\n"
                f"Answer: {response}"
            ),
            id=response_message.id,
        )
    ]

    if resume_node == "spatial_agent_node":
        state_update["spatial_search_history"] = (
            [response_message] if response_message else []
        )
    elif resume_node == "vector_agent_node":
        state_update["vector_search_history"] = (
            [response_message] if response_message else []
        )
    elif resume_node == "web_agent_node":
        state_update["web_search_history"] = (
            [response_message] if response_message else []
        )

    message_history = state.get("messages", [])
    last_human_idx = _get_last_human_index(message_history)
    if last_human_idx is not None:
        updated_message = await run_in_threadpool(
            deepcopy, message_history[last_human_idx]
        )
        updated_message.additional_kwargs.setdefault("feedback", []).append(
            {
                "id": response_message.id,
                "question": state.get("feedback_requested", ""),
                "answer": response,
            }
        )
        state_update["messages"] = [updated_message]

    state_update["feedback_requested"] = ""
    state_update["next_node_context"] = ""
    state_update["scenario_editor_requested"] = False
    state_update["user_feedback"] = ""

    return state_update


def route_after_router(state: GraphState) -> str:
    """
    Dynamic routing based on Router prediction.
    """
    return state.get("next_node", "router_node")


def route_after_planning(state: GraphState) -> str:
    """
    Dynamic routing based on Supervisor prediction.
    """
    return state.get("next_node", "human_approval")


def route_after_clarification(state: GraphState) -> str:
    """Routes to the resume_node to continue after clarification."""
    return state.get("resume_node", "planning_node")


def route_after_sub_agents(state: GraphState) -> str:
    """
    If sub-agent asks for clarification, route to human. Else back to planner.
    """
    return state.get("next_node", "planning_node")


def route_after_human(state: GraphState) -> str:
    """Routes to the execution node if approved, or loops back to planning node to fix it."""
    return state.get("next_node", "planning_node")


def _get_last_human_index(message_history: list[HumanMessage]) -> int:
    """
    Returns the index of the last human message in the message history.
    """

    return next(
        (
            i
            for i in range(len(message_history) - 1, -1, -1)
            if getattr(message_history[i], "type", None) == "human"
        ),
        None,
    )


async def execute_plan_node(state: GraphState, config: RunnableConfig):
    """
    Executes the approved plan by calling the required tools (Vector / Spatial).
    """

    plan = state.get("plan", {})
    bundle = await _load_evidence(state, config)
    retrieved_context = bundle["context"]

    docs = list(retrieved_context.get("vector_docs", []))
    spatial_analysis = list(retrieved_context.get("spatial_analysis", []))

    if "vector_database" in plan.get("selected_tools", []):
        vector_tasks = plan.get("vector_tasks", [])
        retrieved_docs, all_docs, queries = await doc_retriever.retrieve(
            vector_tasks,
            run_config=config,
        )
        docs.extend(retrieved_docs)

        # if retrieved_docs:
        #     with open(f"retrieved_docs_{uuid.uuid4().hex}.json", "w") as f:
        #         json.dump(
        #             [document.model_dump(mode="json") for document in retrieved_docs],
        #             f,
        #             indent=4,
        #         )
        #         print(f"Saved retrieved docs to {f.name}")
        # if all_docs:
        #     with open(f"all_vector_docs_{uuid.uuid4().hex}.json", "w") as f:
        #         json.dump(
        #             [document.model_dump(mode="json") for document in all_docs],
        #             f,
        #             indent=4,
        #         )
        #         print(f"Saved all vector docs to {f.name}")

    map_layers = list(bundle["map_layers"])

    if "spatial_database" in plan.get("selected_tools", []):
        spatial_context = plan.get("spatial_context", [])

        await adispatch_custom_event(
            "reasoning_header", "Analyzing spatial data...", config=config
        )

        new_analysis = await run_spatial(
            spatial_retriever.retrieve, spatial_contexts=spatial_context
        )

        for analysis in new_analysis:
            spatial_analysis.append(
                {key: value for key, value in analysis.items() if key != "map_layers"}
            )
            map_layers.extend(
                layer
                for layer in analysis.get("map_layers", [])
                if layer and not layer.get("empty", False)
            )

    bundle["context"] = {
        "vector_docs": docs,
        "spatial_analysis": spatial_analysis,
        "web_results": retrieved_context.get("web_results", []),
    }
    bundle["map_layers"] = map_layers
    return {
        "evidence_bundle_id": await _save_evidence(state, config, bundle),
        "feedback_requested": "",
        "next_node_context": "",
        "user_feedback": "",
        "next_node": "",
        "sub_agent_message": "",
        "resume_node": "",
    }


async def generate_answer_node(state: GraphState, config: RunnableConfig):
    """
    Generate final answer based on the retrieved context.
    """

    bundle = await _load_evidence(state, config)
    plan_snapshot = await run_in_threadpool(deepcopy, state.get("plan", {}))

    generate_answer_state = {
        "messages": state.get("messages", []),
        "retrieved_context": bundle["context"],
        "user_profile": state.get("user_profile", {}),
    }

    final_answer = await answer_generator_agent.run(
        state=generate_answer_state,
        run_config=config,
    )

    final_message = AIMessage(
        content=final_answer.content,
        id=final_answer.id,
        additional_kwargs=await run_in_threadpool(
            deepcopy, final_answer.additional_kwargs
        ),
        response_metadata=await run_in_threadpool(
            deepcopy, final_answer.response_metadata
        ),
    )
    bundle["citation_sources"] = final_message.additional_kwargs.pop(
        "citation_sources", {}
    )
    bundle_id = await _save_evidence(state, config, bundle)
    final_message.additional_kwargs["evidence_bundle_id"] = bundle_id
    chat_message = HumanMessage(content=final_answer.content, id=final_answer.id)

    wipe = [RemoveMessage(id=REMOVE_ALL_MESSAGES)]
    supervisor_messages = state.get("supervisor_history", [])[
        : len(state.get("messages", []))
    ]
    reset_supervisor = wipe + supervisor_messages + [chat_message]

    message_history = state.get("messages", [])
    last_human_idx = _get_last_human_index(message_history)

    messages_to_return = [final_message]

    if last_human_idx is not None:
        last_human_message = message_history[last_human_idx]
        updated_message = await run_in_threadpool(deepcopy, last_human_message)

        updated_message.additional_kwargs["evidence_bundle_id"] = bundle_id

        updated_message.additional_kwargs.setdefault("plan", {})
        updated_message.additional_kwargs["plan"] = plan_snapshot

        messages_to_return.insert(0, updated_message)

    return {
        "messages": messages_to_return,
        "spatial_search_history": wipe,
        "vector_search_history": wipe,
        "web_search_history": wipe,
        "web_research_state": None,
        "supervisor_history": reset_supervisor,
        "nodes_visited": "__CLEAR__",
        "plan": {"selected_tools": [], "vector_tasks": [], "spatial_context": []},
        "evidence_bundle_id": bundle_id,
        "scenario_request": None,
        "scenario_editor_requested": False,
        "scenario_selection": None,
    }


def build():
    workflow = StateGraph(GraphState)

    workflow.add_node("router_node", router_node)
    workflow.add_node("planning_node", planning_node)
    workflow.add_node("vector_agent_node", vector_agent_node)
    workflow.add_node("spatial_agent_node", spatial_agent_node)
    workflow.add_node("web_agent_node", web_agent_node)
    workflow.add_node("human_approval", human_approval_node)
    workflow.add_node("human_clarification", human_clarification_node)
    workflow.add_node("execute_plan", execute_plan_node)
    workflow.add_node("generate_answer", generate_answer_node)

    workflow.add_edge(START, "router_node")

    workflow.add_conditional_edges(
        "router_node",
        route_after_router,
        ["planning_node", "execute_plan", "generate_answer"],
    )

    workflow.add_conditional_edges(
        "planning_node",
        route_after_planning,
        [
            "planning_node",
            "vector_agent_node",
            "spatial_agent_node",
            "web_agent_node",
            "human_clarification",
            "human_approval",
        ],
    )

    workflow.add_conditional_edges(
        "vector_agent_node",
        route_after_sub_agents,
        ["human_clarification", "planning_node"],
    )

    workflow.add_conditional_edges(
        "spatial_agent_node",
        route_after_sub_agents,
        ["human_clarification", "planning_node"],
    )

    workflow.add_conditional_edges(
        "web_agent_node",
        route_after_sub_agents,
        [
            "human_clarification",
            "planning_node",
        ],
    )

    workflow.add_conditional_edges(
        "human_approval",
        route_after_human,
        [
            "execute_plan",
            "router_node",
        ],
    )

    workflow.add_conditional_edges(
        "human_clarification",
        route_after_clarification,
        [
            "planning_node",
            "vector_agent_node",
            "spatial_agent_node",
            "web_agent_node",
        ],
    )

    workflow.add_edge("execute_plan", "generate_answer")
    workflow.add_edge("generate_answer", END)

    return workflow
