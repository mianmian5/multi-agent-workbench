"""自定义 Agent——用户无需写代码即可创建自己的 Agent 类型"""

from .base import BaseAgent


class CustomAgent(BaseAgent):
    """可由用户在 Web UI 中配置的自定义 Agent"""

    def __init__(self, name: str, description: str, system_prompt: str,
                 capabilities: list[str], context, is_custom: bool = True):
        super().__init__(
            name=name,
            description=description,
            context=context,
            capabilities=capabilities,
        )
        self.system_prompt = system_prompt
        self._is_custom = is_custom

    async def execute(self, task: str, **kwargs) -> str:
        custom_name = kwargs.get("reviewer_name", self.name) if "reviewer_name" in kwargs else self.name

        await self.broadcast(f"🛠️ {custom_name} 正在执行：{task[:50]}...")

        # 收集依赖结果作为上下文
        context_parts = [f"## 任务\n{task}"]
        for key in ("knowledge_context", "search_result", "info", "draft"):
            if kwargs.get(key):
                label = {"knowledge_context": "参考资料", "search_result": "搜索结果",
                         "info": "相关信息", "draft": "待处理稿"}.get(key, key)
                context_parts.append(f"## {label}\n{kwargs[key]}")

        result = await self.call_llm(
            system_prompt=self.system_prompt,
            user_prompt="\n\n".join(context_parts),
        )

        self._bus.record_result(self.name, result)
        await self.broadcast(f"✅ {custom_name} 执行完成，共 {len(result)} 字符")

        return result
