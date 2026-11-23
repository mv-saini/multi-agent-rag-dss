from utils import llm_client
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from models.core import DocumentDiscoveryAnalysis, VisualAnalysis
import logging
import prompts

_logger = logging.getLogger(__name__)


async def agenerate_summaries(
    text: str,
    images: list[str],
    run_config: RunnableConfig | None = None,
):
    """
    Creates a visual analysis asynchronously using the surrounding text and images.
    """
    text = text.strip() if text else ""

    if not text and not images:
        _logger.warning("No text or images provided. Skipping LLM call.")
        return ""

    try:
        _logger.info(
            "Creating summary asynchronously using LLM for text length %d and %d images...",
            len(text),
            len(images) if images else 0,
        )

        llm = llm_client.get_llm()
        if llm is None:
            raise Exception("No LLM available for content enhancement.")

        prompt_text = prompts.summary_prompt

        if text:
            prompt_text += f"{text}\n\n"

        message_content = [{"type": "text", "text": prompt_text}]

        if images:
            for image_url in images:
                message_content.append(
                    {"type": "image_url", "image_url": {"url": image_url}}
                )

        message = HumanMessage(content=message_content)

        structured_llm = llm.with_structured_output(VisualAnalysis)

        response = await structured_llm.ainvoke([message], config=run_config)

        if not response:
            _logger.error("LLM failed to parse structured output.")
            return ""

        return response.model_dump_json(indent=2)

    except Exception as e:
        _logger.error("Error in create_enhanced_content: %s", e)
        return ""


async def agenerate_document_discovery_summary(
    text: str,
    run_config: RunnableConfig | None = None,
) -> dict:
    """Create fallback source-selection metadata when no abstract is available."""
    text = text.strip() if text else ""
    if not text:
        return {}

    try:
        llm = llm_client.get_llm()
        if llm is None:
            _logger.warning("No LLM available for document discovery summary.")
            return {}

        message = HumanMessage(
            content=(
                f"{prompts.document_discovery_prompt}\n\n" f"DOCUMENT CONTENT:\n{text}"
            )
        )
        structured_llm = llm.with_structured_output(DocumentDiscoveryAnalysis)
        response = await structured_llm.ainvoke([message], config=run_config)
        if not response:
            return {}

        summary = response.summary.strip()
        if not summary:
            return {}
        return {
            "source": "generated",
            "text": summary,
            "keywords": response.keywords,
        }
    except Exception as exc:
        _logger.warning("Could not generate document discovery summary: %s", exc)
        return {}
