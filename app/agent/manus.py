from typing import ClassVar, Dict, Optional

from pydantic import Field, model_validator

from app.agent.browser import BrowserContextHelper
from app.agent.toolcall import ToolCallAgent
from app.config import config
from app.flow.flow_factory import FlowFactory, FlowType
from app.flow.planning import PlanningFlow
from app.logger import logger
from app.prompt.manus import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.tool import Terminate, ToolCollection
from app.tool.browser_use_tool import BrowserUseTool
from app.tool.python_execute import PythonExecute
from app.tool.str_replace_editor import StrReplaceEditor


class Manus(ToolCallAgent):
    """A versatile general-purpose agent with planning capabilities."""

    name: str = "Manus"
    description: str = (
        "A versatile agent that can plan and solve various tasks using multiple tools"
    )

    system_prompt: str = SYSTEM_PROMPT.format(directory=config.workspace_root)
    next_step_prompt: str = NEXT_STEP_PROMPT

    # 配置参数，可以从配置文件加载
    max_observe: int = 10000
    max_steps: int = Field(
        default=3, description="Maximum steps allowed for task execution"
    )
    continuation_mode: bool = Field(
        default=True,
        description="Whether to allow task execution to continue after reaching max steps",
    )

    # 提示模板
    STEP_LIMIT_TEMPLATE: ClassVar[
        str
    ] = """
{prompt}

注意：你应该尽量在{max_steps}步内完成此任务。当前任务的执行步数限制为{max_steps}步。
请高效规划你的行动，每一步都要有实质性进展。
"""

    URGENT_TEMPLATE: ClassVar[
        str
    ] = """
当前已执行{current_step}步，最多允许{max_steps}步！
剩余步数: {remaining_steps}步，请注意规划剩余步骤，高效完成当前任务。
"""

    # Add general-purpose tools to the tool collection
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            PythonExecute(), BrowserUseTool(), StrReplaceEditor(), Terminate()
        )
    )

    special_tool_names: list[str] = Field(default_factory=lambda: [Terminate().name])

    browser_context_helper: Optional[BrowserContextHelper] = None
    planning_flow: Optional[PlanningFlow] = None
    is_executing_planned_task: bool = False
    current_step: int = 0

    @model_validator(mode="after")
    def initialize_helper(self) -> "Manus":
        self.browser_context_helper = BrowserContextHelper(self)
        return self

    def create_planning_flow(self) -> PlanningFlow:
        """创建规划流程，将自身作为执行代理"""
        return FlowFactory.create_flow(
            flow_type=FlowType.PLANNING, agents={"manus": self}
        )

    async def run(self, input_text: str) -> str:
        """运行代理，首先规划任务，然后执行

        Args:
            input_text: 用户输入的文本

        Returns:
            执行结果
        """
        # 如果代理正在执行规划任务中的一个步骤，则使用正常流程
        if self.is_executing_planned_task:
            return await super().run(input_text)

        # 否则，创建规划流程并执行
        logger.info(f"Manus: 为任务创建执行计划 - {input_text[:50]}...")
        self.planning_flow = self.create_planning_flow()

        # 执行规划流程
        try:
            result = await self.planning_flow.execute(input_text)
            logger.info("Manus: 任务规划执行完成")
            return result
        finally:
            # 确保执行后重置状态
            self.is_executing_planned_task = False
            logger.info("Manus: 重置执行状态")

    async def execute_planned_step(
        self, step_prompt: str, current_step_index: int = None, planning_flow=None
    ) -> str:
        """执行规划好的步骤，将标记步骤为已完成的逻辑交给planning_flow处理

        Args:
            step_prompt: 步骤提示
            current_step_index: 当前步骤索引
            planning_flow: 规划流程实例

        Returns:
            步骤执行结果

        Note:
            此方法不再自动调用planning_flow._mark_step_completed()标记步骤完成
            而是由PlanningFlow根据返回结果判断步骤是否真正完成
        """
        # 设置执行状态和上下文
        self.is_executing_planned_task = True

        # 重置步骤计数器，确保每个计划步骤有独立的步数限制
        self.current_step = 0

        # 保存当前规划流程和步骤索引，以便think方法使用
        if planning_flow:
            self.planning_flow = planning_flow

        # 添加步骤限制提示，使用模板
        step_prompt = self.STEP_LIMIT_TEMPLATE.format(
            prompt=step_prompt, max_steps=self.max_steps
        )

        # 记录正在执行的步骤
        logger.info(f"Manus: 执行计划步骤 {current_step_index} - {step_prompt[:50]}...")

        try:
            # 使用原始run方法执行步骤，允许使用多个工具调用
            result = await super().run(step_prompt)

            # 确保在执行完成后记录结果
            logger.info(
                f"Manus: 步骤 {current_step_index} 执行完成，结果: {result[:100]}..."
            )

            # 不再自动标记步骤完成，这个逻辑由PlanningFlow处理
            # 避免了重复标记和状态不一致的问题

            return result
        finally:
            self.is_executing_planned_task = False
            logger.debug(f"Manus: 完成计划步骤 {current_step_index}")  # 降低日志级别

    async def think(self) -> bool:
        """处理当前状态并决定下一步行动，考虑规划上下文或浏览器上下文。"""
        # 保存原始提示，以便恢复
        original_prompt = self.next_step_prompt
        original_system_prompt = self.system_prompt
        modified = False

        try:
            # 如果接近最大步数，添加紧急完成提示
            if self.current_step >= self.max_steps // 2:
                urgent_context = self.URGENT_TEMPLATE.format(
                    current_step=self.current_step,
                    max_steps=self.max_steps,
                    remaining_steps=self.max_steps - self.current_step,
                )
                self.next_step_prompt = f"{urgent_context}\n{self.next_step_prompt}"
                modified = True
                logger.info(
                    f"Manus: 添加步数提示，当前步数: {self.current_step}/{self.max_steps}"
                )

            # 1. 如果在执行规划任务，添加规划上下文到系统提示
            if self.is_executing_planned_task and self.planning_flow:
                try:
                    # 获取当前计划状态文本
                    plan_status = await self.planning_flow._get_plan_text()
                    current_step = self.planning_flow.current_step_index

                    # 创建规划上下文提示
                    planning_context = f"""
                    您正在执行一个任务计划中的第 {current_step} 步。

                    当前计划状态:
                    {plan_status}

                    请考虑当前任务计划的上下文，选择最适合完成当前步骤的行动。
                    只专注于完成当前步骤，不要尝试执行后续步骤。
                    完成当前步骤后，系统会自动为您安排下一个步骤。
                    """

                    # 将规划上下文添加到系统提示
                    self.system_prompt = (
                        f"{original_system_prompt}\n\n{planning_context}"
                    )
                    modified = True
                    logger.info(f"Manus: 添加规划上下文到系统提示")
                except Exception as e:
                    logger.warning(f"Manus: 添加规划上下文失败: {e}")

            # 2. 如果使用浏览器，设置浏览器上下文
            recent_messages = self.memory.messages[-3:] if self.memory.messages else []
            browser_in_use = any(
                tc.function.name == BrowserUseTool().name
                for msg in recent_messages
                if msg.tool_calls
                for tc in msg.tool_calls
            )

            if browser_in_use:
                self.next_step_prompt = (
                    await self.browser_context_helper.format_next_step_prompt()
                )
                modified = True

            # 调用父类的think方法
            result = await super().think()

            return result
        finally:
            # 恢复原始提示
            if modified:
                self.next_step_prompt = original_prompt
                self.system_prompt = original_system_prompt

    async def cleanup(self):
        """Clean up Manus agent resources."""
        if self.browser_context_helper:
            await self.browser_context_helper.cleanup_browser()
