"""WorkBench——多智能体协作工作台的主入口

整合 Planner + Router + MessageBus，对外提供简洁的接口。
"""

import asyncio
import time
from typing import Optional

from ..communication.message_bus import MessageBus, WorkLog, Message
from ..agent import BaseAgent, AgentContext
from .planner import Planner
from .router import Router


class WorkBench:
    """
    多智能体协作工作台

    使用方式：
        bench = WorkBench()
        result = await bench.run("写一篇分析AI Agent的文章")
        print(result)
    """

    def __init__(self, context: Optional[AgentContext] = None, use_knowledge: bool = True):
        self.use_knowledge = use_knowledge
        self.message_bus = MessageBus()
        if context and not context.message_bus:
            context.message_bus = self.message_bus
        self.context = context or AgentContext.from_env(self.message_bus)

        # 先创建 Router 和 Agent
        self.router = Router()
        self.agents = self.router.create_default_agents(self.context)

        # 再把 Agent 列表传给 Planner（用于智能匹配）
        self.planner = Planner(self.context, agents=self.router.get_agent_list())

    async def run(self, user_task: str, verbose: bool = True, discuss: bool = True, discussion_rounds: int = 2) -> tuple[str, WorkLog]:
        """
        运行多智能体协作流程（含可选的讨论阶段）

        Args:
            user_task: 用户输入的任务描述
            verbose: 是否打印执行过程
            discuss: 是否启用讨论阶段
            discussion_rounds: 多轮讨论的轮数（默认 2 轮）

        Returns:
            (最终结果, 完整工作日志)
        """
        work_log = WorkLog(task_id=f"task_{int(time.time())}")
        self.message_bus.bind_work_log(work_log)

        # 搜索知识库，获取相关参考资料
        knowledge_context = ""
        if self.use_knowledge:
            try:
                from ..tools.knowledge_base import (
                    search_knowledge, get_knowledge_context
                )
                kc = get_knowledge_context(user_task)
                if kc:
                    knowledge_context = kc
                    if verbose:
                        print(f"📚 找到知识库参考材料 ({len(kc)} 字符)")
                        print()
            except Exception as e:
                # 知识库不可用时不阻塞
                if verbose:
                    print(f"⚠️ 知识库搜索跳过: {e}")

        if verbose:
            print(f"\n{'='*50}")
            print(f"🧠 多智能体协作启动！")
            print(f"📋 任务: {user_task}")
            if knowledge_context:
                print(f"📚 引用知识库: {len(knowledge_context)} 字符")
            print(f"{'='*50}\n")

        # 将知识库信息注入到每个 Agent 的执行环境
        self._knowledge_context = knowledge_context

        # 搜索相关的历史记忆
        memory_context = ""
        try:
            from ..tools.memory_system import get_memory_context
            mc = get_memory_context(user_task)
            if mc:
                memory_context = mc
                if verbose:
                    print(f"🧠 找到相关历史记忆")
        except Exception:
            pass
        self._memory_context = memory_context

        # Step 1: Planner 拆解任务
        if verbose:
            print(f"📐 [规划] 正在拆解任务...")
        steps = await self.planner.plan(user_task)
        work_log.plan = steps

        if verbose:
            print(f"   → 拆解为 {len(steps)} 个子任务:")
            for s in steps:
                print(f"     Step {s['step']}: [{s['agent']}] {s['task']}")
            print()

        # Step 2: Router 分配执行
        if verbose:
            print(f"🚀 [执行] 开始分配任务给各 Agent...\n")

        step_results = await self.router.dispatch(
            steps, self._knowledge_context, self._memory_context,
            user_task=user_task,
        )

        # Step 3: 多轮讨论阶段（像真人会议那样来回对话）
        if discuss and len(step_results) > 0 and discussion_rounds > 0:
            if verbose:
                print(f"💬 [讨论] 开始多轮讨论（{discussion_rounds} 轮）...\n")

            main_result = step_results.get(max(step_results.keys()), "")
            original_task = steps[-1]["task"] if steps else user_task
            discuss_agent = self.router.get_agent("讨论专员")

            self.message_bus.send(Message(
                id="discuss_start", sender="系统", recipient="broadcast",
                content=f"💬 开始多轮团队讨论（共 {discussion_rounds} 轮）..."
            ))

            # 当前讨论的材料
            current_draft = main_result
            all_rounds = []

            for round_num in range(1, discussion_rounds + 1):
                if verbose:
                    print(f"  ── 第 {round_num} 轮讨论 ──")

                # 本轮方向提示：第一轮自由审阅，后续轮次针对性回应
                if round_num == 1:
                    round_context = ""
                else:
                    # 第二轮及以后：主持人指出需要深入讨论的点
                    round_context = await discuss_agent.moderate(
                        original_task, current_draft,
                        all_rounds[-1] if all_rounds else [],
                        round_type="deep_dive",
                    )

                # 每个 Agent 独立审阅（仅包含实际参与任务的 Agent）
                feedbacks = []
                review_tasks = []
                # 获取实际参与任务的 Agent 名称
                active_agents = {s["agent"] for s in steps}
                # 只让实际参与任务的 Agent 参与讨论
                active_agents = {s["agent"] for s in steps}
                for agent in self.agents:
                    if agent.name == "讨论专员":
                        continue
                    if agent.name not in active_agents:
                        continue
                    review_tasks.append(self._get_agent_review(
                        agent, original_task, current_draft, user_task,
                        round_num=round_num, round_context=round_context,
                    ))

                if review_tasks:
                    feedbacks = await asyncio.gather(*review_tasks)
                    all_rounds.append(feedbacks)

                    # 发送本轮讨论事件
                    for name, fb in feedbacks:
                        self.message_bus.send(Message(
                            id=f"discuss_r{round_num}_{name}",
                            sender=name, recipient="broadcast",
                            content=f"[第{round_num}轮] {fb[:300]}"
                        ))

                    if verbose:
                        print(f"    第 {round_num} 轮: {len(feedbacks)} 位 Agent 参与")
                        for name, fb in feedbacks:
                            print(f"      {name}: {fb[:80]}...")

            # 讨论专员做最终总结
            if discuss_agent and all_rounds:
                final_round = all_rounds[-1]
                summary = await discuss_agent.moderate(
                    original_task, current_draft, final_round,
                    round_type="final_summary",
                    history=all_rounds,
                )

                self.message_bus.send(Message(
                    id="discuss_end", sender="系统", recipient="broadcast",
                    content=f"💬 多轮讨论结束（共 {discussion_rounds} 轮，{sum(1 for r in all_rounds for _ in r)} 条反馈）。\n\n{summary}"
                ))

                if verbose:
                    print(f"💬 讨论完成！共 {discussion_rounds} 轮，{len(all_rounds)} 轮反馈")
                    print(f"📋 最终总结:\n{summary[:500]}\n")

        # Step 4: 整理最终结果
        final_result = self._assemble_result(steps, step_results)
        work_log.status = "completed"
        work_log.finished_at = time.time()

        if verbose:
            duration = work_log.finished_at - work_log.started_at
            print(f"\n{'='*50}")
            print(f"✅ 协作完成！耗时 {duration:.1f} 秒")
            print(f"{'='*50}\n")

        return final_result, work_log

    async def _get_agent_review(
        self, agent: BaseAgent, original_task: str, draft: str, user_task: str,
        round_num: int = 1, round_context: str = "",
    ) -> tuple[str, str]:
        """让一个 Agent 独立审阅协作成果（支持多轮）"""
        discuss_agent = self.router.get_agent("讨论专员")
        if not discuss_agent:
            return (agent.name, "")

        # 多轮模式下，给 Agent 传递轮次和上下文
        kwargs = dict(
            draft=draft,
            reviewer_name=agent.name,
            original_task=user_task,
        )

        if round_num > 1 and round_context:
            kwargs["round_context"] = round_context
            kwargs["response_to"] = f"第{round_num - 1}轮的讨论要点"

        feedback = await discuss_agent.execute(
            original_task,
            **kwargs,
        )
        return (agent.name, feedback)

    def _assemble_result(self, steps: list[dict], results: dict[int, str]) -> str:
        """将各步骤结果组装为最终输出"""
        if not results:
            return ""
        last_step = max(results.keys())
        return results[last_step]
