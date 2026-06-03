"""翻译专员——负责多语言翻译和本地化"""

from .base import BaseAgent


TRANSLATE_SYSTEM_PROMPT = """你是一名专业的翻译和本地化专家。
你的任务是根据需求进行高质量翻译。

翻译原则：
1. 准确传达原文含义，不增不减
2. 符合目标语言的语言习惯，不僵硬直译
3. 保持原文的风格和语气（正式/口语/文学/技术）
4. 专业术语要准确，必要时加注

如果用户没有指定目标语言，默认翻译成英文。
输出时先给出译文，可在末尾加简短翻译说明。
"""


class TranslateAgent(BaseAgent):
    """翻译专员——负责多语言翻译"""

    def __init__(self, context):
        super().__init__(
            name="翻译专员",
            description="负责多语言翻译和本地化。擅长：中译英、英译中、技术文档翻译、文学翻译",
            context=context,
            capabilities=[
                "翻译", "译", "translate", "英文", "英语", "中文",
                "本地化", "多语言", "语言",
            ],
        )

    async def execute(self, task: str, **kwargs) -> str:
        await self.broadcast(f"🌐 正在翻译：{task[:50]}...")

        result = await self.call_llm(
            system_prompt=TRANSLATE_SYSTEM_PROMPT,
            user_prompt=f"请完成以下翻译任务：\n\n{task}",
        )

        self._bus.record_result(self.name, result)
        await self.broadcast(f"✅ 翻译完成，共 {len(result)} 字符")

        return result
