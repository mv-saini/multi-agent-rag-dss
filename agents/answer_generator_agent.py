from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from utils import llm_client
from langchain_core.runnables import RunnableConfig
import datetime
from starlette.concurrency import run_in_threadpool
import prompts
from utils import helpers
from core.indexing.image_assets import meaningful_image_refs, multimodal_message_content
from utils.citations import (
    CITATION_DELIMITER,
    CITATION_START,
    CITATION_STOP,
    build_citable_context,
    parse_citations,
)
import config


def _message_text(message) -> str:
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


def _prepare_context(retrieved_context: dict):
    current_date_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    vector_docs = retrieved_context.get("vector_docs", [])
    citable_context = build_citable_context(retrieved_context)
    context_prompt_text = (
        f"Current Date and Time: {current_date_time}\n\n" f"{citable_context.prompt}"
    )

    image_refs = []
    for chunk in vector_docs:
        image_refs.extend(chunk.metadata.get("image_refs", []))
    image_refs = list(dict.fromkeys(meaningful_image_refs(image_refs)))[
        : getattr(config, "MAX_RAG_IMAGES", 12)
    ]
    message_content = multimodal_message_content(context_prompt_text, image_refs)

    return citable_context, message_content


async def run(state: dict, run_config: RunnableConfig = None):
    """
    Generates an answer to the user's query based on the reranked documents.
    """

    try:
        messages = state.get("messages", [])
        retrieved_context = state.get("retrieved_context", {})
        user_profile = state.get("user_profile", {})

        if not messages:
            return AIMessage(
                content="Sorry, I couldn't find any information to answer your query."
            )

        llm = llm_client.get_llm()
        if llm is None:
            raise Exception("No LLM available for answer generation.")

        citable_context, message_content = await run_in_threadpool(
            _prepare_context, retrieved_context
        )

        citation_example = (
            f"{CITATION_START}cite{CITATION_DELIMITER}document_example"
            f"{CITATION_STOP}"
        )
        input_messages = [
            # main prompt
            SystemMessage(
                content=(
                    f"{prompts.answer_prompt}\n\n"
                    f"Actual citation-marker example: {citation_example}"
                )
            )
        ]

        # previous messages and feedback
        for message in messages:
            input_messages.append(message)
            if not isinstance(message, HumanMessage):
                continue
            feedback = message.additional_kwargs.get("feedback", [])
            if feedback:
                clarification_text = "\n\n".join(
                    f"Question: {item.get('question', '')}\n"
                    f"User answer: {item.get('answer', '')}"
                    for item in feedback
                )
                input_messages.append(
                    HumanMessage(
                        content=(
                            "### USER CLARIFICATIONS AND PLAN FEEDBACK\n"
                            "For the preceding user request, in chronological order:\n\n"
                            f"{clarification_text}"
                        )
                    )
                )

        # user profile
        if user_profile:
            user_profile_prompt = (
                f"### USER PROFILE\n{helpers.json_to_markdown(user_profile)}"
            )
            user_profile_message = HumanMessage(content=user_profile_prompt)
            input_messages.append(user_profile_message)

        # context prompt
        input_messages.append(HumanMessage(content=message_content))

        await adispatch_custom_event(
            "reasoning_header", "Generating answer...", config=run_config
        )

        response = await llm.ainvoke(input=input_messages, config=run_config)
        parsed = await run_in_threadpool(
            parse_citations, _message_text(response), citable_context.sources
        )
        additional_kwargs = dict(getattr(response, "additional_kwargs", {}) or {})
        additional_kwargs["citation_sources"] = parsed.sources

        return AIMessage(
            content=parsed.text,
            id=getattr(response, "id", None),
            additional_kwargs=additional_kwargs,
            response_metadata=dict(getattr(response, "response_metadata", {}) or {}),
        )
    except Exception:
        return AIMessage(
            content="Sorry, I encountered an error while generating the answer."
        )
