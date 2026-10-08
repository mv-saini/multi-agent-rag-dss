from utils import llm_client
from langchain_core.messages import HumanMessage
from models.core import EnhancedDocumentAnalysis, DocumentTitleOutput
import logging
import config
import prompts

_logger = logging.getLogger(__name__)


async def agenerate_summaries(
    text: str,
    images: list[str],
):
    """
    Creates an enhanced summary asynchronously using an LLM that combines text and images.
    Returns a JSON formatted string of the structured analysis.
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
            prompt_text += f"TEXT CONTENT:\n{text}\n\n"

        message_content = [{"type": "text", "text": prompt_text}]

        if images:
            for image_base64 in images:
                message_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                    }
                )

        message = HumanMessage(content=message_content)

        structured_llm = llm.with_structured_output(EnhancedDocumentAnalysis)

        response = await structured_llm.ainvoke([message], config=config.llm_config)

        if not response:
            _logger.error("LLM failed to parse structured output.")
            return ""

        return response.model_dump_json(indent=2)

    except Exception as e:
        _logger.error("Error in create_enhanced_content: %s", e)
        return ""


def get_inferred_doc_title(doc_index: dict):
    try:
        llm = llm_client.get_llm()

        if llm is None:
            _logger.warning("LLM not available for title inference. Returning 'N/A'.")
            return "N/A"

        content = (
            "You are given a list of document titles extracted from a PDF. "
            "The PDF may have multiple sections, each with its own title. "
            "Your task is to infer the most likely overall document title based on these section titles.\n\n"
        )

        for idx, info in doc_index.items():
            content += f"{idx}. {info['title']}\n"

        structured_llm = llm.with_structured_output(DocumentTitleOutput)

        response: DocumentTitleOutput = structured_llm.invoke(
            input=content, config=config.llm_config
        )
        return response.title
    except Exception as e:
        _logger.error(f"Error during title inference: {e}")
        return "N/A"
