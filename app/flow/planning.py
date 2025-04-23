import json
import re
import time
from enum import Enum
from typing import ClassVar, Dict, List, Optional, Union

from pydantic import Field

from app.agent.base import BaseAgent
from app.flow.base import BaseFlow
from app.llm import LLM
from app.logger import logger
from app.schema import AgentState, Message, ToolChoice
from app.tool import PlanningTool


class PlanStepStatus(str, Enum):
    """Enum class defining possible statuses of a plan step"""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"

    @classmethod
    def get_all_statuses(cls) -> list[str]:
        """Return a list of all possible step status values"""
        return [status.value for status in cls]

    @classmethod
    def get_active_statuses(cls) -> list[str]:
        """Return a list of values representing active statuses (not started or in progress)"""
        return [cls.NOT_STARTED.value, cls.IN_PROGRESS.value]

    @classmethod
    def get_status_marks(cls) -> Dict[str, str]:
        """Return a mapping of statuses to their marker symbols"""
        return {
            cls.COMPLETED.value: "[✓]",
            cls.IN_PROGRESS.value: "[→]",
            cls.BLOCKED.value: "[!]",
            cls.NOT_STARTED.value: "[ ]",
        }

    @classmethod
    def get_status_chinese(cls) -> Dict[str, str]:
        """Return a mapping of statuses to their Chinese translations"""
        return {
            cls.COMPLETED.value: "已完成",
            cls.IN_PROGRESS.value: "进行中",
            cls.BLOCKED.value: "已阻塞",
            cls.NOT_STARTED.value: "未开始",
        }


class PlanningFlow(BaseFlow):
    """A flow that manages planning and execution of tasks using agents."""

    # 常量定义，使用ClassVar避免被Pydantic视为模型字段
    DEFAULT_STEPS: ClassVar[List[str]] = ["分析需求", "执行任务", "验证结果"]
    STEP_TYPE_PATTERN: ClassVar[str] = r"\[([A-Z_]+)\]"

    # 错误和状态消息模板
    ERROR_MESSAGES: ClassVar[Dict[str, str]] = {
        "plan_not_found": "错误: 找不到ID为 {plan_id} 的计划",
        "no_active_steps": "没有找到活跃的步骤，所有步骤都已完成或已阻塞",
        "step_error": "执行步骤 {step_index} 出错: {error}",
        "mark_step_error": "标记步骤 {step_index} 完成时出错: {error}",
        "get_plan_error": "获取计划时出错: {error}",
        "finalize_error": "生成计划总结时出错",
    }

    # 执行步骤提示模板
    STEP_PROMPT_TEMPLATE: ClassVar[
        str
    ] = """
        您是一个执行任务的智能代理。您正在执行一个任务计划中的步骤：

        当前执行步骤: {step_index}
        步骤内容: {step_text}

        请根据上述步骤内容，选择适当的工具和策略来完成任务。
        完成后，请提供一个简短的执行结果摘要，说明您完成了什么。
        """

    llm: LLM = Field(default_factory=lambda: LLM())
    planning_tool: PlanningTool = Field(default_factory=PlanningTool)
    executor_keys: List[str] = Field(default_factory=list)
    active_plan_id: str = Field(default_factory=lambda: f"plan_{int(time.time())}")
    current_step_index: Optional[int] = None

    def __init__(
        self, agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]], **data
    ):
        # Set executor keys before super().__init__
        if "executors" in data:
            data["executor_keys"] = data.pop("executors")

        # Set plan ID if provided
        if "plan_id" in data:
            data["active_plan_id"] = data.pop("plan_id")

        # Initialize the planning tool if not provided
        if "planning_tool" not in data:
            planning_tool = PlanningTool()
            data["planning_tool"] = planning_tool

        # Call parent's init with the processed data
        super().__init__(agents, **data)

        # Set executor_keys to all agent keys if not specified
        if not self.executor_keys:
            self.executor_keys = list(self.agents.keys())

    def get_executor(self, step_type: Optional[str] = None) -> BaseAgent:
        """
        Get an appropriate executor agent for the current step.
        Can be extended to select agents based on step type/requirements.
        """
        # If step type is provided and matches an agent key, use that agent
        if step_type and step_type in self.agents:
            return self.agents[step_type]

        # Otherwise use the first available executor or fall back to primary agent
        for key in self.executor_keys:
            if key in self.agents:
                return self.agents[key]

        # Fallback to primary agent
        return self.primary_agent

    async def execute(self, input_text: str) -> str:
        """Execute the planning flow with agents."""
        try:
            if not self.primary_agent:
                raise ValueError("No primary agent available")

            logger.info(f"PlanningFlow: 开始执行任务规划 - '{input_text[:50]}...'")

            # Create initial plan if input provided
            if input_text:
                logger.info(f"PlanningFlow: 创建初始计划")
                await self._create_initial_plan(input_text)

                # Verify plan was created successfully
                if self.active_plan_id not in self.planning_tool.plans:
                    logger.error(f"创建计划失败: {input_text}")
                    return f"Failed to create plan for: {input_text}"

            # 获取并显示初始计划状态
            initial_plan = await self._get_plan_text()

            # 初始结果包含计划状态
            result = f"任务计划:\n\n{initial_plan}\n\n执行结果:\n\n"

            while True:
                # Get current step to execute
                self.current_step_index, step_info = await self._get_current_step_info()

                # Exit if no more steps or plan completed
                if self.current_step_index is None:
                    logger.info("PlanningFlow: 所有步骤已完成，准备结束计划")
                    final_message = await self._finalize_plan()
                    result += f"\n{final_message}\n"
                    break

                # Execute current step with appropriate agent
                step_type = step_info.get("type") if step_info else None
                executor = self.get_executor(step_type)

                logger.info(
                    f"PlanningFlow: 执行步骤 {self.current_step_index} - '{step_info.get('text', '')[:50]}...'"
                )

                # 减少日志噪音，仅在调试模式下记录详细的计划状态
                logger.info(
                    f"PlanningFlow: 当前计划状态:\n{await self._get_plan_text()}"
                )

                # 使用代理的execute_planned_step方法执行步骤
                if hasattr(executor, "execute_planned_step") and callable(
                    getattr(executor, "execute_planned_step")
                ):
                    step_prompt = self._create_step_prompt(step_info)
                    # 传递当前步骤索引和规划流程实例
                    step_result = await executor.execute_planned_step(
                        step_prompt,
                        current_step_index=self.current_step_index,
                        planning_flow=self,
                    )
                    # 注意：execute_planned_step方法会自动标记步骤完成，这里不需要再标记
                else:
                    # 如果代理没有execute_planned_step方法，则使用_execute_step
                    step_result = await self._execute_step(executor, step_info)
                    # 这种情况下需要手动标记步骤完成
                    await self._mark_step_completed()

                # 将步骤结果添加到总结果
                result += f"步骤 {self.current_step_index}: {step_info.get('text', '')}\n{step_result}\n\n"

                # 获取更新后的计划状态
                updated_status = await self._get_plan_text()
                logger.info(f"PlanningFlow: 步骤 {self.current_step_index} 已完成")
                # 详细状态只在调试模式下输出
                logger.info(f"更新后的计划状态:\n{updated_status}")

                # 添加更新后的计划状态到结果
                result += f"当前计划状态:\n{updated_status}\n\n"

                # Check if agent wants to terminate
                if hasattr(executor, "state") and executor.state == AgentState.FINISHED:
                    logger.info("PlanningFlow: 代理请求终止执行")
                    break

            # 获取最终计划状态
            final_plan = await self._get_plan_text()
            result += f"\n最终任务状态:\n{final_plan}"

            logger.info("PlanningFlow: 任务规划执行完成")
            return result
        except Exception as e:
            logger.error(f"Error in PlanningFlow: {str(e)}", exc_info=True)
            return f"Execution failed: {str(e)}"

    def _create_step_prompt(self, step_info: dict) -> str:
        """创建用于执行步骤的提示

        Args:
            step_info: 步骤信息

        Returns:
            步骤提示
        """
        step_text = step_info.get("text", f"Step {self.current_step_index}")

        # 使用模板创建步骤提示
        return self.STEP_PROMPT_TEMPLATE.format(
            step_index=self.current_step_index, step_text=step_text
        )

    async def _create_initial_plan(self, request: str) -> None:
        """Create an initial plan based on the request using the flow's LLM and PlanningTool."""
        logger.info(f"Creating initial plan with ID: {self.active_plan_id}")

        # Create a system message for plan creation
        system_message = Message.system_message(
            "You are a planning assistant. Create a concise, actionable plan with clear steps. "
            "Focus on key milestones rather than detailed sub-steps. "
            "Optimize for clarity and efficiency."
        )

        # Create a user message with the request
        user_message = Message.user_message(
            f"Create a reasonable plan with clear steps to accomplish the task: {request}"
        )

        # Call LLM with PlanningTool
        response = await self.llm.ask_tool(
            messages=[user_message],
            system_msgs=[system_message],
            tools=[self.planning_tool.to_param()],
            tool_choice=ToolChoice.AUTO,
        )

        # Process tool calls if present
        if response.tool_calls:
            for tool_call in response.tool_calls:
                if tool_call.function.name == "planning":
                    # Parse the arguments
                    args = tool_call.function.arguments
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse tool arguments: {args}")
                            continue

                    # Ensure plan_id is set correctly and execute the tool
                    args["plan_id"] = self.active_plan_id

                    # Execute the tool via ToolCollection instead of directly
                    result = await self.planning_tool.execute(**args)

                    logger.info(f"Plan creation result: {str(result)}")
                    return

        # If execution reached here, create a default plan
        logger.warning("Creating default plan")

        # Create default plan using the ToolCollection with localized default steps
        await self.planning_tool.execute(
            **{
                "command": "create",
                "plan_id": self.active_plan_id,
                "title": f"Plan for: {request[:50]}{'...' if len(request) > 50 else ''}",
                "steps": self.DEFAULT_STEPS,
            }
        )

    async def _get_current_step_info(self) -> tuple[Optional[int], Optional[dict]]:
        """
        Parse the current plan to identify the first non-completed step's index and info.
        Returns (None, None) if no active step is found.
        """
        if (
            not self.active_plan_id
            or self.active_plan_id not in self.planning_tool.plans
        ):
            logger.error(f"Plan with ID {self.active_plan_id} not found")
            return None, None

        try:
            # Direct access to plan data from planning tool storage
            plan_data = self.planning_tool.plans[self.active_plan_id]
            steps = plan_data.get("steps", [])
            step_statuses = plan_data.get("step_statuses", [])

            # 统计步骤信息
            logger.debug(
                f"计划 {self.active_plan_id} 共有 {len(steps)} 个步骤，状态: {step_statuses}"
            )

            # 确保step_statuses与steps数量匹配
            while len(step_statuses) < len(steps):
                step_statuses.append(PlanStepStatus.NOT_STARTED.value)
                logger.debug(
                    f"为步骤 {len(step_statuses)-1} 添加默认状态: {PlanStepStatus.NOT_STARTED.value}"
                )

            # 检查是否有任何步骤处于"in_progress"状态
            # 如果有，优先返回该步骤，确保它完成后再开始新步骤
            in_progress_index = None
            for i, status in enumerate(step_statuses):
                if status == PlanStepStatus.IN_PROGRESS.value:
                    in_progress_index = i
                    break

            if in_progress_index is not None:
                # 找到一个正在进行中的步骤，返回它
                step = steps[in_progress_index]
                logger.info(f"继续执行进行中的步骤 {in_progress_index}: {step[:30]}...")

                # 提取步骤类型（如果有）
                step_info = {
                    "text": step,
                    "status": PlanStepStatus.IN_PROGRESS.value,
                    "index": in_progress_index,
                }

                # 尝试提取步骤类型
                type_match = re.search(self.STEP_TYPE_PATTERN, step)
                if type_match:
                    step_info["type"] = type_match.group(1).lower()
                    logger.debug(f"找到步骤类型: {step_info['type']}")

                return in_progress_index, step_info

            # Find first non-completed step
            for i, step in enumerate(steps):
                if i >= len(step_statuses):
                    status = PlanStepStatus.NOT_STARTED.value
                else:
                    status = step_statuses[i]

                logger.debug(f"检查步骤 {i}: 状态={status}, 文本={step[:30]}...")

                if status in PlanStepStatus.get_active_statuses():
                    # Extract step type/category if available
                    step_info = {"text": step, "status": status, "index": i}

                    # Try to extract step type from the text (e.g., [SEARCH] or [CODE])
                    type_match = re.search(self.STEP_TYPE_PATTERN, step)
                    if type_match:
                        step_info["type"] = type_match.group(1).lower()
                        logger.debug(f"找到步骤类型: {step_info['type']}")

                    # Mark current step as in_progress
                    try:
                        logger.info(f"开始执行步骤 {i}: {step[:30]}...")
                        await self.planning_tool.execute(
                            command="mark_step",
                            plan_id=self.active_plan_id,
                            step_index=i,
                            step_status=PlanStepStatus.IN_PROGRESS.value,
                        )
                    except Exception as e:
                        logger.warning(f"标记步骤 {i} 为进行中状态失败: {e}")
                        # Update step status directly if needed
                        if i < len(step_statuses):
                            step_statuses[i] = PlanStepStatus.IN_PROGRESS.value
                        else:
                            while len(step_statuses) < i:
                                step_statuses.append(PlanStepStatus.NOT_STARTED.value)
                            step_statuses.append(PlanStepStatus.IN_PROGRESS.value)

                        plan_data["step_statuses"] = step_statuses
                        logger.debug(f"已手动更新步骤 {i} 状态为进行中")

                    return i, step_info

            logger.info(self.ERROR_MESSAGES["no_active_steps"])
            return None, None  # No active step found

        except Exception as e:
            logger.warning(f"查找当前步骤时出错: {e}", exc_info=True)
            return None, None

    async def _execute_step(self, executor: BaseAgent, step_info: dict) -> str:
        """Execute the current step with the specified agent using agent.run()."""
        # Prepare context for the agent with current plan status
        await self._get_plan_text()

        # 创建步骤提示
        step_prompt = self._create_step_prompt(step_info)

        # Use agent.run() to execute the step
        try:
            logger.info(
                f"正在使用代理 {executor.name if hasattr(executor, 'name') else 'Unknown'} 执行步骤 {self.current_step_index}"
            )
            step_result = await executor.run(step_prompt)
            logger.info(
                f"步骤 {self.current_step_index} 执行完成: {step_result[:100]}..."
            )

            return step_result
        except Exception as e:
            error_msg = self.ERROR_MESSAGES["step_error"].format(
                step_index=self.current_step_index, error=str(e)
            )
            logger.error(error_msg, exc_info=True)
            return error_msg

    async def _mark_step_completed(self) -> None:
        """Mark the current step as completed."""
        if self.current_step_index is None:
            logger.warning("无法标记步骤完成: 当前步骤索引为空")
            return

        try:
            # 获取当前步骤状态
            if self.active_plan_id in self.planning_tool.plans:
                plan_data = self.planning_tool.plans[self.active_plan_id]
                step_statuses = plan_data.get("step_statuses", [])
                current_status = (
                    step_statuses[self.current_step_index]
                    if self.current_step_index < len(step_statuses)
                    else "unknown"
                )
                # 只有当状态不是已完成时才进行日志记录和标记操作
                if current_status != PlanStepStatus.COMPLETED.value:
                    # 简化日志，只记录步骤改变
                    logger.info(
                        f"标记步骤 {self.current_step_index}: {current_status} -> {PlanStepStatus.COMPLETED.value}"
                    )

                    # Mark the step as completed
                    await self.planning_tool.execute(
                        command="mark_step",
                        plan_id=self.active_plan_id,
                        step_index=self.current_step_index,
                        step_status=PlanStepStatus.COMPLETED.value,
                    )
                else:
                    logger.debug(
                        f"步骤 {self.current_step_index} 已经是完成状态，无需重复标记"
                    )
            else:
                logger.warning(f"找不到计划 {self.active_plan_id}，无法标记步骤状态")
        except Exception as e:
            error_msg = self.ERROR_MESSAGES["mark_step_error"].format(
                step_index=self.current_step_index, error=str(e)
            )
            logger.warning(error_msg, exc_info=True)

            # Update step status directly in planning tool storage
            if self.active_plan_id in self.planning_tool.plans:
                plan_data = self.planning_tool.plans[self.active_plan_id]
                step_statuses = plan_data.get("step_statuses", [])

                # Ensure the step_statuses list is long enough
                while len(step_statuses) <= self.current_step_index:
                    step_statuses.append(PlanStepStatus.NOT_STARTED.value)

                # Update the status
                step_statuses[self.current_step_index] = PlanStepStatus.COMPLETED.value
                plan_data["step_statuses"] = step_statuses
                logger.info(f"已手动更新步骤 {self.current_step_index} 为已完成状态")

    async def _get_plan_text(self) -> str:
        """Get the current plan as formatted text."""
        try:
            result = await self.planning_tool.execute(
                command="get", plan_id=self.active_plan_id
            )
            return result.output if hasattr(result, "output") else str(result)
        except Exception as e:
            error_msg = self.ERROR_MESSAGES["get_plan_error"].format(error=str(e))
            logger.error(error_msg)
            return self._generate_plan_text_from_storage()

    def _generate_plan_text_from_storage(self) -> str:
        """Generate plan text directly from storage if the planning tool fails."""
        try:
            if self.active_plan_id not in self.planning_tool.plans:
                return self.ERROR_MESSAGES["plan_not_found"].format(
                    plan_id=self.active_plan_id
                )

            plan_data = self.planning_tool.plans[self.active_plan_id]
            title = plan_data.get("title", "未命名计划")
            steps = plan_data.get("steps", [])
            step_statuses = plan_data.get("step_statuses", [])
            step_notes = plan_data.get("step_notes", [])

            # Ensure step_statuses and step_notes match the number of steps
            while len(step_statuses) < len(steps):
                step_statuses.append(PlanStepStatus.NOT_STARTED.value)
            while len(step_notes) < len(steps):
                step_notes.append("")

            # Count steps by status
            status_counts = {status: 0 for status in PlanStepStatus.get_all_statuses()}

            for status in step_statuses:
                if status in status_counts:
                    status_counts[status] += 1

            completed = status_counts[PlanStepStatus.COMPLETED.value]
            total = len(steps)
            progress = (completed / total) * 100 if total > 0 else 0

            # 使用类方法获取状态的中文名称
            status_chinese = PlanStepStatus.get_status_chinese()

            plan_text = f"计划: {title} (ID: {self.active_plan_id})\n"
            plan_text += "=" * len(plan_text) + "\n\n"

            plan_text += f"进度: {completed}/{total} 步骤已完成 ({progress:.1f}%)\n"
            plan_text += f"状态: {status_counts[PlanStepStatus.COMPLETED.value]} 已完成, {status_counts[PlanStepStatus.IN_PROGRESS.value]} 进行中, "
            plan_text += f"{status_counts[PlanStepStatus.BLOCKED.value]} 已阻塞, {status_counts[PlanStepStatus.NOT_STARTED.value]} 未开始\n\n"
            plan_text += "步骤列表:\n"

            status_marks = PlanStepStatus.get_status_marks()

            for i, (step, status, notes) in enumerate(
                zip(steps, step_statuses, step_notes)
            ):
                # Use status marks to indicate step status
                status_mark = status_marks.get(
                    status, status_marks[PlanStepStatus.NOT_STARTED.value]
                )

                # 获取状态的中文名称
                status_text = status_chinese.get(status, status)

                plan_text += f"{i}. {status_mark} [{status_text}] {step}\n"
                if notes:
                    plan_text += f"   笔记: {notes}\n"

            return plan_text
        except Exception as e:
            logger.error(f"Error generating plan text from storage: {e}")
            return self.ERROR_MESSAGES["plan_not_found"].format(
                plan_id=self.active_plan_id
            )

    async def _finalize_plan(self) -> str:
        """Finalize the plan and provide a summary using the flow's LLM directly."""
        plan_text = await self._get_plan_text()

        # Create a summary using the flow's LLM directly
        try:
            system_message = Message.system_message(
                "You are a planning assistant. Your task is to summarize the completed plan."
            )

            user_message = Message.user_message(
                f"The plan has been completed. Here is the final plan status:\n\n{plan_text}\n\nPlease provide a summary of what was accomplished and any final thoughts."
            )

            response = await self.llm.ask(
                messages=[user_message], system_msgs=[system_message]
            )

            return f"Plan completed:\n\n{response}"
        except Exception as e:
            logger.error(f"Error finalizing plan with LLM: {e}")

            # Fallback to using an agent for the summary
            try:
                agent = self.primary_agent
                summary_prompt = f"""
                The plan has been completed. Here is the final plan status:

                {plan_text}

                Please provide a summary of what was accomplished and any final thoughts.
                """
                summary = await agent.run(summary_prompt)
                return f"Plan completed:\n\n{summary}"
            except Exception as e2:
                logger.error(f"Error finalizing plan with agent: {e2}")
                return self.ERROR_MESSAGES["finalize_error"]
