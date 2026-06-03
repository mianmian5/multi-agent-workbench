"""Agent 基类和上下文——所有 Agent 的抽象接口"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from ..communication.message_bus import Message, MessageBus


@dataclass
class AgentContext:
    """Agent 执行上下文——包含消息总线和 LLM 客户端"""
    message_bus: MessageBus | None = None
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"

    @classmethod
    def from_env(cls, message_bus: MessageBus | None = None) -> "AgentContext":
        """从环境变量读取 LLM 配置（自动加载 .env 文件）"""
        import os

        # 尝试自动加载 .env 文件
        _try_load_dotenv()

        return cls(
            message_bus=message_bus,
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            llm_model=os.getenv("LLM_MODEL", "gpt-4o"),
        )


class BaseAgent(ABC):
    """Agent 基类——所有 Agent 的抽象接口"""

    def __init__(self, name: str, description: str, context: AgentContext, capabilities: list[str] | None = None):
        self.name = name
        self.description = description
        self.capabilities = capabilities or []
        self.context = context
        self._bus = context.message_bus

    @abstractmethod
    async def execute(self, task: str, **kwargs) -> str:
        """执行任务，返回结果文本"""
        ...

    def set_memory_context(self, ctx: str):
        """设置记忆上下文（在 execute 前调用）"""
        self._memory_ctx = ctx

    async def send_message(self, recipient: str, content: str, **metadata):
        """向另一个 Agent 发送消息"""
        msg = Message(
            id=f"{self.name}_{id(content)}",
            sender=self.name,
            recipient=recipient,
            content=content,
            metadata=metadata,
        )
        await self._bus.send(msg)

    async def broadcast(self, content: str, **metadata):
        """广播消息给所有 Agent"""
        await self.send_message("broadcast", content, **metadata)

    async def wait_for_message(self, timeout: float = 30.0) -> Optional[Message]:
        """等待接收消息"""
        return await self._bus.receive(self.name, timeout=timeout)

    def _inject_memory(self, user_prompt: str) -> str:
        """如果有记忆上下文，注入到 prompt 中"""
        if hasattr(self, '_memory_ctx') and self._memory_ctx:
            return f"{user_prompt}\n\n---\n{self._memory_ctx}"
        return user_prompt

    async def _call_with_retry(self, client, model: str, messages: list, tools=None) -> str:
        """调用 LLM API 并自动重试（最多 3 次，指数退避）"""
        import asyncio

        last_error = ""
        for attempt in range(3):
            try:
                kwargs = dict(model=model, messages=messages, temperature=0.7)
                if tools:
                    kwargs["tools"] = tools

                response = await client.chat.completions.create(**kwargs)
                return response.choices[0].message

            except Exception as e:
                last_error = str(e)
                err_msg = str(e).lower()

                # 不可重试的错误
                if "auth" in err_msg or "api key" in err_msg or "401" in err_msg:
                    return None  # API Key 问题，不重试
                if "invalid" in err_msg and "model" in err_msg:
                    return None  # 模型不可用

                if attempt < 2:
                    wait = 2 ** attempt  # 1s, 2s
                    await asyncio.sleep(wait)
                    await self.broadcast(f"🔄 重试第 {attempt + 2} 次...")

        # 所有重试都失败
        raise RuntimeError(f"LLM 调用失败（已重试 3 次）: {last_error}")

    async def call_llm(self, system_prompt: str, user_prompt: str, tools: list[dict] | None = None) -> str:
        """调用 LLM API 获取回复（支持 MCP 工具调用 + 记忆上下文 + 自动重试）

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            tools: MCP 工具列表（可选），Agent 可以动态调用这些工具

        Returns:
            LLM 返回的文本内容
        """
        user_prompt = self._inject_memory(user_prompt)
        # 没有 API Key 时返回模拟回复
        if not self.context.llm_api_key:
            return (
                f"[模拟回复 - {self.name} 执行完成]\n\n"
                f"这是 {self.name} 根据请求生成的模拟回复。\n"
                f"请求内容: {user_prompt[:100]}..."
            )

        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.context.llm_api_key,
            base_url=self.context.llm_base_url,
            timeout=60.0,  # 60 秒超时
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # 没有工具：单次调用
        if not tools:
            msg = await self._call_with_retry(client, self.context.llm_model, messages)
            return msg.content or "" if msg else "[LLM 调用失败: 请检查 API Key 和模型配置]"

        # 有工具：函数调用循环（最多 3 轮）
        import json

        for _ in range(3):
            msg = await self._call_with_retry(client, self.context.llm_model, messages, tools)
            if msg is None:
                return "[LLM 调用失败: 请检查 API Key 和模型配置]"

            # 如果没有工具调用，直接返回文本
            if not msg.tool_calls:
                return msg.content or ""

            # 处理工具调用
            for tool_call in msg.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                # 查找并执行工具
                from ..tools.mcp_tools import get_default_registry
                registry = get_default_registry()
                tool = registry.get(tool_name)

                if tool:
                    await self.broadcast(f"🛠️ 调用工具: {tool_name}")
                    tool_result = await tool.call(**tool_args)
                else:
                    tool_result = f"[未知工具] {tool_name}"

                # 把工具调用和结果加到对话中
                tool_msg = {"role": msg.role, "content": msg.content or ""}
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    tool_msg["tool_calls"] = [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in msg.tool_calls
                    ]
                messages.append(tool_msg)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result[:5000],
                })

        # 超过最大轮数，返回最后一次的内容
        return msg.content or "[工具调用超限]"


def _try_load_dotenv():
    """尝试自动加载项目根目录的 .env 文件"""
    import os
    import os.path

    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.isfile(env_path):
        return

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and not os.environ.get(key):
                os.environ[key] = value
