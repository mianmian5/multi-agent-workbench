"""写作 Agent——负责内容创作和表达"""

from .base import BaseAgent


WRITER_SYSTEM_PROMPT = """你是一个专业的内容创作专家。
你的任务是根据提供的信息和需求，创作高质量的内容。

创作原则：
1. 内容要逻辑清晰、层次分明
2. 语言要生动但不浮夸
3. 适当使用例子、比喻帮助理解
4. 技术内容要准确，普通内容要有趣

写作流程：
1. 先理解输入的信息和写作要求
2. 确定文章结构和风格
3. 逐段创作
4. 最后通读检查

请直接输出最终内容，不需要额外说明。
"""


class WriterAgent(BaseAgent):
    """内容创作 Agent"""

    def __init__(self, context):
        super().__init__(
            name="写作专员",
            description="负责内容创作和表达优化。擅长：文章写作、文案创作、内容润色、故事构思",
            context=context,
            capabilities=["写作", "创作", "写", "文章", "文案", "内容", "故事", "小说", "润色", "改写", "摘要", "总结"],
        )

    async def execute(self, task: str, **kwargs) -> str:
        await self.broadcast(f"✍️ 开始创作：{task[:50]}...")

        # 收集所有参考素材
        search_result = kwargs.get("search_result", "")
        knowledge_ctx = kwargs.get("knowledge_context", "")

        user_content = f"## 写作任务\n{task}\n\n"
        if search_result:
            user_content += f"## 参考素材（搜索结果）\n{search_result}\n\n"
        if knowledge_ctx:
            await self.broadcast(f"📚 引用知识库资料作为参考...")
            user_content += f"## 参考素材（用户知识库）\n{knowledge_ctx[:3000]}\n\n"
        user_content += "请基于以上信息创作内容。"

        result = await self.call_llm(
            system_prompt=WRITER_SYSTEM_PROMPT,
            user_prompt=user_content,
        )

        self._bus.record_result(self.name, result)
        await self.broadcast(f"✅ 创作完成，共 {len(result)} 字符")

        return result
