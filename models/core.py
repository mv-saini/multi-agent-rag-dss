from pydantic import BaseModel, Field
from typing import List, Optional, TypedDict
from enum import Enum


class EnhancedDocumentAnalysis(BaseModel):
    """Search-optimized factual description of document content."""

    answered_questions: List[str] = Field(
        default_factory=list,
        description=(
            "Specific, realistic user questions that the provided source "
            "content can directly and reliably answer. Questions must be "
            "answerable exclusively from the source and should maximize "
            "document discoverability."
        ),
    )

    visual_analysis: Optional[str] = Field(
        default="",
        description=(
            "Factual description of meaningful information visible in the "
            "provided images, including chart values and trends, table "
            "contents, diagram relationships, screenshot text/statuses, "
            "or identifiable visual elements. Never infer information that "
            "is not visibly supported. Empty string when no useful visual "
            "information is present."
        ),
    )

    search_keywords: List[str] = Field(
        default_factory=list,
        description=(
            "Concise search terms derived strictly from the source, "
            "including important entities, names, topics, technical terms, "
            "synonyms, abbreviations, acronyms, alternate terminology, "
            "and important phrases that users may search for."
        ),
    )

    comprehensive_summary: str = Field(
        description=(
            "Dense factual summary of the actual source content optimized "
            "for semantic/vector retrieval. Include important topics, "
            "entities, facts, dates, numbers, relationships, procedures, "
            "and meaningful information from tables, charts, and images. "
            "Do not add unsupported information."
        )
    )


class DocumentTitleOutput(BaseModel):
    title: str = Field(
        description="The single, overall document title inferred from the sections."
    )


class ContentData(TypedDict):
    text: str
    tables: List[str]
    images: List[str]
    types: List[str]


POPULATION_COLUMNS = ("P1", "A8", "E3", "PF1")

BREAKDOWN_KEYS = (
    "intensity_breakdown",
    "seismic_discrete_zones",
    "multi_hazard_spatial_breakdown",
)

RISK_COLOR_MAPS = {
    "landslide": {
        "Nulla": "#f7f7f7",
        "Moderata/Attenzione": "#ffffb2",
        "Media": "#fecc5c",
        "Elevata": "#fd8d3c",
        "Molto elevata": "#e31a1c",
    },
    "flood": {
        "None": "#f7f7f7",
        "Low": "#ffffb2",
        "Medium": "#fd8d3c",
        "High": "#e31a1c",
    },
    "seismic": {
        "Low Risk (0.00g - 0.05g)": "#ffffcc",
        "Moderate Risk (0.05g - 0.15g)": "#ffeda0",
        "High Risk (0.15g - 0.25g)": "#feb24c",
        "Very High Risk (0.25g - 0.35g)": "#f03b20",
        "Extremely High Risk (>0.35g)": "#bd0026",
    },
    "multi_hazard": {
        "Low Multi-Hazard (0-3)": "#24e100",
        "Moderate Multi-Hazard (3-6)": "#fff500",
        "High Multi-Hazard (6-9)": "#ff9b00",
        "Very High Multi-Hazard (9-12)": "#d7191c",
    },
}


class HazardKind(str, Enum):
    FLOOD = "flood"
    LANDSLIDE = "landslide"
    SEISMIC = "seismic"
    MULTI_HAZARD = "multi_hazard"
