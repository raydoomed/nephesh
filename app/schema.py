import time
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class Role(str, Enum):
    """Message role options"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


ROLE_VALUES = tuple(role.value for role in Role)
ROLE_TYPE = Literal[ROLE_VALUES]  # type: ignore


class ToolChoice(str, Enum):
    """Tool choice options"""

    NONE = "none"
    AUTO = "auto"
    REQUIRED = "required"


TOOL_CHOICE_VALUES = tuple(choice.value for choice in ToolChoice)
TOOL_CHOICE_TYPE = Literal[TOOL_CHOICE_VALUES]  # type: ignore


class AgentState(str, Enum):
    """Agent execution states"""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"


class Function(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    """Represents a tool/function call in a message"""

    id: str
    type: str = "function"
    function: Function


class Message(BaseModel):
    """Represents a chat message in the conversation"""

    role: ROLE_TYPE = Field(...)  # type: ignore
    content: Optional[str] = Field(default=None)
    tool_calls: Optional[List[ToolCall]] = Field(default=None)
    name: Optional[str] = Field(default=None)
    tool_call_id: Optional[str] = Field(default=None)
    base64_image: Optional[str] = Field(default=None)

    def __add__(self, other) -> List["Message"]:
        """支持 Message + list 或 Message + Message 的操作"""
        if isinstance(other, list):
            return [self] + other
        elif isinstance(other, Message):
            return [self, other]
        else:
            raise TypeError(
                f"unsupported operand type(s) for +: '{type(self).__name__}' and '{type(other).__name__}'"
            )

    def __radd__(self, other) -> List["Message"]:
        """支持 list + Message 的操作"""
        if isinstance(other, list):
            return other + [self]
        else:
            raise TypeError(
                f"unsupported operand type(s) for +: '{type(other).__name__}' and '{type(self).__name__}'"
            )

    def to_dict(self) -> dict:
        """Convert message to dictionary format"""
        message = {"role": self.role}
        if self.content is not None:
            message["content"] = self.content
        if self.tool_calls is not None:
            message["tool_calls"] = [tool_call.dict() for tool_call in self.tool_calls]
        if self.name is not None:
            message["name"] = self.name
        if self.tool_call_id is not None:
            message["tool_call_id"] = self.tool_call_id
        if self.base64_image is not None:
            message["base64_image"] = self.base64_image
        return message

    @classmethod
    def user_message(
        cls, content: str, base64_image: Optional[str] = None
    ) -> "Message":
        """Create a user message"""
        return cls(role=Role.USER, content=content, base64_image=base64_image)

    @classmethod
    def system_message(cls, content: str) -> "Message":
        """Create a system message"""
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def assistant_message(
        cls, content: Optional[str] = None, base64_image: Optional[str] = None
    ) -> "Message":
        """Create an assistant message"""
        return cls(role=Role.ASSISTANT, content=content, base64_image=base64_image)

    @classmethod
    def tool_message(
        cls, content: str, name, tool_call_id: str, base64_image: Optional[str] = None
    ) -> "Message":
        """Create a tool message"""
        return cls(
            role=Role.TOOL,
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            base64_image=base64_image,
        )

    @classmethod
    def from_tool_calls(
        cls,
        tool_calls: List[Any],
        content: Union[str, List[str]] = "",
        base64_image: Optional[str] = None,
        **kwargs,
    ):
        """Create ToolCallsMessage from raw tool calls.

        Args:
            tool_calls: Raw tool calls from LLM
            content: Optional message content
            base64_image: Optional base64 encoded image
        """
        try:
            formatted_calls = []
            for call in tool_calls:
                # 尝试使用dict()方法，如果失败则尝试model_dump()
                try:
                    function_data = call.function.dict()
                except AttributeError:
                    try:
                        function_data = call.function.model_dump()
                    except AttributeError:
                        # 如果都失败，则直接转换为字典
                        function_data = {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        }

                formatted_calls.append(
                    {"id": call.id, "function": function_data, "type": "function"}
                )

            return cls(
                role=Role.ASSISTANT,
                content=content,
                tool_calls=formatted_calls,
                base64_image=base64_image,
                **kwargs,
            )
        except Exception as e:
            # 如果出现任何错误，返回不带工具调用的消息
            import logging

            logging.error(f"Error formatting tool calls: {e}")
            return cls(
                role=Role.ASSISTANT,
                content=content if isinstance(content, str) else str(content),
                base64_image=base64_image,
                **kwargs,
            )


class Memory(BaseModel):
    messages: List[Message] = Field(default_factory=list)
    max_messages: int = Field(default=100)

    # 新增字段用于记忆压缩和摘要管理
    summaries: List[Dict[str, Any]] = Field(default_factory=list)
    compression_threshold: int = Field(
        default=20, description="消息数量超过该阈值时触发压缩"
    )
    compression_ratio: float = Field(
        default=0.5, description="压缩比例，保留多少比例的最新消息"
    )
    last_compression_size: int = Field(default=0, description="上次压缩时的消息数量")
    auto_compress: bool = Field(default=True, description="是否自动压缩")
    compress_system_messages: bool = Field(
        default=False, description="是否压缩系统消息"
    )

    def add_message(self, message: Message) -> None:
        """Add a message to memory and trigger compression if threshold exceeded"""
        self.messages.append(message)

        # 检查是否需要自动压缩
        if (
            self.auto_compress
            and len(self.messages) > self.compression_threshold
            and len(self.messages)
            > self.last_compression_size + self.compression_threshold // 2
        ):
            self.compress_memory()

        # 保持消息数量不超过上限
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]

    def add_messages(self, messages: List[Message]) -> None:
        """Add multiple messages to memory"""
        self.messages.extend(messages)

        # 检查是否需要自动压缩
        if (
            self.auto_compress
            and len(self.messages) > self.compression_threshold
            and len(self.messages)
            > self.last_compression_size + self.compression_threshold // 2
        ):
            self.compress_memory()

        # 保持消息数量不超过上限
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]

    def clear(self) -> None:
        """Clear all messages and summaries"""
        self.messages.clear()
        self.summaries.clear()
        self.last_compression_size = 0

    def get_recent_messages(self, n: int) -> List[Message]:
        """Get n most recent messages"""
        return self.messages[-n:]

    def get_memory_with_summaries(self) -> List[Message]:
        """获取包含摘要的完整记忆，用于LLM上下文"""
        result = []

        # 添加所有摘要作为系统消息
        if self.summaries:
            for summary in self.summaries:
                summary_text = f"历史对话摘要 ({summary['start_idx']}-{summary['end_idx']})：\n{summary['content']}"
                result.append(Message.system_message(summary_text))

        # 添加未压缩的消息
        # 在添加消息前确保工具消息和工具调用之间的关联关系正确
        tool_call_ids = set()
        assistant_with_tool_calls = {}

        # 第一步：收集所有的工具调用ID并建立映射
        for msg in self.messages:
            if msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_call_ids.add(tc.id)
                    assistant_with_tool_calls[tc.id] = msg

        # 第二步：处理工具消息，确保有对应的工具调用
        for msg in self.messages:
            if msg.role == "tool" and msg.tool_call_id:
                # 只添加有对应工具调用的工具消息
                if msg.tool_call_id in tool_call_ids:
                    # 确保先添加工具调用消息
                    if msg.tool_call_id in assistant_with_tool_calls:
                        assistant_msg = assistant_with_tool_calls[msg.tool_call_id]
                        if assistant_msg not in result:
                            result.append(assistant_msg)
                    # 然后添加工具消息
                    result.append(msg)
                else:
                    # 如果没有对应的工具调用，将工具消息转换为助手消息
                    content = f"工具 '{msg.name}' 执行结果: {msg.content}"
                    result.append(Message.assistant_message(content))
            else:
                # 非工具消息直接添加
                result.append(msg)

        return result

    def compress_memory(self) -> None:
        """压缩旧消息，生成摘要并替换，保留最新的消息"""
        if len(self.messages) <= self.compression_threshold:
            return

        # 计算保留的消息数量
        keep_count = int(len(self.messages) * self.compression_ratio)
        keep_count = max(keep_count, 10)  # 至少保留10条消息

        # 要压缩的消息
        to_compress = self.messages[:-keep_count]

        # 排除系统消息（如果设置了不压缩系统消息）
        if not self.compress_system_messages:
            system_messages = [msg for msg in to_compress if msg.role == "system"]
            to_compress = [msg for msg in to_compress if msg.role != "system"]
        else:
            system_messages = []

        if to_compress:
            # 记录压缩范围
            start_idx = 0
            end_idx = len(to_compress) - 1

            # 生成摘要文本
            summary_text = self._generate_summary(to_compress)

            # 存储摘要
            self.summaries.append(
                {
                    "start_idx": start_idx,
                    "end_idx": end_idx,
                    "content": summary_text,
                    "timestamp": time.time(),
                }
            )

            # 更新消息列表，保留系统消息和新消息
            self.messages = system_messages + self.messages[-keep_count:]

            # 更新上次压缩大小
            self.last_compression_size = len(self.messages)

    def _generate_summary(self, messages: List[Message]) -> str:
        """生成消息列表的摘要

        这个简单实现直接连接消息，真实实现中应该使用LLM进行摘要
        """
        # 简单实现：生成基本摘要文本
        summary_lines = []
        for i, msg in enumerate(messages):
            if isinstance(msg.content, str) and msg.content:
                role_name = (
                    "用户"
                    if msg.role == "user"
                    else "助手" if msg.role == "assistant" else msg.role
                )
                content_preview = msg.content[:50] + (
                    "..." if len(msg.content) > 50 else ""
                )
                summary_lines.append(f"{role_name}: {content_preview}")

        return "\n".join(summary_lines)

    async def generate_llm_summary(self, messages: List[Message], llm=None) -> str:
        """使用LLM生成高质量摘要

        Args:
            messages: 要摘要的消息列表
            llm: LLM实例，如果为None则使用简单摘要

        Returns:
            生成的摘要文本
        """
        if not llm:
            return self._generate_summary(messages)

        try:
            # 准备摘要提示
            prompt = "请对以下对话内容生成简洁而全面的摘要，包含关键信息点和决策："

            # 格式化消息
            formatted_messages = []
            for msg in messages:
                if isinstance(msg.content, str) and msg.content:
                    role_str = (
                        "用户"
                        if msg.role == "user"
                        else "助手" if msg.role == "assistant" else msg.role
                    )
                    formatted_messages.append(f"{role_str}: {msg.content}")

            conversation_text = "\n".join(formatted_messages)

            # 调用LLM生成摘要
            from app.llm import LLM

            if not isinstance(llm, LLM):
                llm = LLM()

            # 创建提示消息
            system_msg = Message.system_message(
                "你是一个专业的对话摘要助手，你的任务是生成简洁但信息完整的对话摘要。"
            )
            user_msg = Message.user_message(f"{prompt}\n\n{conversation_text}")

            # 获取摘要
            response = await llm.ask([system_msg, user_msg])
            if response and hasattr(response, "content") and response.content:
                return response.content

            return self._generate_summary(messages)
        except Exception as e:
            # 失败时回退到简单摘要
            from app.logger import logger

            logger.error(f"生成LLM摘要失败: {e}")
            return self._generate_summary(messages)

    def to_dict_list(self) -> List[dict]:
        """Convert messages to list of dicts"""
        return [msg.to_dict() for msg in self.messages]
