import asyncio
import json
import logging
import os
import queue
import threading
import time
from functools import wraps

from flask import Flask, jsonify, render_template, request

from app.agent.manus import Manus
from app.config import config
from app.logger import logger
from app.schema import Message


# Disable werkzeug default access logs
werkzeug_logger = logging.getLogger("werkzeug")
werkzeug_logger.setLevel(logging.WARNING)  # Only show WARNING and higher level logs

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)

# Save the server configuration to the Flask application configuration when initialized
server_config = config.server_config
if server_config:
    app.config["HOST"] = server_config.get("host")
    app.config["PORT"] = server_config.get("port")

# Store Manus instances and message queues for each session
sessions = {}
message_queues = {}
message_counters = {}  # Store the number of messages processed for each session


def async_action(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))

    return wrapped


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/session", methods=["POST"])
def create_session():
    from app.config import config

    # Ensure using the latest configuration
    config.reload_config()

    session_id = os.urandom(16).hex()
    logger.info(f"Creating new session: {session_id}")

    sessions[session_id] = None  # Will be initialized on first request
    message_queues[session_id] = queue.Queue()
    message_counters[session_id] = 0

    logger.info(f"Session {session_id} created successfully")
    return jsonify({"session_id": session_id})


@app.route("/api/tools/<session_id>", methods=["GET"])
def get_available_tools(session_id):
    """Get available tools list for the current session"""
    from app.config import config

    if not session_id or session_id not in sessions:
        return jsonify({"error": "Invalid session ID"}), 400

    # Initialize Manus instance if this is the first request for this session
    if sessions[session_id] is None:
        # Ensure using the latest configuration
        config.reload_config()
        sessions[session_id] = Manus()

    agent = sessions[session_id]

    # Get list of tools available to the agent
    tools = []
    if hasattr(agent, "available_tools") and agent.available_tools:
        for tool in agent.available_tools:
            tool_info = {"name": tool.name, "description": tool.description}
            tools.append(tool_info)

    return jsonify({"tools": tools})


@app.route("/api/chat", methods=["POST"])
@async_action
async def chat():
    from app.config import config

    data = request.json
    logger.info(f"Received chat request: {data}")

    session_id = data.get("session_id")
    prompt = data.get("message")

    if not session_id:
        logger.warning("Missing session ID")
        return jsonify({"error": "Missing session ID"}), 400

    if session_id not in sessions:
        logger.warning(f"Invalid session ID: {session_id}")
        return jsonify({"error": f"Invalid session ID: {session_id}"}), 400

    if not prompt or not prompt.strip():
        logger.warning("Empty message content")
        return jsonify({"error": "Message content cannot be empty"}), 400

    # Initialize Manus instance if this is the first request for this session
    if sessions[session_id] is None:
        logger.info(f"Initializing Manus instance for session {session_id}")
        # Ensure using the latest configuration
        config.reload_config()
        sessions[session_id] = Manus()

    agent = sessions[session_id]
    message_queue = message_queues[session_id]

    # Process request in background
    def process_request():
        async def _run():
            try:
                # Create a task that can be cancelled
                logger.info(
                    f"Starting to process request for session {session_id}: {prompt[:50]}..."
                )
                task = asyncio.create_task(agent.run(prompt))

                # Check task status in a loop, allowing external interruption
                while not task.done():
                    # Check if session has been deleted/terminated
                    if (
                        session_id not in sessions
                        or agent.state == agent.state.__class__.FINISHED
                    ):
                        logger.info(
                            f"Session {session_id} has been terminated, cancelling task"
                        )
                        task.cancel()
                        # Wait a bit after cancelling to allow task to clean up resources
                        await asyncio.sleep(1.0)
                        break
                    await asyncio.sleep(0.1)

                # Wait for task to complete or be cancelled
                try:
                    if not task.done():
                        await asyncio.wait_for(task, timeout=3.0)
                except asyncio.CancelledError:
                    logger.info(f"Task has been cancelled")
                except asyncio.TimeoutError:
                    logger.warning(f"Timed out waiting for task to complete")

            except Exception as e:
                logger.error(f"Error processing request: {str(e)}", exc_info=True)
                message_queue.put({"error": str(e)})
            finally:
                # Mark task as complete
                try:
                    message_queue.put(None)
                except Exception as e:
                    logger.error(
                        f"Failed to send completion signal to message queue: {str(e)}"
                    )

        asyncio.run(_run())

    # Start background thread
    thread = threading.Thread(target=process_request)
    thread.daemon = True
    thread.start()

    return jsonify({"status": "processing", "session_id": session_id})


@app.route("/api/messages/<session_id>", methods=["GET"])
def get_messages(session_id):
    if session_id not in sessions or sessions[session_id] is None:
        return jsonify({"error": "Invalid session ID"}), 400

    agent = sessions[session_id]
    message_queue = message_queues[session_id]
    current_counter = message_counters[session_id]

    # Check for error messages
    error_messages = []
    while not message_queue.empty():
        msg = message_queue.get()
        if msg is None:  # Processing complete marker
            return jsonify({"messages": error_messages, "completed": True})
        error_messages.append(msg)

    # Return error messages immediately if any
    if error_messages:
        return jsonify({"messages": error_messages, "completed": False})

    # Get new messages from agent memory
    all_messages = agent.messages
    new_messages = []

    if len(all_messages) > current_counter:
        for i in range(current_counter, len(all_messages)):
            msg = all_messages[i]
            formatted_msg = _format_message(msg)
            if formatted_msg:
                new_messages.append(formatted_msg)

        # Update processed message count
        message_counters[session_id] = len(all_messages)

    completed = agent.state.value not in ["RUNNING", "THINKING", "ACTING"]

    return jsonify({"messages": new_messages, "completed": completed})


def _format_message(msg: Message) -> dict:
    """Convert Message object to a format usable by the frontend"""
    try:
        if not hasattr(msg, "role") or not hasattr(msg, "content"):
            return None

        # Get basic message info
        role = msg.role
        content = msg.content if hasattr(msg, "content") else ""

        # Create basic result object
        result = {"role": role, "content": content, "time": time.time()}

        # Check message type
        if hasattr(msg, "message_type"):
            # If backend explicitly marked message type
            message_type = msg.message_type
            if message_type == "thought":
                result["role"] = "assistant"
                if "name" in result:
                    del result["name"]
                return result
        else:
            # Backward compatible thought content detection
            thought_markers = [
                "✨ Manus's thoughts:",
                "Manus's thoughts:",
                "✨ Manus thinking:",
                "Manus thinking:",
            ]

            if (
                content
                and isinstance(content, str)
                and any(marker in content for marker in thought_markers)
            ):
                result["role"] = "assistant"
                if "name" in result:
                    del result["name"]
                return result

        # Add tool name (if present)
        if hasattr(msg, "name") and msg.name:
            try:
                result["name"] = msg.name
            except Exception:
                # Ignore if getting name attribute fails
                pass

        # Process additional attributes
        try:
            # Dynamically add all possible attributes of the message
            for attr_name in dir(msg):
                # Skip private attributes, methods, and already processed basic attributes
                if attr_name.startswith("_") or attr_name in [
                    "role",
                    "content",
                    "name",
                    "tool_calls",
                ]:
                    continue

                # Skip methods and complex objects that can't be serialized
                try:
                    attr_value = getattr(msg, attr_name)
                    if attr_value is None or callable(attr_value):
                        continue

                    # Try JSON serialization test, skip attributes that can't be serialized
                    json.dumps(attr_value)
                    result[attr_name] = attr_value
                except (TypeError, ValueError, json.JSONDecodeError):
                    # Skip attributes that can't be serialized
                    continue
        except Exception as e:
            logger.error(f"Error processing additional attributes: {str(e)}")
            # Continue processing other parts if error occurs

        # Special handling: screenshot information
        if hasattr(msg, "base64_image") and msg.base64_image:
            try:
                result["base64_image"] = msg.base64_image
                if role != "assistant":  # Maintain consistency of assistant role
                    result["role"] = "tool"
                    # Use a more dynamic way to set tool name
                    if not result.get("name"):
                        # Can get default name from config or specific attribute
                        try:
                            result["name"] = getattr(
                                msg, "tool_type", "Browser Screenshot"
                            )
                        except Exception:
                            result["name"] = "Browser Screenshot"
            except Exception as e:
                logger.error(f"Error processing screenshot information: {str(e)}")

        # Extract tool call information (if present)
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            try:
                tool_calls = []
                for call in msg.tool_calls:
                    # Dynamically build function info
                    if hasattr(call, "function") and call.function:
                        try:
                            func = call.function
                            function_info = {}

                            # Ensure at least basic properties exist
                            function_info["name"] = "unknown"
                            function_info["arguments"] = "{}"

                            # Safely set basic properties
                            if hasattr(func, "name"):
                                function_info["name"] = func.name
                            if hasattr(func, "arguments"):
                                function_info["arguments"] = func.arguments

                            # Create call info object
                            call_info = {"function": function_info}

                            # Add ID (if present)
                            if hasattr(call, "id"):
                                call_info["id"] = call.id

                            tool_calls.append(call_info)
                        except Exception as e:
                            logger.error(
                                f"Error processing individual tool call: {str(e)}"
                            )
                            continue

                if tool_calls:
                    result["tool_calls"] = tool_calls
                    # Only set role to tool if it's actually a tool call
                    if role != "assistant":
                        result["role"] = "tool"
            except Exception as e:
                logger.error(f"Error processing tool calls: {str(e)}")

        return result
    except Exception as e:
        logger.error(f"Message format conversion failed: {str(e)}", exc_info=True)
        # Return basic info to prevent frontend display issues
        return {
            "role": getattr(msg, "role", "unknown"),
            "content": getattr(msg, "content", "Message processing failed"),
            "time": time.time(),
            "error": f"Message processing error: {str(e)}",
        }


@app.route("/api/terminate/<session_id>", methods=["POST"])
@async_action
async def terminate_session(session_id):
    if session_id not in sessions:
        return jsonify({"error": "Invalid session ID"}), 400

    agent = sessions[session_id]
    if agent:
        try:
            # Call agent cleanup method
            await agent.cleanup()
            logger.info(f"Agent {session_id} resources cleaned up")

            # Force set agent state to finished
            agent.state = agent.state.__class__.FINISHED

            # Add forced termination of agent running tasks
            # Ensure all background tasks are terminated
            for task in asyncio.all_tasks():
                if not task.done() and session_id in str(task):
                    logger.info(
                        f"Forcibly cancelling tasks related to session {session_id}"
                    )
                    task.cancel()
        except Exception as e:
            logger.error(f"Error cleaning up agent {session_id}: {e}", exc_info=True)
            return jsonify({"error": f"Failed to clean up resources: {str(e)}"}), 500

    # Remove session
    try:
        del sessions[session_id]
        del message_queues[session_id]
        del message_counters[session_id]
        logger.info(f"Session {session_id} terminated")
    except Exception as e:
        logger.error(f"Error removing session {session_id}: {e}", exc_info=True)
        return jsonify({"error": f"Failed to remove session: {str(e)}"}), 500

    return jsonify({"status": "success", "message": "Session terminated"})


@app.route("/api/config", methods=["GET"])
def get_config():
    """Get current system configuration"""
    import tomllib
    from pathlib import Path

    from app.config import config

    # Read original configuration file
    config_path = Path(config.root_path) / "config" / "config.toml"
    with open(config_path, "rb") as f:
        raw_config = tomllib.load(f)

    # Ensure vision model configuration exists
    if "llm" in raw_config and "vision" not in raw_config["llm"]:
        # Add default vision model configuration
        raw_config["llm"]["vision"] = {
            "model": "claude-3-7-sonnet-20250219",
            "base_url": "https://api.anthropic.com/v1/",
            "api_key": "",
            "max_tokens": 8192,
            "temperature": 0.0,
        }

    # Return complete configuration, frontend can edit directly
    return jsonify({"config": raw_config})


@app.route("/api/config", methods=["POST"])
def update_config():
    """Update system configuration"""
    from pathlib import Path

    import tomli_w

    from app.config import config
    from app.logger import logger

    data = request.json
    new_config = data.get("config")

    if not new_config:
        return jsonify({"error": "Invalid configuration data"}), 400

    try:
        logger.info("Saving new configuration...")
        # Write new configuration to file
        config_path = Path(config.root_path) / "config" / "config.toml"
        with open(config_path, "wb") as f:
            tomli_w.dump(new_config, f)

        logger.info(
            "Configuration file has been successfully saved, reloading configuration..."
        )

        # Reload the configuration into memory
        reload_success = config.reload_config()

        if reload_success:
            logger.info(
                "Configuration has been successfully reloaded into the application"
            )

            # Check if server configuration has changed
            server_config_changed = False
            if "server" in new_config:
                old_host = app.config.get("HOST")
                old_port = app.config.get("PORT")
                new_host = new_config["server"].get("host")
                new_port = new_config["server"].get("port")

                if old_host != new_host or old_port != new_port:
                    server_config_changed = True
                    logger.warning(
                        f"Server configuration has changed (host:{old_host}->{new_host}, port:{old_port}->{new_port}), need to restart the service to take effect"
                    )
        else:
            logger.warning(
                "Configuration file has been saved, but failed to reload configuration"
            )

        # Return success message with detailed info
        return jsonify(
            {
                "status": "success",
                "message": "Configuration has been updated and reloaded",
                "reload_success": reload_success,
                "server_config_changed": (
                    server_config_changed
                    if "server_config_changed" in locals()
                    else False
                ),
            }
        )
    except Exception as e:
        logger.error(f"Error saving configuration: {str(e)}", exc_info=True)
        return jsonify({"error": f"Failed to save configuration: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True)
