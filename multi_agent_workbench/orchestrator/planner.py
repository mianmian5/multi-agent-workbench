"""Planner——智能任务拆解器

根据用户任务内容和可用 Agent 的能力，智能拆解为子任务并匹配合适的 Agent。
"""

from typing import Optional


class Planner:
    """任务规划器——将任务拆解为子任务列表（智能匹配 Agent）"""

    def __init__(self, context, agents: list[dict] | None = None):
        self.context = context
        self._agents = agents or []

    def set_agents(self, agents: list[dict]):
        """设置可用的 Agent 列表（从 Router 获取）"""
        self._agents = agents

    def _build_system_prompt(self) -> str:
        """根据可用 Agent 动态构建 system prompt"""
        agent_list = "\n".join([
            f"  - {a['name']}: {a['description']}"
            for a in self._agents
        ]) if self._agents else "  - 搜索专员: 信息搜集\n  - 写作专员: 内容创作\n  - 总结专员: 审校改进"

        return f"""你是一个任务规划专家。你的职责是把一个复杂任务拆解成清晰的执行步骤。

可用专家团队：
{agent_list}

规则：
1. 分析任务内容，**从可用专家团队中选择最合适的专家**分配给每个步骤
2. 每个步骤必须具体、可执行
3. 步骤数量：2-6 步
4. 步骤之间要有依赖关系（depends_on 为前面步骤的编号）
5. **agent 必须从以上列表中选择，不能自己编造**

输出格式要求（严格按此格式，不要加其他内容）：
[
  {{"step": 1, "agent": "专家名称", "task": "具体任务描述", "depends_on": []}},
  ...
]

请仅输出 JSON 数组，不要有额外说明。
"""

    async def plan(self, user_task: str) -> list[dict]:
        """将用户任务拆解为步骤列表（智能匹配 Agent）"""
        # 没有 API Key 时使用关键词匹配方案
        if not self.context.llm_api_key:
            return self._keyword_plan(user_task)

        try:
            system_prompt = self._build_system_prompt()
            result = await self._call_planner_llm(system_prompt, user_task)
            steps = self._parse_steps(result)

            if not steps:
                steps = self._keyword_plan(user_task)
        except Exception:
            steps = self._keyword_plan(user_task)

        return steps

    async def _call_planner_llm(self, system_prompt: str, task: str) -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.context.llm_api_key,
            base_url=self.context.llm_base_url,
        )

        response = await client.chat.completions.create(
            model=self.context.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请将以下任务拆解为执行步骤，选择合适的专家：\n\n{task}"},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    def _parse_steps(self, text: str) -> list[dict]:
        import json
        import re

        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if match:
            try:
                steps = json.loads(match.group())
                if isinstance(steps, list) and all("step" in s for s in steps):
                    return steps
            except json.JSONDecodeError:
                pass
        return []

    def _keyword_plan(self, task: str) -> list[dict]:
        """根据关键词智能匹配 Agent（离线模式）"""
        task_lower = task.lower()

        # 启用关键词匹配
        matched = []
        for agent in self._agents:
            score = sum(1 for kw in agent.get("capabilities", []) if kw.lower() in task_lower)
            if score > 0:
                matched.append((score, agent))

        # 检查是否是编程类任务
        is_code = any(kw in task_lower for kw in ["编程", "代码", "python", "写一个", "脚本", "爬虫", "程序", "算法"])
        is_translate = any(kw in task_lower for kw in ["翻译", "译", "translate", "英文", "英文版"])

        if is_translate:
            steps = [
                {"step": 1, "agent": "翻译专员", "task": f"翻译：{task}", "depends_on": []},
                {"step": 2, "agent": "总结专员", "task": "校对翻译质量，确保准确通顺", "depends_on": [1]},
            ]
            return steps

        if is_code:
            steps = [
                {"step": 1, "agent": "编程专员", "task": f"分析需求并设计方案：{task}", "depends_on": []},
                {"step": 2, "agent": "写作专员", "task": "编写技术说明文档", "depends_on": [1]},
                {"step": 3, "agent": "总结专员", "task": "审核代码和技术文档质量", "depends_on": [2]},
            ]
            return steps

        # 默认方案：搜索 → 写作 → 总结
        return [
            {"step": 1, "agent": "搜索专员", "task": f"搜集与「{task}」相关的信息", "depends_on": []},
            {"step": 2, "agent": "写作专员", "task": f"基于搜集的信息创作内容：{task}", "depends_on": [1]},
            {"step": 3, "agent": "总结专员", "task": f"审校和总结创作成果：{task}", "depends_on": [2]},
        ]
