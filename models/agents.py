from typing import List, Annotated, Optional, Union, Literal
from pydantic import BaseModel, Field
import operator
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage

AVAILABLE_ROUTES = {
    "vector_agent_node": "Route to this node for domain knowledge, research papers, internal documents.",
    "spatial_agent_node": "Route to this node for spatial hazard data and related information.",
    "web_agent_node": "Route to this node for web research and information gathering, only if the information is not available in the internal documents or spatial data.",
    "human_approval": "Route to this node for human approval of the proposed plan.",
    "human_clarification": "Route to this node for clarification",
}


class ExecutiveRouter(BaseModel):
    next_node: Literal["planning_node", "execute_plan", "generate_answer"] = Field(
        description="Must be one of: 'planning_node', 'execute_plan', 'generate_answer'"
    )


class SearchTask(BaseModel):
    queries: List[str] = Field(
        description="Vector search queries. Must use the returned context of the files to make this query."
    )
    target_file: str = Field(
        description="The exact filename to run this query against."
    )


class CityContext(BaseModel):
    city_id: int = Field(description="City identifier.")
    city_name: str = Field(description="City name.")


class ProvinceContext(BaseModel):
    province_id: int = Field(description="Province identifier.")
    province_name: str = Field(description="Province name.")
    city: Optional[List[CityContext]] = Field(
        default=list,
        description="Optional city nested under this province.",
    )


class RegionContext(BaseModel):
    region_id: int = Field(description="Region identifier.")
    region_name: str = Field(description="Region name.")
    province: Optional[List[ProvinceContext]] = Field(
        default=list,
        description="Optional province nested under this region.",
    )


class HazardContext(BaseModel):
    hazard_id: int = Field(description="Hazard identifier.")
    hazard_name: str = Field(description="Hazard name.")
    hazard_file_path: str = Field(description="File path for the hazard data.")


class SpatialContext(BaseModel):
    hazard: List[HazardContext] = Field(
        description="List of Hazards context including id, name, and file path."
    )
    geographic_context: List[RegionContext] = Field(
        description=(
            "Nested geographic context as (List of region_id, region_name, "
            "Optional List of provinces with province_id, province_name if asked and Optional List of cities with city_id and city_name if asked)."
        )
    )


class Plan(BaseModel):
    selected_tools: List[str] = Field(
        description="List of selected tools to use for the final plan."
    )
    vector_tasks: List[SearchTask] = Field(
        description="List of search tasks with vector queries and target files."
    )
    spatial_context: List[SpatialContext] = Field(
        description="List of highly relevant spatial context covering hazard data files, province, city and region information."
    )


def clearable_add(left: list, right: list | str):
    if right == "__CLEAR__":
        return []
    return operator.add(left, right)


def clearable_agent_add(left: dict, right: Union[dict, str]) -> dict:
    if right == "__CLEAR__":
        return {}

    result = dict(left) if left else {}

    if not isinstance(right, dict):
        return result

    for agent_name, nodes in right.items():
        if nodes == "__CLEAR__":
            result[agent_name] = []
        elif isinstance(nodes, list):
            existing_history = result.get(agent_name, [])
            result[agent_name] = existing_history + nodes

    return result


class GraphState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    supervisor_history: Annotated[list[AnyMessage], add_messages]
    spatial_search_history: Annotated[list[AnyMessage], add_messages]
    vector_search_history: Annotated[list[AnyMessage], add_messages]
    web_search_history: Annotated[list[AnyMessage], add_messages]
    plan: Plan
    retrieved_context: dict
    nodes_visited: Annotated[dict[str, list[str]], clearable_agent_add]
    user_feedback: str
    feedback_requested: str
    next_node_context: str
    sub_agent_message: str
    next_node: str
    resume_node: str
    user_profile: Optional[dict]
    last_map_layers: list[dict]
    new_map_layers: list[dict]


class SpatialAgentOutput(BaseModel):
    spatial_context: Optional[List[SpatialContext]] = Field(
        default=[],
        description="List of highly relevant spatial context covering hazard data files, province, city and region information.",
    )
    message: str = Field(
        description="A message that summarizes your decision and reasoning."
    )


class VectorAgentOutput(BaseModel):
    vector_tasks: Optional[List[SearchTask]] = Field(
        default=[],
        description="List of search tasks, you MUST provide vector queries based on the retrieved context targeting the specific sections of the files.",
    )
    message: str = Field(
        description="A message that summarizes your decision and reasoning."
    )


class SupervisorRouter(BaseModel):
    next_node: Literal[
        "spatial_agent_node",
        "vector_agent_node",
        "web_agent_node",
        "human_approval",
        "human_clarification",
    ] = Field(description="The next agent node to route to.")
    next_node_context: str = Field(
        description=f"""The query to be passed to the next node/sub-agent to gather more information."""
    )


class WebResearchItem(BaseModel):
    url: str = Field(description="Source URL.")
    title: str = Field(default="", description="Source title.")
    content: str = Field(description="Relevant source content.")


class FinishResearchInput(BaseModel):
    selected_indices: list[int] = Field(
        default_factory=list,
        description="Indices of the useful results from the AVAILABLE WEB RESULTS section. Select only relevant evidence.",
    )

    message: str = Field(
        default="Web research completed.",
        description="A concise summary of the research outcome and why the selected results are useful.",
    )
