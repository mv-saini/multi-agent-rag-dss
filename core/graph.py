from langgraph.graph import StateGraph, START, END
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import HumanMessage, RemoveMessage, AIMessage
from langchain_core.callbacks import adispatch_custom_event
from copy import deepcopy
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
from models.agents import GraphState
from langgraph.graph.message import REMOVE_ALL_MESSAGES


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
    planner_state = {
        "supervisor_history": state.get("supervisor_history", []),
        "plan": state.get("plan", {}),
        "nodes_visited": state.get("nodes_visited", {}).get("planning_node", []),
        "sub_agent_message": state.get("sub_agent_message", ""),
        "user_profile": state.get("user_profile", {}),
        "web_results": state.get("retrieved_context", {}).get("web_results", []),
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
    }

    update = await spatial_data_agent.run(
        state=spatial_state,
        run_config=config,
    )

    if not update.get("feedback_requested"):
        spatial_context = update.pop("spatial_context", [])
        if spatial_context:
            plan_update = state.get("plan", {})
            if "spatial_database" not in plan_update["selected_tools"]:
                plan_update["selected_tools"] = plan_update["selected_tools"] + [
                    "spatial_database"
                ]
            plan_update["spatial_context"] = spatial_context
            update["plan"] = plan_update

    return update


async def web_agent_node(state: GraphState, config: RunnableConfig):
    """
    Web agent processing.
    """
    web_state = {
        "web_search_history": state.get("web_search_history", []),
        "agent_query": state.get("next_node_context", ""),
        "web_results": state.get("retrieved_context", {}).get("web_results", []),
        "user_profile": state.get("user_profile", {}),
    }

    update = await web_agent.run(
        state=web_state,
        run_config=config,
    )

    if not update.get("feedback_requested"):
        web_results = update.pop("web_results", [])
        update["retrieved_context"] = {"web_results": web_results}

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
            updated_message = deepcopy(last_human_message)
            feedbackQA = {
                "id": response_message.id,
                "question": "Feedback requested for plan approval.",
                "answer": response,
            }
            updated_message.additional_kwargs.setdefault("feedback", []).append(
                feedbackQA
            )

            state_update["messages"] = [updated_message]
    else:
        state_update["next_node"] = "execute_plan"

    return state_update


async def human_clarification_node(state: GraphState):
    resume_node = state.get("resume_node", "planning_node")
    state_update = {}

    response = state.get("user_feedback", "")
    response_message = HumanMessage(content=response, id=uuid.uuid4().hex)

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
    elif resume_node == "planning_node":
        state_update["supervisor_history"] = (
            [response_message] if response_message else []
        )

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
            updated_message = deepcopy(last_human_message)
            feedbackQA = {
                "id": response_message.id,
                "question": state.get("feedback_requested", ""),
                "answer": response,
            }
            updated_message.additional_kwargs.setdefault("feedback", []).append(
                feedbackQA
            )

            state_update["messages"] = [updated_message]

    state_update["feedback_requested"] = ""
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


def _collect_map_layers(spatial_analysis: list[dict]) -> list[dict]:
    layers = []

    for analysis in spatial_analysis or []:
        if not analysis:
            continue

        map_layers = analysis.pop("map_layers", [])

        for layer in map_layers:
            if layer and not layer.get("empty", False):
                layers.append(layer)

    return layers


async def execute_plan_node(state: GraphState, config: RunnableConfig):
    """
    Executes the approved plan by calling the required tools (Vector / Spatial).
    """

    plan = state.get("plan", {})
    retrieved_context = state.get("retrieved_context", {})

    docs = list(retrieved_context.get("vector_docs", []))
    spatial_analysis = list(retrieved_context.get("spatial_analysis", []))

    if "vector_database" in plan.get("selected_tools", []):
        vector_tasks = plan.get("vector_tasks", [])
        retrieved_docs, all_docs, queries = await doc_retriever.retrieve(
            vector_tasks,
            run_config=config,
        )
        docs.extend(retrieved_docs)

    new_analysis = []
    new_map_layers = []

    if "spatial_database" in plan.get("selected_tools", []):
        spatial_context = plan.get("spatial_context", [])

        await adispatch_custom_event(
            "reasoning_header", "Analyzing spatial data...", config=config
        )

        new_analysis = spatial_retriever.retrieve(spatial_contexts=spatial_context)

        new_map_layers = _collect_map_layers(new_analysis)

        last_map_layers = list(state.get("last_map_layers", [])) + new_map_layers

        spatial_analysis.extend(new_analysis)
    else:
        last_map_layers = list(state.get("last_map_layers", []))

    return {
        "retrieved_context": {
            "vector_docs": docs,
            "spatial_analysis": spatial_analysis,
            "web_results": retrieved_context.get("web_results", []),
        },
        "last_map_layers": last_map_layers,
        "new_map_layers": new_map_layers,
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

    context_snapshot = deepcopy(state.get("retrieved_context", {}))
    plan_snapshot = deepcopy(state.get("plan", {}))

    generate_answer_state = {
        "messages": state.get("messages", []),
        "retrieved_context": state.get("retrieved_context", {}),
        "user_profile": state.get("user_profile", {}),
    }

    final_answer = await answer_generator_agent.run(
        state=generate_answer_state,
        run_config=config,
    )

    final_message = AIMessage(content=final_answer.content, id=final_answer.id)
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
        updated_message = deepcopy(last_human_message)

        updated_message.additional_kwargs.setdefault("retrieved_context", {})
        updated_message.additional_kwargs["retrieved_context"] = context_snapshot

        updated_message.additional_kwargs.setdefault("plan", {})
        updated_message.additional_kwargs["plan"] = plan_snapshot

        messages_to_return.insert(0, updated_message)

    return {
        "messages": messages_to_return,
        "spatial_search_history": wipe,
        "vector_search_history": wipe,
        "web_search_history": wipe,
        "supervisor_history": reset_supervisor,
        "nodes_visited": "__CLEAR__",
        "plan": {"selected_tools": [], "vector_tasks": [], "spatial_context": []},
        "retrieved_context": {
            "vector_docs": [],
            "spatial_analysis": [],
            "web_results": [],
        },
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
