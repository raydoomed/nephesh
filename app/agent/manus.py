from typing import ClassVar, Dict, List, Optional

from pydantic import Field, model_validator

from app.agent.browser import BrowserContextHelper
from app.agent.toolcall import ToolCallAgent
from app.config import config
from app.evaluation.self_evaluation import SelfEvaluator
from app.flow.flow_factory import FlowFactory, FlowType
from app.flow.planning import PlanningFlow
from app.logger import logger
from app.optimization.task_optimizer import TaskOptimizer
from app.prompt.manus import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.schema import Message
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
        default=5, description="Maximum steps allowed for task execution"
    )
    continuation_mode: bool = Field(
        default=True,
        description="Whether to allow task execution to continue after reaching max steps",
    )

    # 记忆压缩和摘要相关参数
    use_llm_summary: bool = Field(
        default=True, description="是否使用LLM生成更智能的对话摘要，而不是简单拼接"
    )
    summarize_after_steps: int = Field(
        default=3, description="执行多少步骤后触发一次智能摘要"
    )
    steps_since_last_summary: int = Field(
        default=0, description="自上次摘要后执行的步骤数"
    )

    # 自我评估和优化相关参数
    use_self_evaluation: bool = Field(default=True, description="是否启用自我评估功能")
    enable_auto_improvement: bool = Field(
        default=True, description="是否启用自动改进功能"
    )
    subtask_evaluation_enabled: bool = Field(
        default=True, description="是否启用子任务评估和重试功能"
    )
    subtask_quality_threshold: float = Field(
        default=8, description="子任务质量阈值，高于此值才算通过"
    )
    subtask_max_retries: int = Field(default=0, description="子任务最大重试次数")
    max_improvement_iterations: int = Field(
        default=1, description="最大自动改进迭代次数"
    )
    improvement_quality_threshold: float = Field(
        default=8, description="改进质量阈值，高于此值则不再继续改进"
    )

    # 提示模板
    STEP_LIMIT_TEMPLATE: ClassVar[
        str
    ] = """
{prompt}

注意：你可以在最多{max_steps}步内完成此任务。
请高效规划你的行动，每一步都要有实质性进展。
如果任务已经实质性完成，无需强制执行所有步骤，可以直接使用terminate工具提前结束任务。
"""

    URGENT_TEMPLATE: ClassVar[
        str
    ] = """
当前已执行{current_step}步，最多允许{max_steps}步！
剩余步数: {remaining_steps}步，请注意规划剩余步骤，高效完成当前任务。
"""

    # 子任务重试模板
    SUBTASK_RETRY_TEMPLATE: ClassVar[
        str
    ] = """
之前的执行结果未达到质量标准，评估分数: {score}/{threshold}
评估发现以下问题:
{issues}

请重新执行原始任务，注意解决上述问题:
{original_task}

这是第 {retry_count}/{max_retries} 次尝试，请务必提高质量。
"""

    # 摘要提示模板
    SUMMARY_PROMPT_TEMPLATE: ClassVar[
        str
    ] = """
请对以下对话内容生成简洁而全面的摘要，包含关键信息点、决策和重要的上下文：

{conversation}

摘要应当:
1. 包含用户的需求和目标
2. 记录已经完成的工作和取得的进展
3. 突出当前工作的状态和下一步计划
4. 保留任何技术细节、代码片段的关键设计决策
5. 简明扼要，具有逻辑连贯性
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

    # 自我评估和优化组件
    evaluator: Optional[SelfEvaluator] = None
    optimizer: Optional[TaskOptimizer] = None

    # 工具使用统计
    tool_usage_stats: Dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def initialize_helper(self) -> "Manus":
        """初始化各组件"""
        # 初始化浏览器上下文助手
        self.browser_context_helper = BrowserContextHelper(self)

        # 初始化评估器和优化器
        if self.use_self_evaluation:
            # 确保评估器和优化器都被初始化
            logger.info("Manus: 初始化评估和优化组件...")
            self.evaluator = SelfEvaluator(self.llm)
            self.optimizer = TaskOptimizer(self.llm)

            # 记录子任务评估设置
            if self.subtask_evaluation_enabled:
                logger.info(
                    f"Manus: 子任务评估已启用，质量阈值: {self.subtask_quality_threshold}，最大重试次数: {self.subtask_max_retries}"
                )
            else:
                logger.info("Manus: 子任务评估已禁用")
        else:
            logger.info("Manus: 自我评估功能已禁用")

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
        # 清空工具使用统计
        self.tool_usage_stats = {}

        # 保存原始输入，用于后续评估
        original_task = input_text

        # 重置智能摘要步骤计数器
        self.steps_since_last_summary = 0

        # 如果代理正在执行规划任务中的一个步骤，则使用正常流程
        if self.is_executing_planned_task:
            result = await super().run(input_text)
            return result

        # 检查是否需要进行记忆压缩和智能摘要
        # 对于新任务，只有在记忆中已经有大量历史对话时才进行压缩
        if (
            hasattr(self.memory, "compress_memory")
            and len(self.memory.messages)
            > getattr(self.memory, "compression_threshold", 20) * 1.5
        ):

            logger.info(
                f"Manus: 新任务开始前优化历史记忆，当前消息数: {len(self.memory.messages)}"
            )

            # 新任务开始前，如果有足够的历史记忆，使用LLM生成更高质量的摘要
            if self.use_llm_summary and hasattr(self.memory, "generate_llm_summary"):
                # 只对较旧的消息生成摘要，保留最新的一部分对话作为上下文
                to_summarize = (
                    self.memory.messages[:-15] if len(self.memory.messages) > 20 else []
                )

                if to_summarize:
                    # 使用LLM生成智能摘要
                    summary_text = await self.generate_intelligent_summary(to_summarize)

                    # 临时调整压缩参数
                    original_ratio = self.memory.compression_ratio
                    original_threshold = self.memory.compression_threshold

                    self.memory.compression_ratio = (
                        0.3  # 更激进的压缩，只保留30%的最新消息
                    )
                    self.memory.compression_threshold = 0  # 确保一定执行压缩

                    # 手动设置摘要内容
                    if len(to_summarize) > 0:
                        import time

                        self.memory.summaries.append(
                            {
                                "start_idx": 0,
                                "end_idx": len(to_summarize) - 1,
                                "content": summary_text,
                                "timestamp": time.time(),
                            }
                        )

                        # 更新消息列表，保留系统消息和最新消息
                        system_messages = [
                            msg for msg in to_summarize if msg.role == "system"
                        ]
                        self.memory.messages = (
                            system_messages + self.memory.messages[-15:]
                        )
                        self.memory.last_compression_size = len(self.memory.messages)

                    # 恢复原始参数
                    self.memory.compression_ratio = original_ratio
                    self.memory.compression_threshold = original_threshold

                    logger.info(
                        f"Manus: 新任务开始前完成智能记忆压缩，保留消息数: {len(self.memory.messages)}"
                    )
            else:
                # 使用默认压缩
                self.memory.compress_memory()

        # 创建规划流程并执行
        logger.info(f"Manus: 为任务创建执行计划 - {input_text[:50]}...")
        self.planning_flow = self.create_planning_flow()

        # 启用子任务评估功能
        prev_subtask_eval_setting = self.subtask_evaluation_enabled
        if self.use_self_evaluation and not self.subtask_evaluation_enabled:
            logger.info("Manus: 临时启用子任务评估功能")
            self.subtask_evaluation_enabled = True

        # 执行规划流程
        try:
            result = await self.planning_flow.execute(input_text)
            logger.info("Manus: 任务规划执行完成")

            # 执行最终的评估但不进行自动改进
            if self.use_self_evaluation and self.evaluator:
                logger.info("Manus: 执行最终任务评估...")
                final_evaluation = await self.evaluator.evaluate_task(
                    original_task=original_task,
                    task_output=result,
                    step_count=self.current_step,
                    tools_used=self.tool_usage_stats,
                )

                logger.info(f"Manus: 最终评估分数: {final_evaluation.score}/10")
                if final_evaluation.issues:
                    issue_summary = "\n".join(
                        [f"- {issue.issue}" for issue in final_evaluation.issues[:3]]
                    )
                    logger.info(f"Manus: 评估发现的主要问题:\n{issue_summary}")

                # 添加评估结果到最终输出
                evaluation_suffix = f"\n\n任务质量评估: {final_evaluation.score}/10"
                if final_evaluation.issues and len(final_evaluation.issues) > 0:
                    evaluation_suffix += "\n主要问题:"
                    for i, issue in enumerate(final_evaluation.issues[:3]):
                        evaluation_suffix += f"\n{i+1}. {issue.issue}"

                # 在最终输出中附加评估结果
                result += evaluation_suffix

            return result
        finally:
            # 恢复子任务评估设置
            self.subtask_evaluation_enabled = prev_subtask_eval_setting

            # 确保执行后重置状态
            self.is_executing_planned_task = False
            logger.info("Manus: 重置执行状态")

    async def generate_intelligent_summary(self, messages: List[Message]) -> str:
        """使用LLM生成智能对话摘要

        Args:
            messages: 要摘要的消息列表

        Returns:
            生成的摘要文本
        """
        if not messages:
            return "没有需要摘要的内容"

        try:
            # 准备对话内容
            formatted_messages = []
            for msg in messages:
                if (
                    isinstance(msg.content, str) and msg.content
                ):  # 确保content是字符串且不为空
                    role_str = (
                        "用户"
                        if msg.role == "user"
                        else "助手" if msg.role == "assistant" else msg.role
                    )
                    formatted_messages.append(f"{role_str}: {msg.content}")

            conversation_text = "\n".join(formatted_messages)

            # 使用模板格式化摘要提示
            summary_prompt = self.SUMMARY_PROMPT_TEMPLATE.format(
                conversation=conversation_text
            )

            # 创建提示消息
            system_msg = Message.system_message(
                "你是一个专业的对话摘要助手，你的任务是生成简洁但信息完整的对话摘要。"
            )
            user_msg = Message.user_message(summary_prompt)

            # 获取摘要
            logger.info(f"Manus: 使用LLM生成智能摘要，处理消息数: {len(messages)}")
            response = await self.llm.ask([system_msg, user_msg])

            # 处理LLM返回结果，支持字符串和对象两种可能的返回类型
            response_content = ""
            if response is None:
                logger.warning("Manus: LLM摘要生成失败，返回None，回退到简单摘要")
                return self._generate_simple_summary(messages)
            elif isinstance(response, str):
                # 直接使用字符串
                response_content = response
            elif hasattr(response, "content"):
                # 对象有content属性
                content = response.content
                # 检查content类型
                if isinstance(content, list):
                    response_content = "\n".join(content)
                elif isinstance(content, dict):
                    # 如果是字典，转换为JSON字符串
                    try:
                        import json

                        response_content = json.dumps(
                            content, ensure_ascii=False, indent=2
                        )
                    except:
                        response_content = str(content)
                else:
                    response_content = content
            else:
                # 尝试转换为字符串
                try:
                    response_content = str(response)
                except:
                    logger.warning("Manus: 无法解析LLM摘要响应，回退到简单摘要")
                    return self._generate_simple_summary(messages)

            if response_content:
                logger.info(f"Manus: 成功生成智能摘要: {response_content[:100]}...")
                return response_content

            logger.warning("Manus: LLM摘要生成失败，回退到简单摘要")
            return self._generate_simple_summary(messages)
        except Exception as e:
            logger.error(f"Manus: 生成LLM摘要出错: {e}")
            return self._generate_simple_summary(messages)

    def _generate_simple_summary(self, messages: List[Message]) -> str:
        """生成简单的对话摘要，当LLM摘要失败时使用

        Args:
            messages: 要摘要的消息列表

        Returns:
            生成的摘要文本
        """
        summary_lines = []
        for i, msg in enumerate(messages):
            if (
                isinstance(msg.content, str) and msg.content
            ):  # 确保content是字符串且不为空
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
            此方法增加了子任务评估功能，子任务质量达标才能继续下一步骤
            子任务质量未达标时会自动重试，直到达到最大重试次数
        """
        # 设置执行状态和上下文
        self.is_executing_planned_task = True

        # 重置步骤计数器，确保每个计划步骤有独立的步数限制
        self.current_step = 0
        self.steps_since_last_summary += 1

        # 保存当前规划流程和步骤索引，以便think方法使用
        if planning_flow:
            self.planning_flow = planning_flow

        # 检查是否需要进行记忆压缩和智能摘要
        if hasattr(self.memory, "compress_memory") and len(
            self.memory.messages
        ) > getattr(self.memory, "compression_threshold", 20):

            logger.info(
                f"Manus: 步骤执行前优化记忆，当前消息数: {len(self.memory.messages)}"
            )

            # 如果开启智能摘要且已经执行了足够的步骤，使用LLM生成摘要
            if (
                self.use_llm_summary
                and self.steps_since_last_summary >= self.summarize_after_steps
                and hasattr(self.memory, "generate_llm_summary")
            ):

                # 要摘要的消息范围，排除最新的几条
                to_summarize = (
                    self.memory.messages[:-10] if len(self.memory.messages) > 10 else []
                )

                if to_summarize:
                    logger.info(
                        f"Manus: 触发智能摘要生成，处理消息数: {len(to_summarize)}"
                    )

                    # 使用Manus的摘要方法生成
                    summary_text = await self.generate_intelligent_summary(to_summarize)

                    # 设置到Memory中
                    original_ratio = self.memory.compression_ratio
                    self.memory.compression_ratio = 0.4  # 更激进的压缩比例

                    # 保存当前压缩阈值
                    compression_threshold = self.memory.compression_threshold
                    # 临时降低压缩阈值，确保一定执行压缩
                    self.memory.compression_threshold = 0

                    # 手动设置摘要内容
                    if len(to_summarize) > 0:
                        import time

                        self.memory.summaries.append(
                            {
                                "start_idx": 0,
                                "end_idx": len(to_summarize) - 1,
                                "content": summary_text,
                                "timestamp": time.time(),
                            }
                        )

                        # 更新消息列表，保留系统消息和最新消息
                        system_messages = [
                            msg for msg in to_summarize if msg.role == "system"
                        ]
                        self.memory.messages = (
                            system_messages + self.memory.messages[-10:]
                        )
                        self.memory.last_compression_size = len(self.memory.messages)

                    # 恢复原始压缩比例和阈值
                    self.memory.compression_ratio = original_ratio
                    self.memory.compression_threshold = compression_threshold

                    # 重置步骤计数
                    self.steps_since_last_summary = 0

                    logger.info(
                        f"Manus: 智能记忆压缩完成，保留消息数: {len(self.memory.messages)}"
                    )
            else:
                # 使用常规压缩
                self.memory.compress_memory()

        # 添加步骤限制提示，使用模板
        step_prompt = self.STEP_LIMIT_TEMPLATE.format(
            prompt=step_prompt, max_steps=self.max_steps
        )

        # 记录正在执行的步骤
        logger.info(f"Manus: 执行计划步骤 {current_step_index} - {step_prompt[:50]}...")

        try:
            # 检查是否启用了子任务评估
            if (
                not self.subtask_evaluation_enabled
                or not self.use_self_evaluation
                or not self.evaluator
            ):
                # 未启用子任务评估，直接执行一次并返回结果
                result = await super().run(step_prompt)
                logger.info(
                    f"Manus: 步骤 {current_step_index} 执行完成 (未启用子任务评估)"
                )
                return result

            # 使用自我评估和优化来执行子任务，直到达到质量标准
            retry_count = 0
            current_result = None
            evaluation = None
            improvement_plan = None

            # 使用配置参数
            quality_threshold = self.subtask_quality_threshold
            max_retries = self.subtask_max_retries

            # 首次执行
            result = await super().run(step_prompt)
            logger.info(f"Manus: 步骤 {current_step_index} 首次执行完成")
            current_result = result

            # 评估当前子任务结果
            evaluation = await self.evaluator.evaluate_task(
                original_task=step_prompt,
                task_output=result,
                step_count=self.current_step,
                tools_used=self.tool_usage_stats,
            )

            # 打印评估结果
            logger.info(f"Manus: 子任务评估分数: {evaluation.score}/10")

            # 使用安全的方式检查task_complete属性
            task_complete = False
            if hasattr(evaluation, "metadata"):
                task_complete = evaluation.metadata.get("task_complete", False)

            # 如果质量已达标，直接返回结果
            if evaluation.score >= quality_threshold:
                logger.info(f"Manus: 子任务质量达标，继续下一步骤")

                # 添加系统消息，表示质量达标
                self.update_memory(
                    "system",
                    f"子任务质量评估: {evaluation.score}/10，已达到标准 {quality_threshold}。",
                )

                # 安全检查task_complete
                if task_complete:
                    self.update_memory(
                        "system",
                        "任务已实质完成，考虑使用terminate工具提前结束剩余步骤。",
                    )

                return current_result

            # 质量未达标，尝试进行一次基本改进（无论max_retries设置如何）
            if self.optimizer and self.enable_auto_improvement:
                logger.info(f"Manus: 尝试使用优化器为子任务生成改进计划...")
                max_iterations = self.max_improvement_iterations

                # 生成改进计划
                if improvement_plan is None and max_iterations > 0:
                    improvement_plan = await self.optimizer.create_improvement_plan(
                        evaluation=evaluation,
                        original_task=step_prompt,
                        task_output=result,
                    )

                    if improvement_plan:
                        logger.info(f"Manus: 成功生成子任务改进计划")

                        # 添加系统消息，包含改进计划
                        self.update_memory(
                            "system",
                            (
                                f"子任务改进计划:\n{improvement_plan[:500]}..."
                                if len(improvement_plan) > 500
                                else improvement_plan
                            ),
                        )

                        # 使用改进计划执行一次改进（无论max_retries如何）
                        retry_prompt = f"""
根据执行的评估结果，需要改进当前步骤的质量，请按照以下改进计划执行：

{improvement_plan}

原始任务:
{step_prompt}

请务必按照改进计划提高质量。
"""
                        result = await super().run(retry_prompt)
                        current_result = result

                        # 再次评估改进后的结果
                        evaluation = await self.evaluator.evaluate_task(
                            original_task=step_prompt,
                            task_output=result,
                            step_count=self.current_step,
                            tools_used=self.tool_usage_stats,
                        )

                        logger.info(
                            f"Manus: 改进后子任务评估分数: {evaluation.score}/10"
                        )

                        # 如果改进后质量达标，返回结果
                        if evaluation.score >= quality_threshold:
                            logger.info(f"Manus: 改进后子任务质量达标，继续下一步骤")
                            self.update_memory(
                                "system",
                                f"改进后子任务质量评估: {evaluation.score}/10，已达到标准 {quality_threshold}。",
                            )
                            return current_result
                    else:
                        logger.warning(f"Manus: 未能生成有效的改进计划")

            # 如果max_retries=0，质量未达标但不进行重试
            if max_retries == 0:
                logger.warning(
                    f"Manus: 子任务 {current_step_index} 质量未达标 ({evaluation.score}/{quality_threshold})，"
                    f"但重试已禁用(max_retries=0)，将继续下一步骤"
                )

                # 添加系统消息
                self.update_memory(
                    "system",
                    f"警告: 子任务质量未达标 ({evaluation.score}/{quality_threshold})，"
                    f"但重试已禁用(max_retries=0)。将继续下一步骤。",
                )

                return current_result

            # 启用重试机制 (只有当max_retries > 0时)
            retry_count = 1  # 已经执行过一次改进，从1开始计数

            # 重试循环
            while retry_count <= max_retries:
                # 使用改进计划或重试模板
                if improvement_plan:
                    # 使用生成的改进计划作为新的执行指令
                    logger.info(
                        f"Manus: 步骤 {current_step_index} 使用改进计划重试 ({retry_count}/{max_retries})"
                    )
                    retry_prompt = f"""
根据上次执行的评估结果，需要改进当前步骤的质量，请按照以下改进计划执行：

{improvement_plan}

原始任务:
{step_prompt}

这是第 {retry_count}/{max_retries} 次重试，请务必按照改进计划提高质量。
"""
                    result = await super().run(retry_prompt)
                else:
                    # 没有改进计划，使用标准重试模板
                    # 准备问题列表
                    issues_text = (
                        "\n".join(
                            [
                                f"- {issue.issue} ({issue.severity}): {issue.suggestion}"
                                for issue in evaluation.issues
                            ]
                        )
                        if evaluation and evaluation.issues
                        else "未提供具体问题"
                    )

                    # 使用模板格式化重试提示
                    retry_prompt = self.SUBTASK_RETRY_TEMPLATE.format(
                        score=evaluation.score if evaluation else "未知",
                        threshold=quality_threshold,
                        issues=issues_text,
                        original_task=step_prompt,
                        retry_count=retry_count,
                        max_retries=max_retries,
                    )

                    # 执行重试
                    result = await super().run(retry_prompt)

                logger.info(
                    f"Manus: 步骤 {current_step_index} 第{retry_count}次重试执行完成"
                )

                current_result = result

                # 评估当前子任务结果
                evaluation = await self.evaluator.evaluate_task(
                    original_task=step_prompt,
                    task_output=result,
                    step_count=self.current_step,
                    tools_used=self.tool_usage_stats,
                )

                # 打印评估结果
                logger.info(f"Manus: 重试后子任务评估分数: {evaluation.score}/10")

                if evaluation.score >= quality_threshold:
                    logger.info(f"Manus: 重试后子任务质量达标，继续下一步骤")

                    # 添加系统消息，表示质量达标
                    self.update_memory(
                        "system",
                        f"重试后子任务质量评估: {evaluation.score}/10，已达到标准 {quality_threshold}。",
                    )
                    break

                # 检查是否达到最大重试次数
                if retry_count >= max_retries:
                    logger.warning(
                        f"Manus: 子任务 {current_step_index} 达到最大重试次数 {max_retries}，"
                        f"但质量仍未达标 ({evaluation.score}/{quality_threshold})，将继续下一步骤"
                    )

                    # 添加系统消息，表示强制继续
                    self.update_memory(
                        "system",
                        f"警告: 已达到最大重试次数 {max_retries}，但子任务质量仍未达标 "
                        f"({evaluation.score}/{quality_threshold})。将强制进入下一步骤。",
                    )
                    break

                # 增加重试计数
                retry_count += 1

                # 添加系统消息，说明需要重试
                self.update_memory(
                    "system",
                    f"子任务质量评估: {evaluation.score}/10，未达到标准 {quality_threshold}，"
                    f"将进行第 {retry_count}/{max_retries} 次重试。",
                )

                # 尝试生成新的改进计划
                if self.optimizer and self.enable_auto_improvement:
                    if retry_count <= self.max_improvement_iterations:
                        # 生成新的改进计划
                        improvement_plan = await self.optimizer.create_improvement_plan(
                            evaluation=evaluation,
                            original_task=step_prompt,
                            task_output=result,
                        )

                        if improvement_plan:
                            logger.info(f"Manus: 成功生成子任务新改进计划")
                        else:
                            logger.warning(f"Manus: 未能生成有效的新改进计划")

            # 返回最终结果
            return current_result
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
                    如果您认为任务已经实质性完成，可以使用terminate工具提前结束任务，而不必执行剩余步骤。
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

    async def act(self) -> bool:
        """执行动作，选择和使用工具。
        重写此方法以记录工具使用情况。
        """
        result = await super().act()

        # 记录工具使用情况
        if hasattr(self, "last_tool_call") and self.last_tool_call:
            tool_name = self.last_tool_call.function.name
            self.tool_usage_stats[tool_name] = (
                self.tool_usage_stats.get(tool_name, 0) + 1
            )

        return result

    async def cleanup(self):
        """Clean up Manus agent resources."""
        # 记录记忆统计信息
        if hasattr(self.memory, "summaries"):
            summary_count = len(self.memory.summaries)
            message_count = len(self.memory.messages)
            compression_ratio = getattr(self.memory, "compression_ratio", 0.5)

            logger.info(
                f"Manus: 记忆统计 - 消息数: {message_count}, "
                f"摘要数: {summary_count}, 压缩比例: {compression_ratio}"
            )

            if summary_count > 0:
                # 记录最新摘要
                latest_summary = self.memory.summaries[-1]["content"]
                summary_preview = (
                    latest_summary[:100] + "..."
                    if len(latest_summary) > 100
                    else latest_summary
                )
                logger.info(f"Manus: 最新记忆摘要: {summary_preview}")

        # 记录自我评估统计信息
        if self.evaluator and hasattr(self.evaluator, "evaluation_history"):
            eval_count = len(self.evaluator.evaluation_history)
            if eval_count > 0:
                avg_score = self.evaluator.get_average_score()
                logger.info(
                    f"Manus: 评估统计 - 评估次数: {eval_count}, 平均评分: {avg_score:.2f}"
                )

        # 清理浏览器资源
        if self.browser_context_helper:
            await self.browser_context_helper.cleanup_browser()

        logger.info("Manus: 资源清理完成")
