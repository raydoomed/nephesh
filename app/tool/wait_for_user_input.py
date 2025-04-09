from typing import Optional

from app.schema import AgentState
from app.tool.base import BaseTool


_WAIT_FOR_USER_INPUT_DESCRIPTION = """
This tool is used when you need to wait for user input or feedback.
After calling this tool, the agent will pause execution until the user provides new input.
Applicable scenarios: when user confirmation, selection, or additional information is required to continue the task.
"""


class WaitForUserInput(BaseTool):
    name: str = "wait_for_user_input"
    description: str = _WAIT_FOR_USER_INPUT_DESCRIPTION
    parameters: dict = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The message to display to the user, explaining what information or choices they need to provide.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of options, if provided, will be displayed to the user for selection.",
            },
        },
        "required": ["message"],
    }

    async def execute(self, message: str, options: Optional[list[str]] = None) -> str:
        """Pause current execution and wait for user input"""
        # Access the agent instance that called this tool (if any)
        agent = getattr(self, "_agent", None)

        # If there is an agent instance, set its state to WAITING_FOR_INPUT
        if agent and hasattr(agent, "state"):
            # Set state to WAITING_FOR_USER_INPUT
            agent.state = AgentState.WAITING_FOR_USER_INPUT
            # Ensure that cleanup is not triggered
            agent._should_cleanup = False

        # Build the response message
        response = "Waiting for user input: " + message

        # If options are provided, add them to the response message
        if options and isinstance(options, list) and len(options) > 0:
            options_str = "\n".join([f"- {option}" for option in options])
            response += f"\n\nOptional options:\n{options_str}"

        return response
