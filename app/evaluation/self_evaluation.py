"""
Self-evaluation module for Manus agent.
Provides functionality to evaluate task execution quality and identify improvement opportunities.
"""

import json
import time
from enum import Enum
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field, field_validator

from app.llm import LLM
from app.logger import logger
from app.schema import Message


class IssueSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IssueDetail(BaseModel):
    issue: str = Field(..., description="描述发现的问题")
    severity: IssueSeverity = Field(..., description="问题的严重程度")
    suggestion: str = Field("", description="改进建议")


class EvaluationResult(BaseModel):
    """评估结果模型"""

    score: float = Field(..., description="评估得分，范围0-10")
    issues: List[IssueDetail] = Field(
        default_factory=list, description="发现的问题列表"
    )
    action_needed: str = Field(
        "none", description="需要采取的行动: none, modify, restart"
    )
    action_details: Dict[str, Any] = Field(
        default_factory=dict, description="行动详情，包含步骤和工具建议"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="评估元数据，如任务完成状态等"
    )

    @field_validator("score")
    def validate_score(cls, value: float) -> float:
        if not (0 <= value <= 10):
            raise ValueError("评分必须在0-10之间")
        return round(value, 1)  # 保留一位小数


class SelfEvaluator:
    """自我评估器，对任务执行结果进行质量评估"""

    def __init__(self, llm: LLM):
        self.llm = llm
        self.evaluation_history: List[EvaluationResult] = []

    def get_average_score(self) -> float:
        """获取历史评估的平均分数"""
        if not self.evaluation_history:
            return 0.0
        return sum(e.score for e in self.evaluation_history) / len(
            self.evaluation_history
        )

    EVALUATION_PROMPT = """请评估执行结果的质量和完整度，返回一个0-10分的评分和详细分析。
请按以下维度评估:
1. 任务完成度 - 原始任务目标实现程度
2. 输出质量 - 结果的准确性和可用性
3. 执行效率 - 步骤是否简洁、必要
4. 异常处理 - 是否妥善处理了错误情况
5. 用户体验 - 输出对用户是否友好

原始任务:
{original_task}

执行结果:
{task_output}

步骤数: {step_count}
使用的工具: {tools_used}

请使用以下JSON格式返回评估结果:

```json
{{
  "score": 评分(0-10),
  "issues": [
    {{
      "issue": "发现的问题1",
      "severity": "low|medium|high|critical",
      "suggestion": "改进建议"
    }},
    ...
  ],
  "action_needed": "none|modify|restart",
  "action_details": {{
    "steps": ["具体修改步骤1", "步骤2", ...],
    "tools": ["建议使用的工具1", "工具2", ...]
  }},
  "metadata": {{
    "task_complete": true|false,
    "additional_info": "其他相关信息"
  }}
}}
```

请确保JSON格式正确，并根据问题的严重程度给出详细的改进建议。
"""

    async def evaluate_task(
        self,
        original_task: str,
        task_output: str,
        step_count: int,
        tools_used: Dict[str, int],
    ) -> EvaluationResult:
        """评估任务执行结果

        Args:
            original_task: 原始任务描述
            task_output: 任务执行结果
            step_count: 执行步骤数
            tools_used: 使用的工具及次数

        Returns:
            评估结果
        """
        logger.info("SelfEvaluator: 执行任务评估...")

        # 格式化工具使用情况
        tools_used_str = ", ".join(
            [f"{tool}({count}次)" for tool, count in tools_used.items()]
        )
        if not tools_used_str:
            tools_used_str = "无"

        # 构建评估提示
        prompt = self.EVALUATION_PROMPT.format(
            original_task=original_task,
            task_output=task_output,
            step_count=step_count,
            tools_used=tools_used_str,
        )

        # 创建消息
        system_message = Message.system_message(
            "你是一个专业的任务质量评估助手，你的任务是客观评估AI执行结果的质量。"
        )
        user_message = Message.user_message(prompt)

        # 获取评估结果
        response = await self.llm.ask([system_message, user_message])

        # 解析评估结果
        evaluation_result = self._parse_evaluation_response(response)

        # 添加到历史记录
        self.evaluation_history.append(evaluation_result)

        # 输出评估结果
        logger.info(
            f"SelfEvaluator: 评估完成，分数: {evaluation_result.score}，问题数量: {len(evaluation_result.issues)}"
        )

        return evaluation_result

    def _parse_evaluation_response(self, response: str) -> EvaluationResult:
        """解析LLM的评估响应

        Args:
            response: LLM的响应文本

        Returns:
            解析后的评估结果
        """
        try:
            # 提取JSON部分
            import json
            import re

            # 寻找JSON块
            json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 尝试直接解析为JSON
                json_str = response

            # 解析JSON
            data = json.loads(json_str)

            # 创建问题列表
            issues = []
            if "issues" in data and data["issues"]:
                for issue_data in data["issues"]:
                    # 设置默认值并确保字段存在
                    severity = issue_data.get("severity", "medium")
                    if severity not in [e.value for e in IssueSeverity]:
                        severity = "medium"

                    issues.append(
                        IssueDetail(
                            issue=issue_data.get("issue", "未指定问题"),
                            severity=severity,
                            suggestion=issue_data.get("suggestion", ""),
                        )
                    )

            # 创建评估结果
            result = EvaluationResult(
                score=data.get("score", 5.0),  # 默认中等分数
                issues=issues,
                action_needed=data.get("action_needed", "none"),
                action_details=data.get("action_details", {}),
                metadata=data.get("metadata", {}),
            )

            return result
        except Exception as e:
            logger.error(f"解析评估响应失败: {e}")
            # 返回默认评估结果
            return EvaluationResult(
                score=5.0,
                issues=[
                    IssueDetail(
                        issue=f"无法解析评估结果: {str(e)}",
                        severity="high",
                        suggestion="请检查评估系统",
                    )
                ],
                metadata={"parse_error": True},
            )
