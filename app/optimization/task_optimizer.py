"""
Task optimizer module for Manus agent.
Provides functionality to improve task execution based on evaluation results.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.evaluation.self_evaluation import EvaluationResult
from app.llm import LLM
from app.logger import logger
from app.schema import Message


class OptimizationPlan(BaseModel):
    """Represents a plan for task optimization."""

    action_type: str  # replan, retry, modify, external_help
    action_details: str
    target_issues: List[str]
    expected_improvements: List[str]


class TaskOptimizer:
    """任务优化器，基于评估结果生成改进计划"""

    def __init__(self, llm: LLM):
        """初始化任务优化器

        Args:
            llm: 语言模型实例
        """
        self.llm = llm

    IMPROVEMENT_PROMPT = """
作为AI任务优化专家，请根据以下评估结果，制定一个详细的改进计划，以提高任务执行质量：

原始任务:
{original_task}

当前执行结果:
{task_output}

评估分数: {score}/10

评估发现的问题:
{issues}

请制定一个结构化、具体且可执行的改进计划，包括:
1. 需要改进的具体内容(优先级排序)
2. 每一步的实施步骤和代码示例
3. 预期达到的效果

请确保改进计划可以解决评估中发现的所有问题，且能实质性提高任务质量分数。
返回格式化的计划，包含足够详细的说明和示例代码。
"""

    async def create_improvement_plan(
        self,
        evaluation: EvaluationResult,
        original_task: str,
        task_output: str,
    ) -> str:
        """创建任务改进计划

        Args:
            evaluation: 评估结果
            original_task: 原始任务
            task_output: 任务输出

        Returns:
            改进计划
        """
        logger.info("TaskOptimizer: 制定改进计划...")

        # 格式化问题列表
        issues_text = "\n".join(
            [
                f"- {issue.issue} ({issue.severity}): {issue.suggestion}"
                for issue in evaluation.issues
            ]
        )

        # 构建改进提示
        prompt = self.IMPROVEMENT_PROMPT.format(
            original_task=original_task,
            task_output=task_output,
            score=evaluation.score,
            issues=issues_text,
        )

        # 创建消息
        system_message = Message.system_message(
            "你是一个专业的AI任务优化专家，擅长分析问题并提供具体、可实施的改进方案。"
        )
        user_message = Message.user_message(prompt)

        # 使用LLM生成改进计划
        try:
            response = await self.llm.ask([system_message, user_message])

            # 处理响应
            improvement_plan = ""
            if isinstance(response, str):
                improvement_plan = response
            elif hasattr(response, "content"):
                improvement_plan = response.content
            else:
                try:
                    improvement_plan = str(response)
                except:
                    logger.error("TaskOptimizer: 无法解析响应")
                    return ""

            # 检查改进计划长度
            if len(improvement_plan) < 10:
                logger.warning("TaskOptimizer: 生成的改进计划太短或为空")
                return ""

            logger.info(
                f"TaskOptimizer: 改进计划生成完成，长度: {len(improvement_plan)}"
            )
            return improvement_plan

        except Exception as e:
            logger.error(f"TaskOptimizer: 生成改进计划失败: {e}")
            return ""

    async def execute_improvement(
        self, improvement_plan: str, original_task: str, current_result: str
    ) -> Optional[str]:
        """Execute the improvement plan to optimize the result.

        Args:
            improvement_plan: Improvement plan text
            original_task: The original task description
            current_result: The current task result

        Returns:
            Optional[str]: Improved result, or None if execution failed
        """
        if not improvement_plan:
            return None

        # Create execution prompt
        execution_prompt = self.IMPROVEMENT_PROMPT.format(
            original_task=original_task,
            task_output=current_result,
            score=0,
            issues="",
        )

        # Use LLM to execute improvement
        system_msg = Message.system_message(
            "你是专业的任务执行专家，擅长根据改进计划优化任务结果，确保高质量的输出。"
        )
        user_msg = Message.user_message(execution_prompt)

        try:
            # Get improved result from LLM
            logger.info("TaskOptimizer: 执行改进计划...")
            execution_response = await self.llm.ask([system_msg, user_msg])

            # 处理LLM返回结果，支持字符串和对象两种可能的返回类型
            improved_result = ""
            if execution_response is None:
                logger.error("TaskOptimizer: 执行改进计划失败，LLM返回None")
                return None
            elif isinstance(execution_response, str):
                # 直接返回字符串
                improved_result = execution_response
            elif hasattr(execution_response, "content"):
                # 对象有content属性
                content = execution_response.content
                # 检查content类型
                if isinstance(content, list):
                    improved_result = "\n".join(content)
                elif isinstance(content, dict):
                    # 如果是字典，转换为JSON字符串
                    try:
                        import json

                        improved_result = json.dumps(
                            content, ensure_ascii=False, indent=2
                        )
                    except:
                        improved_result = str(content)
                else:
                    improved_result = content
            else:
                # 尝试转换为字符串
                try:
                    improved_result = str(execution_response)
                except:
                    logger.error("TaskOptimizer: 无法解析LLM响应")
                    return None

            if not improved_result:
                logger.error("TaskOptimizer: 执行改进计划失败，LLM返回空响应")
                return None

            # Check if the result actually changed
            if improved_result.strip() == current_result.strip():
                logger.warning(
                    "TaskOptimizer: 改进后结果与原结果相同，未产生实质性改进"
                )
                return None

            logger.info(
                f"TaskOptimizer: 改进计划执行完成，结果长度: {len(improved_result)}"
            )
            return improved_result

        except Exception as e:
            logger.error(f"TaskOptimizer: 执行改进计划出错: {e}")
            return None
