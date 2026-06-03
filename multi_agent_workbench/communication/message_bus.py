"""Agent 间通信的消息总线"""

from __future__ import annotations
import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Message:
    """Agent 之间传递的消息"""
    id: str
    sender: str          # 发送者 Agent 名称
    recipient: str       # 接收者 Agent 名称（"broadcast" 表示广播）
    content: str         # 消息内容
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    parent_id: Optional[str] = None  # 关联的父消息 ID


@dataclass
class WorkLog:
    """任务执行过程的全量日志"""
    task_id: str
    plan: list = field(default_factory=list)       # 任务拆解结果
    messages: list = field(default_factory=list)   # Agent 间通信记录
    results: dict = field(default_factory=dict)    # 每个 Agent 的执行结果
    status: str = "pending"    # pending | running | completed | failed
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        """转为可序列化的字典，方便前端展示"""
        return {
            "task_id": self.task_id,
            "plan": self.plan,
            "messages": [
                {"sender": m.sender, "recipient": m.recipient,
                 "content": m.content[:200], "time": m.created_at}
                for m in self.messages
            ],
            "results": self.results,
            "status": self.status,
            "duration": (self.finished_at or time.time()) - self.started_at,
        }


class MessageBus:
    """
    消息总线——Agent 之间沟通的枢纽

    - 支持点对点发送、广播
    - 自动记录所有通信日志
    - 支持异步等待特定消息（用于 Agent 间协作）
    """

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}
        self.on_broadcast = None  # callback(msg) for forwarding broadcasts to frontend
        self._work_log: Optional[WorkLog] = None

    def bind_work_log(self, log: WorkLog):
        self._work_log = log

    def get_or_create_queue(self, name: str) -> asyncio.Queue:
        if name not in self._queues:
            self._queues[name] = asyncio.Queue()
        return self._queues[name]

    async def send(self, message: Message):
        """发送消息"""
        if self._work_log is not None:
            self._work_log.messages.append(message)

        if message.recipient == "broadcast":
            # 转发到前端 SSE（如果有回调）
            if self.on_broadcast:
                self.on_broadcast(message)
            # 广播给所有 Agent
            for name, queue in self._queues.items():
                if name != message.sender:
                    await queue.put(message)
        else:
            # 发送给指定 Agent
            queue = self.get_or_create_queue(message.recipient)
            await queue.put(message)

    async def receive(self, agent_name: str, timeout: float = 30.0) -> Optional[Message]:
        """接收消息（阻塞等待）"""
        queue = self.get_or_create_queue(agent_name)
        try:
            return await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def record_result(self, agent_name: str, result: str):
        """记录一个 Agent 的执行结果"""
        if self._work_log is not None:
            self._work_log.results[agent_name] = result
