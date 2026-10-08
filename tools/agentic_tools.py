from langchain_core.tools import tool


@tool(return_direct=True)
async def ask_human_feedback(request_feedback: str):
    """If you cannot proceed or requires clarification, provide the question here for the user."""
    return {"request_feedback": request_feedback}
