from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import HumanMessage, SystemMessage
from utils import llm_client
from langchain_core.runnables import RunnableConfig
import datetime
import prompts
from utils import helpers


async def run(state: dict, run_config: RunnableConfig = None):
    """
    Generates an answer to the user's query based on the reranked documents.
    """

    try:
        messages = state.get("messages", [])
        retrieved_context = state.get("retrieved_context", {})
        user_profile = state.get("user_profile", {})

        if not messages:
            return "Sorry, I couldn't find any information to answer your query."

        llm = llm_client.get_llm()
        if llm is None:
            raise Exception("No LLM available for answer generation.")

        current_date_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        context_prompt_text = f"""
Current Date and Time: {current_date_time}
SPATIAL ANALYSIS SUMMARY
"""

        vector_docs = retrieved_context.get("vector_docs", [])
        web_results = retrieved_context.get("web_results", [])
        spatial_analysis = retrieved_context.get("spatial_analysis", [])

        if spatial_analysis:
            context_prompt_text += helpers.format_spatial_analysis(spatial_analysis)
            context_prompt_text += "\n\n"
        else:
            context_prompt_text += "No spatial analysis results were found.\n\n"

        context_prompt_text += "RETRIEVED DOCUMENT EVIDENCE\n"
        if vector_docs:
            context_prompt_text += helpers.format_vector_docs(vector_docs)
            context_prompt_text += "\n\n"
        else:
            context_prompt_text += "No document evidence was found.\n\n"

        context_prompt_text += "RETRIEVED WEB RESULTS\n"
        if web_results:
            context_prompt_text += helpers.format_web_results(
                web_results, offset=len(vector_docs)
            )
            context_prompt_text += "\n\n"
        else:
            context_prompt_text += "No web results were found.\n\n"

        message_content = [{"type": "text", "text": context_prompt_text}]
        for chunk in retrieved_context.get("vector_docs", []):
            images_base64 = chunk.metadata.get("images_base64", [])
            for image_base64 in images_base64:
                message_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                    }
                )

        # main prompt
        input_messages = [SystemMessage(content=prompts.answer_prompt)]

        # user profile
        if user_profile:
            user_profile_prompt = (
                f"### USER PROFILE\n{helpers.json_to_markdown(user_profile)}"
            )
            user_profile_message = HumanMessage(content=user_profile_prompt)
            input_messages.append(user_profile_message)

        # context prompt
        input_messages.append(HumanMessage(content=message_content))

        # previous messages
        input_messages.extend(messages)

        await adispatch_custom_event(
            "reasoning_header", "Generating answer...", config=run_config
        )

        response = await llm.ainvoke(input=input_messages, config=run_config)

        return response
    except Exception as e:
        return "Sorry, I encountered an error while generating the answer."
