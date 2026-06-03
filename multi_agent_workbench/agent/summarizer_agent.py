"""总结 Agent——负责内容提炼、审核和改进（以成果为主，审校为辅）"""

from .base import BaseAgent


REVIEWER_SYSTEM_PROMPT = """你是团队中的质量把关人。你的任务是对已有内容进行审校和优化。

工作原则：
1. **以「改进后的完整版本」作为主要内容输出**，而不是输出审校报告
2. 审校意见（如果有）放在**末尾**作为简短的「💡 审校说明」，不要喧宾夺主
3. 如果内容质量已经很好，直接输出内容本身，不需要刻意找缺点

输出格式：
- 先输出改进后的最终版本（这是主体）
- 末尾可以加一段简短的「💡 审校说明」（可选），用 2-3 句话概括核心改动
- 不要输出「优点」「待改进」「建议」这种结构化的审校报告
"""


class SummarizerAgent(BaseAgent):
    """总结/审校 Agent（以成果输出为主）"""

    def __init__(self, context):
        super().__init__(
            name="总结专员",
            description="负责内容总结、质量审核和改进优化，以最终成果为主",
            context=context,
            capabilities=["总结", "审校", "审核", "质检", "提炼", "要点", "改进", "优化", " review", "检查", "校对"],
        )

    async def execute(self, task: str, **kwargs) -> str:
        original_task = kwargs.get("original_task", task)
        draft = kwargs.get("draft", "")

        await self.broadcast(f"📋 正在优化内容...")

        if draft:
            # 有草稿：审校并输出优化后的版本
            result = await self.call_llm(
                system_prompt=REVIEWER_SYSTEM_PROMPT,
                user_prompt=f"## 原始需求\n{original_task}\n\n## 待优化的内容\n{draft}\n\n请审校并输出改进后的最终版本。",
            )
            self._bus.record_result(self.name, result)
            await self.broadcast(f"✅ 内容优化完成")

        else:
            # 没有草稿：进行总结/提炼
            info = kwargs.get("info", task)
            result = await self.call_llm(
                system_prompt="提取关键信息，用简洁清晰的方式呈现。直接输出提炼后的内容。",
                user_prompt=f"请提炼以下信息的核心要点：\n\n{info}",
            )
            self._bus.record_result(self.name, result)
            await self.broadcast(f"✅ 提炼完成")

        return result
