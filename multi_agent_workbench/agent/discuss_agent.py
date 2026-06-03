"""讨论 Agent——团队讨论的协调者和主持人

在讨论阶段，每个 Agent 会独立审阅成果并从自己的专业角度给出反馈。
讨论专员（本 Agent）负责主持讨论、归纳各方意见、给出综合结论。
"""

from .base import BaseAgent


MODERATOR_SYSTEM_PROMPT = """你是一个优秀的团队讨论主持人。

你的团队刚刚完成了一个协作任务。现在你要：
1. 听取各位团队成员的审阅意见
2. 归纳各方反馈的要点
3. 综合各位专家意见，给出最终改进建议

请以主持人的身份，输出一份结构清晰的讨论总结。
"""


REVIEW_SYSTEM_PROMPT_TEMPLATE = """你是一个{role}。

现在请你从你的专业角度，审阅团队刚刚完成的协作成果。

请关注：
1. 成果中与你专业相关的部分质量如何？
2. 有没有专业性的错误或不足？
3. 有哪些可以改进的具体建议？

请输出你的审阅意见（200字以内），要专业、具体、有建设性。
如果你觉得成果在你专业领域内没有问题，说"没有修改意见"即可。
"""


class DiscussAgent(BaseAgent):
    """讨论专员——主持团队讨论，收集各方反馈"""

    def __init__(self, context):
        super().__init__(
            name="讨论专员",
            description="团队讨论主持人，负责收集各方反馈、归纳意见、给出总结建议。擅长：组织讨论、归纳总结、冲突协调",
            context=context,
            capabilities=["讨论", "反馈", "建议", "头脑风暴", "整合意见", "归纳"],
        )

    async def execute(self, task: str, **kwargs) -> str:
        draft = kwargs.get("draft", "")
        reviewer_name = kwargs.get("reviewer_name", "")
        original_task = kwargs.get("original_task", task)

        round_context = kwargs.get("round_context", "")
        response_to = kwargs.get("response_to", "")

        await self.broadcast(f"💬 {reviewer_name} 正在审阅成果...")

        # 每个 Agent 的专属审阅 Prompt
        role_desc = self._get_reviewer_role(reviewer_name)

        user_content = f"## 原始任务\n{original_task}\n\n## 团队成果\n{draft}"

        # 多轮讨论：追加上下文
        if round_context:
            user_content += f"\n\n## 主持人提出的讨论要点\n{round_context}"
        if response_to:
            user_content += f"\n\n请针对以上讨论要点给出你的回应。"

        feedback = await self.call_llm(
            system_prompt=REVIEW_SYSTEM_PROMPT_TEMPLATE.format(role=role_desc),
            user_prompt=user_content,
        )

        self._bus.record_result(f"{reviewer_name}_feedback", feedback)
        await self.broadcast(f"💬 {reviewer_name} 审阅完毕 ✓")

        return feedback

    def _get_reviewer_role(self, name: str) -> str:
        """获取 Agent 的专业角色描述"""
        roles = {
            "搜索专员": "信息搜索和资料整理专家，对信息的准确性和全面性敏感",
            "写作专员": "内容创作和文字表达专家，关注文章结构、语言表达和可读性",
            "总结专员": "质量审核和总结专家，把关整体质量、逻辑性和完整性",
            "编程专员": "编程和技术实现专家，关注技术方案的可行性和代码质量",
            "翻译专员": "语言翻译和本地化专家，关注翻译准确性和语言自然度",
            "讨论专员": "团队协作和流程管理专家，关注多方意见整合",
        }
        return roles.get(name, f"{name}领域的专家")

    async def moderate(self, task: str, draft: str, feedbacks: list[tuple[str, str]],
                       round_type: str = "summarize",
                       history: list | None = None) -> str:
        """主持讨论——汇总反馈，或深入探讨（支持多轮）

        Args:
            task: 原始任务
            draft: 被讨论的成果
            feedbacks: [(agent_name, feedback_text), ...]
            round_type: "summarize" | "deep_dive" | "final_summary"
            history: 之前所有轮次的讨论记录

        Returns:
            讨论总结或下一轮的讨论要点
        """
        feedback_text = "\n\n".join([
            f"### {name} 的审阅意见\n{fb}"
            for name, fb in feedbacks
        ])

        if round_type == "deep_dive":
            # 主持人找出分歧点，提出深入讨论的问题
            prompt = MODERATOR_SYSTEM_PROMPT + "\n\n现在是讨论的深入阶段。请根据各方意见，找出需要进一步讨论的分歧点或改进点，提出 2-3 个具体问题让各位专家回应。"
            user = f"""## 原始任务\n{task}

## 成果\n{draft[:2000]}

## 各方意见\n{feedback_text}

请找出分歧点，提出需要深入讨论的问题。"""
        elif round_type == "final_summary":
            # 最终总结，综合所有轮次
            all_history = ""
            if history:
                for i, round_fb in enumerate(history, 1):
                    all_history += f"\n--- 第{i}轮讨论 ---\n"
                    for name, fb in round_fb:
                        all_history += f"{name}: {fb[:200]}\n"

            prompt = MODERATOR_SYSTEM_PROMPT
            user = f"""## 原始任务\n{task}

## 全部讨论记录\n{all_history}

## 最新一轮意见\n{feedback_text}

请综合所有讨论，给出最终的改进方案和总结。"""
        else:
            prompt = MODERATOR_SYSTEM_PROMPT
            user = f"## 原始任务\n{task}\n\n## 成果\n{draft[:2000]}\n\n## 各方意见\n{feedback_text}\n\n请归纳各方意见并给出综合改进建议。"

        return await self.call_llm(system_prompt=prompt, user_prompt=user)
