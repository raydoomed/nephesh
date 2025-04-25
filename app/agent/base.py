from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from app.llm import LLM
from app.logger import logger
from app.sandbox.client import SANDBOX_CLIENT
from app.schema import ROLE_TYPE, AgentState, Memory, Message


class BaseAgent(BaseModel, ABC):
    """Abstract base class for managing agent state and execution.

    Provides foundational functionality for state transitions, memory management,
    and a step-based execution loop. Subclasses must implement the `step` method.
    """

    # Core attributes
    name: str = Field(..., description="Unique name of the agent")
    description: Optional[str] = Field(None, description="Optional agent description")

    # Prompts
    system_prompt: Optional[str] = Field(
        None, description="System-level instruction prompt"
    )
    next_step_prompt: Optional[str] = Field(
        None, description="Prompt for determining next action"
    )

    # Dependencies
    llm: LLM = Field(default_factory=LLM, description="Language model instance")
    memory: Memory = Field(default_factory=Memory, description="Agent's memory store")
    state: AgentState = Field(
        default=AgentState.IDLE, description="Current agent state"
    )

    # Execution control
    max_steps: int = Field(default=10, description="Maximum steps before termination")
    current_step: int = Field(default=0, description="Current step in execution")

    duplicate_threshold: int = 2

    class Config:
        arbitrary_types_allowed = True
        extra = "allow"  # Allow extra fields for flexibility in subclasses

    @model_validator(mode="after")
    def initialize_agent(self) -> "BaseAgent":
        """Initialize agent with default settings if not provided."""
        if self.llm is None or not isinstance(self.llm, LLM):
            self.llm = LLM(config_name=self.name.lower())
        if not isinstance(self.memory, Memory):
            self.memory = Memory()
        return self

    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        """Context manager for safe agent state transitions.

        Args:
            new_state: The state to transition to during the context.

        Yields:
            None: Allows execution within the new state.

        Raises:
            ValueError: If the new_state is invalid.
        """
        if not isinstance(new_state, AgentState):
            raise ValueError(f"Invalid state: {new_state}")

        previous_state = self.state
        self.state = new_state
        try:
            yield
        except Exception as e:
            self.state = AgentState.ERROR  # Transition to ERROR on failure
            raise e
        finally:
            self.state = previous_state  # Revert to previous state

    def update_memory(
        self,
        role: ROLE_TYPE,  # type: ignore
        content: str,
        base64_image: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Add a message to the agent's memory.

        Args:
            role: The role of the message sender (user, system, assistant, tool).
            content: The message content.
            base64_image: Optional base64 encoded image.
            **kwargs: Additional arguments (e.g., tool_call_id for tool messages).

        Raises:
            ValueError: If the role is unsupported.
        """
        if role not in ["user", "system", "assistant", "tool"]:
            raise ValueError(f"Unsupported message role: {role}")

        # 根据角色类型创建适当的消息
        if role == "user":
            message = Message.user_message(content, base64_image=base64_image)
        elif role == "system":
            message = Message.system_message(content)
        elif role == "assistant":
            message = Message.assistant_message(content, base64_image=base64_image)
        elif role == "tool":
            # 确保tool消息有必要的参数
            if "name" not in kwargs or "tool_call_id" not in kwargs:
                raise ValueError(
                    "Tool messages require 'name' and 'tool_call_id' parameters"
                )
            message = Message.tool_message(
                content,
                name=kwargs.get("name"),
                tool_call_id=kwargs.get("tool_call_id"),
                base64_image=base64_image,
            )

        # 添加消息到内存
        self.memory.add_message(message)

    async def run(self, request: Optional[str] = None) -> str:
        """Execute the agent's main loop asynchronously.

        Args:
            request: Optional initial user request to process.

        Returns:
            A string summarizing the execution results.

        Raises:
            RuntimeError: If the agent is not in IDLE state at start.
        """
        if self.state != AgentState.IDLE:
            raise RuntimeError(f"Cannot run agent from state: {self.state}")

        if request:
            self.update_memory("user", request)

        # 检查是否需要执行记忆压缩，优化长对话
        if hasattr(self.memory, "compress_memory") and len(
            self.memory.messages
        ) > getattr(self.memory, "compression_threshold", 20):
            logger.info(f"Agent {self.name}: 执行记忆压缩，优化长对话处理")
            self.memory.compress_memory()

        results: List[str] = []
        async with self.state_context(AgentState.RUNNING):
            while (
                self.current_step < self.max_steps and self.state != AgentState.FINISHED
            ):
                self.current_step += 1
                logger.info(f"Executing step {self.current_step}/{self.max_steps}")

                # 执行记忆压缩，确保在步骤执行过程中长对话也能得到优化
                memory_size = len(self.memory.messages)
                if (
                    hasattr(self.memory, "compress_memory")
                    and memory_size > getattr(self.memory, "compression_threshold", 20)
                    and memory_size
                    > getattr(self.memory, "last_compression_size", 0) + 10
                ):
                    logger.info(
                        f"Agent {self.name}: 步骤内执行记忆压缩，消息数量: {memory_size}"
                    )
                    self.memory.compress_memory()

                step_result = await self.step()

                # Check for stuck state
                if self.is_stuck():
                    self.handle_stuck_state()

                results.append(f"Step {self.current_step}: {step_result}")

            if self.current_step >= self.max_steps:
                # 检查是否支持继续模式
                continuation_mode = getattr(self, "continuation_mode", False)
                if continuation_mode:
                    self.current_step = 0
                    continuation_msg = f"已达到最大步数 {self.max_steps}，但任务尚未完成。任务将继续执行。"
                    self.update_memory("system", continuation_msg)

                    # 在继续执行前执行一次记忆压缩，确保新阶段的执行有最优的上下文
                    if hasattr(self.memory, "compress_memory"):
                        logger.info(f"Agent {self.name}: 继续模式下执行记忆压缩")
                        self.memory.compress_memory()

                    logger.warning(
                        f"Agent {self.name} reached max_steps limit of {self.max_steps}. Continuing task execution."
                    )
                    results.append(continuation_msg)
                else:
                    # 如果不支持继续模式，则按原逻辑强制完成
                    self.current_step = 0
                    self.state = AgentState.FINISHED
                    results.append(
                        f"Terminated: Reached max steps ({self.max_steps}). Marking step as completed and forcing completion."
                    )
                    logger.warning(
                        f"Agent {self.name} reached max_steps limit of {self.max_steps}. Forcing step completion."
                    )
        await SANDBOX_CLIENT.cleanup()
        return "\n".join(results) if results else "No steps executed"

    @abstractmethod
    async def step(self) -> str:
        """Execute a single step in the agent's workflow.

        Must be implemented by subclasses to define specific behavior.
        """
        # 在接近最大步数时添加紧急提示
        if self.current_step == self.max_steps - 1:
            # 检查是否支持继续模式
            continuation_mode = getattr(self, "continuation_mode", False)
            if continuation_mode:
                emergency_msg = f"当前已执行 {self.current_step} 步，即将达到最大步数 {self.max_steps}。如果任务无法在下一步完成，请进行阶段性总结，任务将在重置步数后继续执行。"
            else:
                emergency_msg = "这是最后一步，必须立即完成当前任务！"
            self.update_memory("system", emergency_msg)
            logger.warning(f"Agent approaching max steps: {emergency_msg}")
        # 如果已经是最后一步，强制将状态设为FINISHED
        elif self.current_step >= self.max_steps:
            # 检查是否支持继续模式
            continuation_mode = getattr(self, "continuation_mode", False)
            if not continuation_mode:
                self.state = AgentState.FINISHED
                logger.warning(f"已达到最大步数 {self.max_steps}，强制终止当前步骤")
                return f"步骤已达到最大限制 {self.max_steps}，强制完成"
            else:
                # 在继续模式下，重置步数并继续执行
                self.current_step = 0
                logger.warning(f"已达到最大步数 {self.max_steps}，重置步数并继续执行")
                return f"步骤已达到最大限制 {self.max_steps}，重置步数并继续任务"

    def handle_stuck_state(self):
        """Handle stuck state by adding a prompt to change strategy"""
        stuck_prompt = "\
        Observed duplicate responses. Consider new strategies and avoid repeating ineffective paths already attempted."
        self.next_step_prompt = f"{stuck_prompt}\n{self.next_step_prompt}"
        logger.warning(f"Agent detected stuck state. Added prompt: {stuck_prompt}")

    def is_stuck(self) -> bool:
        """Check if the agent is stuck in a loop by detecting duplicate content"""
        if len(self.memory.messages) < 2:
            return False

        last_message = self.memory.messages[-1]
        if not last_message.content:
            return False

        # Count identical content occurrences
        duplicate_count = sum(
            1
            for msg in reversed(self.memory.messages[:-1])
            if msg.role == "assistant" and msg.content == last_message.content
        )

        return duplicate_count >= self.duplicate_threshold

    @property
    def messages(self) -> List[Message]:
        """Retrieve a list of messages from the agent's memory."""
        return self.memory.messages

    @messages.setter
    def messages(self, value: List[Message]):
        """Set the list of messages in the agent's memory."""
        self.memory.messages = value
