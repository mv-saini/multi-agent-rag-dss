import logging

_logger = logging.getLogger(__name__)


def extract_last_tool_call_args(response, tool_name):
    """Utility function to extract the arguments of the last call to a specific tool from an agent's response."""
    try:
        messages = response.get("messages", [])
        for msg in reversed(messages):
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.get('name') == tool_name:
                        return tc.get('args', {})
    except Exception as e:
        _logger.error(
            f"Failed to extract tool call arguments for {tool_name}. Error: {e}")
    return {}
