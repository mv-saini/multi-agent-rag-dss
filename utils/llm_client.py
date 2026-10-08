import config
import logging
from langchain_openai import ChatOpenAI

_logger = logging.getLogger(__name__)


def get_llm():
    try:
        if config.OPEN_AI:
            llm = ChatOpenAI(
                model=config.OPEN_AI_MODEL,
                use_responses_api=True,
                reasoning_effort="medium",
                max_retries=3,
            )
            return llm
        # Add other LLMs here as needed
    except Exception as e:
        _logger.error(f"Error initializing LLM: {e}")
