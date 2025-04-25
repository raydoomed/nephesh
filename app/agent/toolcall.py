import asyncio
import json
from typing import Any, Dict, List, Optional, Union

from pydantic import Field

from app.agent.react import ReActAgent
from app.exceptions import TokenLimitExceeded
from app.logger import logger
from app.prompt.toolcall import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.schema import TOOL_CHOICE_TYPE, AgentState, Message, ToolCall, ToolChoice
from app.tool import CreateChatCompletion, Terminate, ToolCollection

TOOL_CALL_REQUIRED = "Tool calls required but none provided"


class ToolCallAgent(ReActAgent):
    """Base agent class for handling tool/function calls with enhanced abstraction"""

    name: str = "toolcall"
    description: str = "an agent that can execute tool calls."

    system_prompt: str = SYSTEM_PROMPT
    next_step_prompt: str = NEXT_STEP_PROMPT

    available_tools: ToolCollection = ToolCollection(
        CreateChatCompletion(), Terminate()
    )
    tool_choices: TOOL_CHOICE_TYPE = ToolChoice.AUTO  # type: ignore
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])

    tool_calls: List[ToolCall] = Field(default_factory=list)
    _current_base64_image: Optional[str] = None

    max_steps: int = 30
    max_observe: Optional[Union[int, bool]] = None

    # 添加工具使用历史和性能跟踪
    tool_usage_history: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    tool_success_rates: Dict[str, float] = Field(default_factory=dict)

    async def think(self) -> bool:
        """Process current state and decide next actions using tools"""
        if self.next_step_prompt:
            user_msg = Message.user_message(self.next_step_prompt)
            self.messages += [user_msg]

        # 检查是否需要使用压缩后的记忆
        messages_for_llm = self.messages

        # 如果支持记忆摘要功能，使用带摘要的消息列表
        if hasattr(self.memory, "get_memory_with_summaries") and self.memory.summaries:
            # 获取带摘要的消息，但需要额外处理确保工具调用的正确关联
            try:
                all_messages = self.memory.get_memory_with_summaries()

                # 确保工具调用和工具响应的关联关系正确
                # 检查是否存在没有对应assistant tool_calls的tool消息
                messages_for_llm = []
                tool_call_ids = set()
                assistant_indices = {}

                # 第一遍：收集所有工具调用ID和assistant消息位置
                for i, msg in enumerate(all_messages):
                    if msg.role == "assistant" and msg.tool_calls:
                        for tc in msg.tool_calls:
                            tool_call_ids.add(tc.id)
                            assistant_indices[tc.id] = i

                # 第二遍：确保只包含有对应工具调用的工具响应
                for i, msg in enumerate(all_messages):
                    if msg.role == "tool" and msg.tool_call_id:
                        # 只保留有对应assistant消息的tool消息
                        if msg.tool_call_id in tool_call_ids:
                            # 确保assistant消息在工具消息之前
                            if (
                                msg.tool_call_id in assistant_indices
                                and assistant_indices[msg.tool_call_id] < i
                            ):
                                messages_for_llm.append(msg)
                        else:
                            # 工具消息没有对应的工具调用，转换为assistant消息
                            content = f"工具 '{msg.name}' 执行结果: {msg.content}"
                            messages_for_llm.append(Message.assistant_message(content))
                    else:
                        # 非工具消息直接添加
                        messages_for_llm.append(msg)

                logger.info(
                    f"🧠 {self.name} 使用记忆压缩和摘要功能，消息数量: {len(messages_for_llm)}，包含摘要数量: {len(self.memory.summaries)}"
                )
            except Exception as e:
                # 如果处理失败，退回到使用原始消息
                logger.error(f"处理记忆摘要时出错: {e}，退回到使用原始消息")
                messages_for_llm = self.messages

        try:
            # Get response with tool options using optimized memory context
            response = await self.llm.ask_tool(
                messages=messages_for_llm,
                system_msgs=(
                    [Message.system_message(self.system_prompt)]
                    if self.system_prompt
                    else None
                ),
                tools=self.available_tools.to_params(),
                tool_choice=self.tool_choices,
            )
        except ValueError:
            raise
        except Exception as e:
            # Check if this is a RetryError containing TokenLimitExceeded
            if hasattr(e, "__cause__") and isinstance(e.__cause__, TokenLimitExceeded):
                token_limit_error = e.__cause__
                logger.error(
                    f"🚨 Token limit error (from RetryError): {token_limit_error}"
                )

                # 尝试进行更激进的记忆压缩和摘要以减少token
                if hasattr(self.memory, "compress_memory"):
                    logger.warning(
                        f"🔄 {self.name} 执行紧急记忆压缩以处理token超限问题"
                    )
                    # 保存原来的压缩比例
                    original_ratio = getattr(self.memory, "compression_ratio", 0.5)
                    # 设置更激进的压缩比例
                    self.memory.compression_ratio = 0.3
                    self.memory.compress_memory()
                    # 恢复原来的压缩比例
                    self.memory.compression_ratio = original_ratio

                    # 使用压缩后的记忆重试一次
                    try:
                        messages_for_llm = self.memory.get_memory_with_summaries()
                        logger.info(
                            f"🔄 紧急压缩后重试，消息数量: {len(messages_for_llm)}"
                        )

                        response = await self.llm.ask_tool(
                            messages=messages_for_llm,
                            system_msgs=(
                                [Message.system_message(self.system_prompt)]
                                if self.system_prompt
                                else None
                            ),
                            tools=self.available_tools.to_params(),
                            tool_choice=self.tool_choices,
                        )
                        # 如果成功，继续正常执行
                        logger.info(f"✅ {self.name} 紧急压缩记忆后成功恢复执行")
                    except Exception as retry_error:
                        # 如果重试也失败，记录错误并终止
                        logger.error(f"🚨 紧急记忆压缩后仍然失败: {retry_error}")
                        self.memory.add_message(
                            Message.assistant_message(
                                f"即使进行记忆压缩后，仍然超出了token限制，无法继续执行: {str(token_limit_error)}"
                            )
                        )
                        self.state = AgentState.FINISHED
                        return False
                else:
                    # 如果没有压缩功能，按原来逻辑处理
                    self.memory.add_message(
                        Message.assistant_message(
                            f"Maximum token limit reached, cannot continue execution: {str(token_limit_error)}"
                        )
                    )
                    self.state = AgentState.FINISHED
                    return False
            else:
                # 其他类型的错误直接抛出
                raise

        self.tool_calls = tool_calls = (
            response.tool_calls if response and response.tool_calls else []
        )
        content = response.content if response and response.content else ""

        # Log response info
        logger.info(f"✨ {self.name}'s thoughts: {content}")
        logger.info(
            f"🛠️ {self.name} selected {len(tool_calls) if tool_calls else 0} tools to use"
        )
        if tool_calls:
            logger.info(
                f"🧰 Tools being prepared: {[call.function.name for call in tool_calls]}"
            )
            logger.info(f"🔧 Tool arguments: {tool_calls[0].function.arguments}")

        try:
            if response is None:
                raise RuntimeError("No response received from the LLM")

            # Handle different tool_choices modes
            if self.tool_choices == ToolChoice.NONE:
                if tool_calls:
                    logger.warning(
                        f"🤔 Hmm, {self.name} tried to use tools when they weren't available!"
                    )
                if content:
                    self.memory.add_message(Message.assistant_message(content))
                    return True
                return False

            # Create and add assistant message
            assistant_msg = (
                Message.from_tool_calls(content=content, tool_calls=self.tool_calls)
                if self.tool_calls
                else Message.assistant_message(content)
            )
            self.memory.add_message(assistant_msg)

            if self.tool_choices == ToolChoice.REQUIRED and not self.tool_calls:
                return True  # Will be handled in act()

            # For 'auto' mode, continue with content if no commands but content exists
            if self.tool_choices == ToolChoice.AUTO and not self.tool_calls:
                return bool(content)

            return bool(self.tool_calls)
        except Exception as e:
            logger.error(f"🚨 Oops! The {self.name}'s thinking process hit a snag: {e}")
            self.memory.add_message(
                Message.assistant_message(
                    f"Error encountered while processing: {str(e)}"
                )
            )
            return False

    async def optimize_tool_selection(self) -> None:
        """优化工具选择策略，分析历史工具使用情况并可能调整工具选择策略

        此方法实现了智能工具选择优化，通过以下策略提升效率：
        1. 分析工具使用历史和成功率
        2. 识别工具使用模式
        3. 根据当前任务上下文调整工具优先级
        4. 过滤或替换低效工具
        """
        if not self.tool_calls:
            return

        # 当前任务上下文分析
        recent_messages = self.memory.messages[-5:] if self.memory.messages else []
        current_context = " ".join(
            [msg.content or "" for msg in recent_messages if msg.content]
        )

        # 分析当前选择的工具是否适合当前任务
        for i, tool_call in enumerate(self.tool_calls):
            tool_name = tool_call.function.name

            # 更新工具使用历史
            if tool_name not in self.tool_usage_history:
                self.tool_usage_history[tool_name] = []

            # 记录本次使用
            self.tool_usage_history[tool_name].append(
                {
                    "arguments": tool_call.function.arguments,
                    "context": current_context[:200],  # 只保存上下文的前200个字符
                    "step": self.current_step,
                    "timestamp": asyncio.get_event_loop().time(),
                    "success": None,  # 将在执行后更新
                }
            )

            # 检查此工具的历史成功率
            if (
                tool_name in self.tool_success_rates
                and self.tool_success_rates[tool_name] < 0.3
            ):
                # 如果工具历史成功率低于30%，考虑替换为更可靠的工具
                logger.warning(
                    f"🔄 Tool '{tool_name}' has low success rate ({self.tool_success_rates[tool_name]:.2f}), considering alternatives"
                )

                # 这里可以实现工具替换逻辑，但需要谨慎，避免过度干预模型决策
                # 目前只记录警告，不进行实际替换

            # 如果是特殊工具，确保其位置适当（通常应该最后执行）
            if self._is_special_tool(tool_name) and i < len(self.tool_calls) - 1:
                # 将特殊工具移到末尾
                logger.info(
                    f"🔀 Reordering: moving special tool '{tool_name}' to the end of execution queue"
                )
                self.tool_calls.append(self.tool_calls.pop(i))
                # 由于修改了tool_calls，需要重新开始循环
                break

    async def act(self) -> str:
        """Execute tool calls and handle their results"""
        if not self.tool_calls:
            if self.tool_choices == ToolChoice.REQUIRED:
                raise ValueError(TOOL_CALL_REQUIRED)

            # Return last message content if no tool calls
            return self.messages[-1].content or "No content or commands to execute"

        # 优化工具选择策略
        await self.optimize_tool_selection()

        results = []
        for command in self.tool_calls:
            # Reset base64_image for each tool call
            self._current_base64_image = None

            # 记录开始时间，用于性能分析
            start_time = asyncio.get_event_loop().time()
            success = True  # 默认假设成功

            try:
                result = await self.execute_tool(command)

                if self.max_observe:
                    result = result[: self.max_observe]

                logger.info(
                    f"🎯 Tool '{command.function.name}' completed its mission! Result: {result}"
                )

                # 找到工具调用的原始消息 (assistant消息，带有tool_calls)
                assistant_msg_with_tool_calls = None
                for i in range(len(self.memory.messages) - 1, -1, -1):
                    msg = self.memory.messages[i]
                    if (
                        msg.role == "assistant"
                        and msg.tool_calls
                        and any(tc.id == command.id for tc in msg.tool_calls)
                    ):
                        assistant_msg_with_tool_calls = msg
                        break

                # 确保找到了工具调用的原始消息
                if assistant_msg_with_tool_calls:
                    # Add tool response to memory
                    tool_msg = Message.tool_message(
                        content=result,
                        tool_call_id=command.id,
                        name=command.function.name,
                        base64_image=self._current_base64_image,
                    )
                    self.memory.add_message(tool_msg)
                    results.append(result)
                else:
                    # 找不到对应的工具调用消息，使用普通消息
                    logger.warning(
                        f"找不到匹配的工具调用消息 ID {command.id}，使用普通消息"
                    )
                    self.memory.add_message(
                        Message.assistant_message(
                            f"工具 '{command.function.name}' 执行结果: {result}"
                        )
                    )
                    results.append(result)

            except Exception as e:
                # 工具执行失败
                success = False
                error_msg = (
                    f"⚠️ Tool '{command.function.name}' execution failed: {str(e)}"
                )
                logger.error(error_msg)
                self.memory.add_message(Message.assistant_message(error_msg))
                results.append(f"Error: {error_msg}")
            finally:
                # 完成工具执行后，更新工具使用历史
                tool_name = command.function.name
                if (
                    tool_name in self.tool_usage_history
                    and self.tool_usage_history[tool_name]
                ):
                    # 更新最近一次使用记录
                    self.tool_usage_history[tool_name][-1].update(
                        {
                            "success": success,
                            "duration": asyncio.get_event_loop().time() - start_time,
                        }
                    )

                    # 更新工具成功率
                    successes = sum(
                        1
                        for record in self.tool_usage_history[tool_name]
                        if record["success"]
                    )
                    total = len(self.tool_usage_history[tool_name])
                    self.tool_success_rates[tool_name] = (
                        successes / total if total > 0 else 0.0
                    )

        return "\n\n".join(results)

    async def execute_tool(self, command: ToolCall) -> str:
        """Execute a single tool call with robust error handling"""
        if not command or not command.function or not command.function.name:
            return "Error: Invalid command format"

        name = command.function.name
        if name not in self.available_tools.tool_map:
            return f"Error: Unknown tool '{name}'"

        try:
            # Parse arguments
            args = json.loads(command.function.arguments or "{}")

            # Execute the tool
            logger.info(f"🔧 Activating tool: '{name}'...")
            result = await self.available_tools.execute(name=name, tool_input=args)

            # Handle special tools
            await self._handle_special_tool(name=name, result=result)

            # Check if result is a ToolResult with base64_image
            if hasattr(result, "base64_image") and result.base64_image:
                # Store the base64_image for later use in tool_message
                self._current_base64_image = result.base64_image

                # Format result for display
                observation = (
                    f"Observed output of cmd `{name}` executed:\n{str(result)}"
                    if result
                    else f"Cmd `{name}` completed with no output"
                )
                return observation

            # Format result for display (standard case)
            observation = (
                f"Observed output of cmd `{name}` executed:\n{str(result)}"
                if result
                else f"Cmd `{name}` completed with no output"
            )

            return observation
        except json.JSONDecodeError:
            error_msg = f"Error parsing arguments for {name}: Invalid JSON format"
            logger.error(
                f"📝 Oops! The arguments for '{name}' don't make sense - invalid JSON, arguments:{command.function.arguments}"
            )
            return f"Error: {error_msg}"
        except Exception as e:
            error_msg = f"⚠️ Tool '{name}' encountered a problem: {str(e)}"
            logger.exception(error_msg)
            return f"Error: {error_msg}"

    async def _handle_special_tool(self, name: str, result: Any, **kwargs):
        """Handle special tool execution and state changes"""
        if not self._is_special_tool(name):
            return

        if self._should_finish_execution(name=name, result=result, **kwargs):
            # Set agent state to finished
            logger.info(f"🏁 Special tool '{name}' has completed the task!")
            self.state = AgentState.FINISHED

    @staticmethod
    def _should_finish_execution(**kwargs) -> bool:
        """Determine if tool execution should finish the agent"""
        return True

    def _is_special_tool(self, name: str) -> bool:
        """Check if tool name is in special tools list"""
        return name.lower() in [n.lower() for n in self.special_tool_names]

    async def cleanup(self):
        """Clean up resources used by the agent's tools."""
        logger.info(f"🧹 Cleaning up resources for agent '{self.name}'...")
        for tool_name, tool_instance in self.available_tools.tool_map.items():
            if hasattr(tool_instance, "cleanup") and asyncio.iscoroutinefunction(
                tool_instance.cleanup
            ):
                try:
                    logger.debug(f"🧼 Cleaning up tool: {tool_name}")
                    await tool_instance.cleanup()
                except Exception as e:
                    logger.error(
                        f"🚨 Error cleaning up tool '{tool_name}': {e}", exc_info=True
                    )
        logger.info(f"✨ Cleanup complete for agent '{self.name}'.")

    async def run(self, request: Optional[str] = None) -> str:
        """运行代理，执行工具调用直到完成

        Args:
            request: 初始用户请求

        Returns:
            执行结果
        """
        try:
            response = await super().run(request)

            # 检查是否因为达到max_steps而终止，如果是则尝试优雅地结束当前任务
            if (
                self.state == AgentState.FINISHED
                and self.current_step >= self.max_steps
            ):
                logger.warning(
                    f"ToolCallAgent强制终止: 已达到最大步数 {self.max_steps}"
                )

                # 如果是特殊工具，尝试调用terminate工具来结束任务
                for tool_name in self.special_tool_names:
                    if tool_name == "terminate":
                        try:
                            terminate_tool = self.available_tools.get_tool("terminate")
                            if terminate_tool:
                                tool_result = await terminate_tool.execute(
                                    status="force_complete"
                                )
                                logger.info(f"强制调用终止工具完成任务: {tool_result}")

                                # 添加强制终止消息
                                self.memory.add_message(
                                    Message.system_message(
                                        "已达到最大步数限制，系统强制完成当前步骤。"
                                    )
                                )
                                break
                        except Exception as e:
                            logger.error(f"强制终止工具调用失败: {e}")

            return response
        finally:
            await self.cleanup()
