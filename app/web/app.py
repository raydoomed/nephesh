import asyncio
import datetime
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
# Store session history with timestamp, user input and full message history
session_history = {}  # To store historical session data

# Create history directory if not exists
HISTORY_DIR = os.path.join(str(config.workspace_root), "history")
if not os.path.exists(HISTORY_DIR):
    os.makedirs(HISTORY_DIR)


# Load history data
def load_history_data():
    global session_history
    if os.path.exists(HISTORY_DIR):
        for filename in os.listdir(HISTORY_DIR):
            if filename.endswith(".json"):
                session_id = filename[:-5]  # Remove .json suffix
                try:
                    with open(
                        os.path.join(HISTORY_DIR, filename), "r", encoding="utf-8"
                    ) as f:
                        session_data = json.load(f)

                        # Filter out history records with no actual content
                        if (
                            not session_data.get("prompts")
                            or len(session_data.get("prompts", [])) == 0
                        ) and (
                            not session_data.get("messages")
                            or len(session_data.get("messages", [])) == 0
                        ):
                            # Delete history files with no actual content
                            try:
                                os.remove(os.path.join(HISTORY_DIR, filename))
                                logger.info(f"Deleted empty history file: {filename}")
                                continue
                            except Exception as e:
                                logger.error(
                                    f"Unable to delete empty history file {filename}: {str(e)}"
                                )

                        session_history[session_id] = session_data
                except Exception as e:
                    logger.error(f"Unable to load history file {filename}: {str(e)}")
    logger.info(f"Loaded {len(session_history)} history records")


# Save history to file
def save_history(session_id):
    if session_id in session_history:
        try:
            history_file = os.path.join(HISTORY_DIR, f"{session_id}.json")
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(session_history[session_id], f, ensure_ascii=False, indent=2)
            logger.info(f"Session history saved: {session_id}")
        except Exception as e:
            logger.error(f"Failed to save history {session_id}: {str(e)}")


# Load existing history data
load_history_data()


# Periodic cleanup of empty session records
def cleanup_empty_sessions():
    """Clean up empty session records in memory"""
    global session_history
    try:
        sessions_to_remove = []
        # Look for empty sessions
        for session_id, data in session_history.items():
            # Check if it's a newly created empty session
            if "is_new" in data:
                # Only clean up inactive sessions
                if session_id not in sessions or sessions[session_id] is None:
                    sessions_to_remove.append(session_id)
                    continue

            # Check if the session has actual message content
            if (not data.get("prompts") or len(data.get("prompts", [])) == 0) and (
                not data.get("messages") or len(data.get("messages", [])) == 0
            ):
                # Only clean up inactive sessions
                if session_id not in sessions or sessions[session_id] is None:
                    sessions_to_remove.append(session_id)

        # Delete empty sessions
        for session_id in sessions_to_remove:
            if session_id in session_history:
                del session_history[session_id]
                logger.info(
                    f"Periodic cleanup: Removed empty session from memory: {session_id}"
                )

                # Delete corresponding files
                try:
                    history_file = os.path.join(HISTORY_DIR, f"{session_id}.json")
                    if os.path.exists(history_file):
                        os.remove(history_file)
                        logger.info(
                            f"Periodic cleanup: Deleted empty session history file: {session_id}"
                        )
                except Exception as e:
                    logger.error(
                        f"Periodic cleanup: Failed to delete empty session history file {session_id}: {str(e)}"
                    )
    except Exception as e:
        logger.error(
            f"Error during periodic cleanup of empty sessions: {str(e)}", exc_info=True
        )


# Start cleanup thread
def start_cleanup_thread():
    """Start background thread for periodic cleanup of empty sessions"""

    def cleanup_worker():
        while True:
            try:
                # Clean up every 5 minutes
                time.sleep(300)
                cleanup_empty_sessions()
            except Exception as e:
                logger.error(f"Cleanup thread error: {str(e)}", exc_info=True)
                # Continue running even if error occurs
                time.sleep(60)

    thread = threading.Thread(target=cleanup_worker)
    thread.daemon = (
        True  # Set as daemon thread, automatically terminate when main program exits
    )
    thread.start()
    logger.info("Empty session cleanup thread started")


# Start cleanup thread
start_cleanup_thread()


def async_action(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))

    return wrapped


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat")
def chat_page():
    return render_template("chat.html")


@app.route("/history")
def history_page():
    """Display the history page with all session records"""
    return render_template("history.html")


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

    # Initialize session history in memory only, don't save to file yet
    session_history[session_id] = {
        "session_id": session_id,
        "created_at": datetime.datetime.now().isoformat(),
        "prompts": [],
        "messages": [],
        "is_new": True,  # Mark as new session
    }
    # Only save history when there are actual messages

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
            # Ensure all tools are included, including special tools
            tool_info = {"name": tool.name, "description": tool.description}
            # Mark special tools
            if (
                hasattr(agent, "special_tool_names")
                and tool.name in agent.special_tool_names
            ):
                tool_info["is_special"] = True
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

        # Initialize history record for this session if not exists
        if session_id not in session_history:
            session_history[session_id] = {
                "session_id": session_id,
                "created_at": datetime.datetime.now().isoformat(),
                "prompts": [],
                "messages": [],
                "is_new": True,  # Mark as new session
            }
            # Don't save empty history record immediately

    # Add prompt to history
    if session_id in session_history:
        # If this is the first message, remove is_new flag
        if "is_new" in session_history[session_id]:
            del session_history[session_id]["is_new"]
            logger.info(
                f"Session {session_id} received first message, removing new session flag"
            )

        # Add user prompt to history
        current_time = datetime.datetime.now().isoformat()
        session_history[session_id]["prompts"].append(
            {"time": current_time, "content": prompt}
        )

        # Add user message to message history
        user_message = {"role": "user", "content": prompt, "time": time.time()}
        session_history[session_id]["messages"].append(user_message)

        # Save history - now only when there are actual messages
        save_history(session_id)
        logger.info(f"User message saved to history: {session_id}")

    agent = sessions[session_id]
    message_queue = message_queues[session_id]

    # 检查智能体是否处于等待用户输入状态
    # 如果是，则恢复执行，而不是创建新的执行线程
    was_waiting = False
    if agent.state == agent.state.__class__.WAITING_FOR_USER_INPUT:
        logger.info(
            f"Agent was waiting for user input in session {session_id}, resuming execution"
        )
        agent.state = agent.state.__class__.RUNNING
        was_waiting = True

    # Process request in background
    def process_request():
        async def _run():
            try:
                # Create a task that can be cancelled
                logger.info(
                    f"Starting to process request for session {session_id}: {prompt[:50]}..."
                )

                # 如果智能体之前在等待用户输入，则将用户的回复添加到内存中，但不启动新的run
                if was_waiting:
                    # 添加用户的回复作为消息
                    agent.update_memory("user", prompt)
                    # 继续执行下一步
                    task = asyncio.create_task(agent.step())
                else:
                    # 正常启动新的运行流程
                    task = asyncio.create_task(agent.run(prompt))

                # Check task status in a loop, allowing external interruption
                while not task.done():
                    # Check if session has been deleted/terminated
                    if (
                        session_id not in sessions
                        or agent.state == agent.state.__class__.FINISHED
                        or agent.state == agent.state.__class__.WAITING_FOR_USER_INPUT
                    ):
                        # 如果agent在等待用户输入，不要取消任务
                        if agent.state == agent.state.__class__.WAITING_FOR_USER_INPUT:
                            logger.info(
                                f"Agent is waiting for user input in session {session_id}"
                            )
                            # 让任务正常完成
                            # await asyncio.wait_for(task, timeout=3.0)
                            break
                        else:
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
                # 只有当智能体不处于等待状态时才发送完成信号
                if agent.state != agent.state.__class__.WAITING_FOR_USER_INPUT:
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


@app.route("/api/history", methods=["GET"])
def get_history():
    """Get list of all historical sessions"""
    history_list = []

    # First clean up empty session records in memory
    sessions_to_remove = []
    for session_id, data in session_history.items():
        # Check if it's a newly created empty session
        if "is_new" in data:
            # Mark sessions with no actual content for later deletion
            if session_id not in sessions or sessions[session_id] is None:
                # If there's no active session instance, it's safe to delete
                sessions_to_remove.append(session_id)
                continue

        # Check if the session has actual message content
        if (not data.get("prompts") or len(data.get("prompts", [])) == 0) and (
            not data.get("messages") or len(data.get("messages", [])) == 0
        ):
            # Mark sessions with no actual content for later deletion
            if session_id not in sessions or sessions[session_id] is None:
                # If there's no active session instance, it's safe to delete
                sessions_to_remove.append(session_id)

    # Remove empty sessions from memory
    for session_id in sessions_to_remove:
        if session_id in session_history:
            del session_history[session_id]
            logger.info(f"Removed empty session from memory: {session_id}")

            # Delete corresponding file (if exists)
            try:
                history_file = os.path.join(HISTORY_DIR, f"{session_id}.json")
                if os.path.exists(history_file):
                    os.remove(history_file)
                    logger.info(f"Deleted empty session history file: {session_id}")
            except Exception as e:
                logger.error(
                    f"Failed to delete empty session history file {session_id}: {str(e)}"
                )

    # Collect valid history records
    for session_id, data in session_history.items():
        # Ensure all necessary fields exist
        if not isinstance(data, dict):
            logger.warning(f"Invalid session history format: {session_id}")
            continue

        # Skip sessions with is_new flag
        if "is_new" in data:
            continue

        # Double check if the session has actual message content
        if (not data.get("prompts") or len(data.get("prompts", [])) == 0) and (
            not data.get("messages") or len(data.get("messages", [])) == 0
        ):
            # Skip sessions with no actual content
            continue

        # Get first prompt or show default message
        first_prompt = "No prompt content"
        if (
            "prompts" in data
            and isinstance(data["prompts"], list)
            and len(data["prompts"]) > 0
        ):
            prompt_data = data["prompts"][0]
            if isinstance(prompt_data, dict) and "content" in prompt_data:
                first_prompt = prompt_data["content"]

        # Create session summary
        session_summary = {
            "session_id": session_id,
            "created_at": data.get("created_at", "Unknown time"),
            "first_prompt": first_prompt,
            "prompt_count": len(data.get("prompts", [])),
            "completed": "completed_at" in data,
        }

        history_list.append(session_summary)

    # Sort by creation time (newest first)
    history_list.sort(key=lambda x: x["created_at"], reverse=True)

    return jsonify({"history": history_list})


@app.route("/api/history/<session_id>", methods=["GET"])
def get_session_history(session_id):
    """Get detailed history for a specific session"""
    if session_id not in session_history:
        return jsonify({"error": "Session history not found"}), 404

    # Return complete session history data
    session_data = session_history[session_id]

    # Ensure session ID exists in the data
    if isinstance(session_data, dict) and "session_id" not in session_data:
        session_data["session_id"] = session_id

    return jsonify(session_data)


@app.route("/api/history/<session_id>", methods=["DELETE"])
def delete_session_history(session_id):
    """Delete a specific session history"""
    if session_id not in session_history:
        return jsonify({"error": "Session history not found"}), 404

    try:
        # Delete from memory
        del session_history[session_id]

        # Delete the corresponding file
        history_file = os.path.join(HISTORY_DIR, f"{session_id}.json")
        if os.path.exists(history_file):
            os.remove(history_file)
            logger.info(f"Deleted session history file: {session_id}")

        return jsonify(
            {"success": True, "message": "Session history deleted successfully"}
        )
    except Exception as e:
        logger.error(f"Failed to delete session history {session_id}: {str(e)}")
        return jsonify({"error": f"Failed to delete session history: {str(e)}"}), 500


@app.route("/api/history", methods=["DELETE"])
def clear_all_history():
    """Clear all history records"""
    try:
        # Clear memory
        session_history.clear()

        # Delete all history files
        if os.path.exists(HISTORY_DIR):
            for filename in os.listdir(HISTORY_DIR):
                if filename.endswith(".json"):
                    try:
                        os.remove(os.path.join(HISTORY_DIR, filename))
                        logger.info(f"Deleted history file: {filename}")
                    except Exception as e:
                        logger.error(
                            f"Failed to delete history file {filename}: {str(e)}"
                        )

        return jsonify(
            {"success": True, "message": "All history records cleared successfully"}
        )
    except Exception as e:
        logger.error(f"Failed to clear history records: {str(e)}")
        return jsonify({"error": f"Failed to clear history records: {str(e)}"}), 500


@app.route("/api/messages/<session_id>", methods=["GET"])
def get_messages(session_id):
    """Get messages from an active session with SSE streaming"""
    if session_id not in sessions:
        return jsonify({"error": "Invalid session ID"}), 400

    agent = sessions[session_id]
    if agent is None:
        # Empty session record, no agent yet
        logger.warning(f"Empty agent session record, no messages: {session_id}")
        return jsonify({"messages": [], "completed": True})

    # Get all new messages from the agent queue
    message_queue = message_queues[session_id]
    message_counter = message_counters[session_id]

    # Initialize variables
    completed = False
    new_messages = []

    # Process messages in the queue (errors or completion markers)
    queue_messages = []
    while not message_queue.empty():
        msg = message_queue.get()
        if msg is None:  # Handle completion marker
            completed = True
            break
        queue_messages.append(msg)
        new_messages.append(msg)

    # Save queue messages to history
    if queue_messages and session_id in session_history:
        for msg in queue_messages:
            # Check if message already exists
            if not any(
                m.get("content") == msg.get("content")
                and m.get("role") == msg.get("role")
                for m in session_history[session_id]["messages"]
            ):
                session_history[session_id]["messages"].append(msg)
        save_history(session_id)
        logger.info(f"Saved {len(queue_messages)} queue messages to history")

    # If there are queue messages, return them immediately
    if new_messages:
        return jsonify({"messages": new_messages, "completed": completed})

    # Add a shortcut to return completed flag if no messages are available
    # and agent state is finished or agent is waiting for user input
    if message_queue.empty() and (
        agent.state == agent.state.__class__.FINISHED
        or agent.state == agent.state.__class__.WAITING_FOR_USER_INPUT
    ):
        logger.info(f"Agent state: {agent.state}. No new messages.")

        # Get all messages so the frontend can update
        agent_messages = []

        try:
            agent_messages = agent.memory.messages
        except Exception as e:
            logger.error(f"Failed to access agent messages: {str(e)}")

        # Format messages for frontend use
        formatted_msgs = []
        for msg in agent_messages:
            if hasattr(msg, "role"):  # Ensure message has required attributes
                formatted_msg = _format_message(msg)
                if formatted_msg:
                    formatted_msgs.append(formatted_msg)

        # Ensure messages are sorted by time
        formatted_msgs.sort(key=lambda m: m.get("time", 0))

        # Return only the messages that haven't been counted yet
        new_messages = formatted_msgs[message_counter:]

        # Update counter
        message_counters[session_id] = len(formatted_msgs)

        # Add messages to session history
        if session_id in session_history and new_messages:
            for msg in new_messages:
                msg_copy = msg.copy()
                if "time" in msg_copy:
                    # Ensure timestamp is ISO formatted string
                    msg_copy["time"] = datetime.datetime.fromtimestamp(
                        msg_copy["time"]
                    ).isoformat()
                session_history[session_id]["messages"].append(msg_copy)

            # Save session history
            save_history(session_id)

        # If agent is in waiting for user input state, return special status
        if agent.state == agent.state.__class__.WAITING_FOR_USER_INPUT:
            return jsonify(
                {
                    "messages": new_messages,
                    "completed": False,
                    "waiting_for_input": True,
                }
            )
        else:
            return jsonify(
                {
                    "messages": new_messages,
                    "completed": agent.state == agent.state.__class__.FINISHED,
                }
            )

    # Get new messages from agent
    agent_messages = []
    if len(agent.messages) > message_counter:
        for i in range(message_counter, len(agent.messages)):
            msg = agent.messages[i]
            formatted_msg = _format_message(msg)
            if formatted_msg:
                agent_messages.append(formatted_msg)
                new_messages.append(formatted_msg)

        # Update message counter
        message_counters[session_id] = len(agent.messages)

    # Save agent messages to history
    if agent_messages and session_id in session_history:
        for msg in agent_messages:
            # Check if message already exists
            if not any(
                m.get("content") == msg.get("content")
                and m.get("role") == msg.get("role")
                for m in session_history[session_id]["messages"]
            ):
                session_history[session_id]["messages"].append(msg)
        save_history(session_id)
        logger.info(f"Saved {len(agent_messages)} agent messages to history")

    # Check if completed - only consider tasks complete if agent is not in an active state
    # AND the agent has either performed its final step OR been terminated
    if not completed:
        is_inactive = agent.state.value not in ["RUNNING", "THINKING", "ACTING"]
        is_finished = (
            (agent.current_step >= agent.max_steps)
            or hasattr(agent, "terminated")
            and agent.terminated
        )
        completed = is_inactive and is_finished

    # If task is completed, ensure completion status is saved
    if (
        completed
        and session_id in session_history
        and "completed_at" not in session_history[session_id]
    ):
        session_history[session_id][
            "completed_at"
        ] = datetime.datetime.now().isoformat()
        save_history(session_id)
        logger.info(f"Task completed, saved session completion time: {session_id}")

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
    success = True  # Mark if termination is successful

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
            success = False  # Mark termination as failed
            return jsonify({"error": f"Failed to clean up resources: {str(e)}"}), 500

    # Finalize history record when session is terminated
    try:
        if session_id in session_history:
            # Check if session has actual content
            session_data = session_history[session_id]
            has_content = (
                session_data.get("prompts") and len(session_data.get("prompts", [])) > 0
            ) or (
                session_data.get("messages")
                and len(session_data.get("messages", [])) > 0
            )

            if has_content:
                # Only save termination record for sessions with actual content
                logger.info(f"Saving history for session {session_id}")
                session_history[session_id][
                    "completed_at"
                ] = datetime.datetime.now().isoformat()
                # Ensure save operation is performed
                save_history(session_id)
                logger.info(f"History for session {session_id} has been saved")
            else:
                # For empty sessions, remove directly from history
                logger.info(
                    f"Session {session_id} has no actual content, removing from history"
                )
                if session_id in session_history:
                    del session_history[session_id]

                # Delete corresponding file (if exists)
                try:
                    history_file = os.path.join(HISTORY_DIR, f"{session_id}.json")
                    if os.path.exists(history_file):
                        os.remove(history_file)
                        logger.info(f"Deleted empty session history file: {session_id}")
                except Exception as e:
                    logger.error(
                        f"Failed to delete empty session history file {session_id}: {str(e)}"
                    )
    except Exception as e:
        logger.error(
            f"Error saving history for terminated session: {str(e)}", exc_info=True
        )

    # Add terminate tool message to message queue
    try:
        if session_id in message_queues:
            status_message = "success" if success else "failed"
            terminate_message = Message(
                role="tool",
                name="terminate",
                content=f"Observed output of cmd terminate executed: The interaction has been completed with status: {status_message}",
            )
            formatted_msg = _format_message(terminate_message)
            message_queues[session_id].put(formatted_msg)

            # Also add termination message to history record - only if there is actual content
            if session_id in session_history and formatted_msg:
                # Check again if session has actual content
                session_data = session_history[session_id]
                has_content = (
                    session_data.get("prompts")
                    and len(session_data.get("prompts", [])) > 0
                ) or (
                    session_data.get("messages")
                    and len(session_data.get("messages", [])) > 0
                )

                if has_content:
                    session_history[session_id]["messages"].append(formatted_msg)
                    save_history(session_id)
    except Exception as e:
        logger.error(f"Error adding terminate message to queue: {e}", exc_info=True)

    # Remove session
    try:
        # Delay session deletion to ensure terminate message can be received by frontend
        import threading

        def delayed_session_cleanup():
            try:
                time.sleep(
                    5
                )  # Wait 5 seconds to ensure frontend receives terminate message
                if session_id in sessions:
                    del sessions[session_id]
                if session_id in message_queues:
                    del message_queues[session_id]
                if session_id in message_counters:
                    del message_counters[session_id]
                logger.info(f"Session {session_id} terminated (delayed cleanup)")
            except Exception as e:
                logger.error(
                    f"Error in delayed cleanup for session {session_id}: {e}",
                    exc_info=True,
                )

        # Start delayed cleanup thread
        cleanup_thread = threading.Thread(target=delayed_session_cleanup)
        cleanup_thread.daemon = True
        cleanup_thread.start()

        logger.info(f"Session {session_id} termination initiated")
    except Exception as e:
        logger.error(
            f"Error setting up delayed cleanup for session {session_id}: {e}",
            exc_info=True,
        )
        success = False
        return jsonify({"error": f"Failed to initiate session cleanup: {str(e)}"}), 500

    return jsonify({"status": "success", "message": "Session terminated"})


@app.route("/api/status/<session_id>", methods=["GET"])
def get_agent_status(session_id):
    """Get current status of an agent, including step progress"""
    if session_id not in sessions:
        return jsonify({"error": "Invalid session ID"}), 400

    agent = sessions[session_id]
    if agent is None:
        return jsonify({"error": "Agent not initialized"}), 404

    # Return the current status information
    return jsonify(
        {
            "status": agent.state.value,
            "current_step": agent.current_step,
            "max_steps": agent.max_steps,
            "session_id": session_id,
        }
    )


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


@app.route("/api/files", methods=["GET"])
def list_workspace_files():
    """Get a list of files in the workspace directory."""
    try:
        workspace_root = config.workspace_root
        files = []

        for item in workspace_root.iterdir():
            if item.is_file():
                files.append(
                    {
                        "name": item.name,
                        "path": str(item.relative_to(workspace_root)),
                        "size": item.stat().st_size,
                        "modified": item.stat().st_mtime,
                    }
                )

        return jsonify({"files": files})
    except Exception as e:
        logger.error(f"Error listing workspace files: {str(e)}", exc_info=True)
        return jsonify({"error": f"Failed to list workspace files: {str(e)}"}), 500


@app.route("/api/files/<path:file_path>", methods=["GET"])
def download_workspace_file(file_path):
    """Download a file from the workspace directory."""
    from flask import send_file

    try:
        workspace_root = config.workspace_root
        # Ensure the file path is secure
        file_path = os.path.normpath(file_path).lstrip("/")
        full_path = workspace_root / file_path

        if not full_path.exists():
            return jsonify({"error": "File not found"}), 404

        if not full_path.is_file():
            return jsonify({"error": "Not a file"}), 400

        # Send the file as an attachment
        return send_file(
            full_path, as_attachment=True, download_name=os.path.basename(file_path)
        )
    except Exception as e:
        logger.error(f"Error downloading file {file_path}: {str(e)}", exc_info=True)
        return jsonify({"error": f"Failed to download file: {str(e)}"}), 500


@app.route("/api/files/<path:file_path>", methods=["DELETE"])
def delete_workspace_file(file_path):
    """Delete a file from the workspace directory."""
    try:
        workspace_root = config.workspace_root
        # Ensure the file path is secure
        file_path = os.path.normpath(file_path).lstrip("/")
        full_path = workspace_root / file_path

        if not full_path.exists():
            return jsonify({"error": "File not found"}), 404

        if not full_path.is_file():
            return jsonify({"error": "Not a file"}), 400

        # Delete the file
        os.remove(full_path)
        return jsonify({"message": "File deleted successfully"})
    except Exception as e:
        logger.error(f"Error deleting file {file_path}: {str(e)}", exc_info=True)
        return jsonify({"error": f"Failed to delete file: {str(e)}"}), 500


@app.route("/api/files", methods=["POST"])
def upload_workspace_file():
    """Upload a file to the workspace directory."""
    try:
        workspace_root = config.workspace_root

        if "file" not in request.files:
            return jsonify({"error": "No file part in the request"}), 400

        file = request.files["file"]

        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        # Ensure filename is secure
        filename = os.path.basename(file.filename)
        file_path = workspace_root / filename

        # Save file
        file.save(file_path)

        # Return file information
        file_info = {
            "name": filename,
            "path": filename,
            "size": os.path.getsize(file_path),
            "modified": os.path.getmtime(file_path),
        }

        return jsonify({"file": file_info, "message": "File uploaded successfully"})
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}", exc_info=True)
        return jsonify({"error": f"Failed to upload file: {str(e)}"}), 500


@app.route("/api/history/<session_id>/export/<format>", methods=["GET"])
def export_session(session_id, format):
    """Export session record in specified format"""
    if session_id not in session_history:
        return jsonify({"error": "Session record not found"}), 404

    session_data = session_history[session_id]

    # Choose export method based on format
    if format == "json":
        response = jsonify(session_data)
        response.headers[
            "Content-Disposition"
        ] = f"attachment; filename=session-{session_id[:8]}.json"
        return response

    elif format == "txt":
        content = generate_text_export(session_data)
        return (
            content,
            200,
            {
                "Content-Type": "text/plain; charset=utf-8",
                "Content-Disposition": f"attachment; filename=session-{session_id[:8]}.txt",
            },
        )

    elif format == "md":
        content = generate_markdown_export(session_data)
        return (
            content,
            200,
            {
                "Content-Type": "text/markdown; charset=utf-8",
                "Content-Disposition": f"attachment; filename=session-{session_id[:8]}.md",
            },
        )

    else:
        return jsonify({"error": "Unsupported export format"}), 400


def generate_text_export(session_data):
    """Generate text format of session record"""
    lines = []

    # Basic session information
    session_id = session_data.get("session_id", "Unknown")
    created_at = session_data.get("created_at", "Unknown time")
    lines.append(f"OpenManus Session Record")
    lines.append(f"Session ID: {session_id}")
    lines.append(f"Created at: {created_at}")
    lines.append("-" * 50)

    # Add message content
    messages = session_data.get("messages", [])
    for msg in messages:
        role = msg.get("role", "")
        if role == "user":
            lines.append(f"\nUser: {msg.get('content', '')}")
        elif role == "assistant":
            lines.append(f"\nAssistant: {msg.get('content', '')}")
        elif role == "tool":
            tool_name = msg.get("name", "Unknown tool")
            lines.append(f"\nTool({tool_name}): {msg.get('content', '')}")

    return "\n".join(lines)


def generate_markdown_export(session_data):
    """Generate Markdown format of session record"""
    lines = []

    # Basic session information
    session_id = session_data.get("session_id", "Unknown")
    created_at = session_data.get("created_at", "Unknown time")
    lines.append("# OpenManus Session Record")
    lines.append(f"**Session ID**: `{session_id}`")
    lines.append(f"**Created at**: {created_at}")
    lines.append("")

    # Add message content
    messages = session_data.get("messages", [])
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user":
            lines.append("## User")
            lines.append(content)
            lines.append("")
        elif role == "assistant":
            lines.append("## Assistant")
            lines.append(content)
            lines.append("")
        elif role == "tool":
            tool_name = msg.get("name", "Unknown tool")
            lines.append(f"## Tool ({tool_name})")
            lines.append("```")
            lines.append(content)
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


@app.route("/utils/<path:filename>")
def utils(filename):
    """处理utils目录下的文件请求"""
    import os

    from flask import send_from_directory

    # 获取当前文件(app.py)所在目录的utils文件夹绝对路径
    utils_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils")
    return send_from_directory(utils_dir, filename)
