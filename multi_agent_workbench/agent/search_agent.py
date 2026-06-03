"""搜索 Agent——负责真实搜索和分析网络信息"""

from .base import BaseAgent
from ..tools.web_search import search_and_fetch, search_bing, fetch_page


SUBQUERY_PROMPT = """你是一个信息检索策略专家。请将用户的搜索任务拆解为 3-5 个独立的子搜索词/子问题，覆盖任务的不同侧面。

规则：
- 每个子查询应当独立、具体、搜索友好（适合直接用来搜网页）
- 覆盖任务的核心主题、不同角度或维度
- 输出格式：每行一个子查询，不要编号，不要多余文字

例子：
任务：帮我写一篇关于量子计算的科普文章
子查询：
量子计算 基本原理 入门
量子计算 最新进展 2025
量子计算 应用场景 实际案例
量子计算 与传统计算 区别对比

任务：对ChatGPT进行竞品分析
子查询：
ChatGPT 竞品分析 市场
ChatGPT 功能 评测 对比
Google Gemini Claude 对比 2025
AI大模型 商业模式 发展趋势"""


SEARCH_SYSTEM_PROMPT = """你是一个专业的信息搜集与分析专家。
你的任务是基于搜索到的网络信息和用户提供的参考资料，进行整理、归纳和分析。

工作要求：
1. **优先使用用户提供的参考资料**，其次是网络搜索
2. 基于搜索结果进行分析，不要凭空编造
3. 提取关键事实、数据、观点
4. 标注信息来源（来自网络或用户资料）
5. 按逻辑组织，便于后续处理

输出格式要求：
- 用 Markdown 格式
- 先给出核心发现和总结（2-3 点）
- 再按主题分类展开详细信息
- 每个信息点标注来源
"""


class SearchAgent(BaseAgent):
    """搜索/信息搜集 Agent——真正搜索互联网"""

    def __init__(self, context):
        super().__init__(
            name="搜索专员",
            description="负责真实搜索互联网、信息整理和事实核查。擅长：资料检索、信息归纳、知识梳理",
            context=context,
            capabilities=["搜索", "信息", "资料", "调研", "查找", "了解", "搜集", "查询", "整理", "归纳", "最新", "趋势"],
        )

    async def execute(self, task: str, **kwargs) -> str:
        await self.broadcast(f"\U0001f50d 正在搜索互联网：{task[:60]}...")

        knowledge_ctx = kwargs.get("knowledge_context", "")
        has_knowledge = bool(knowledge_ctx)

        # Step 1: 用 LLM 生成 3-5 个子搜索词
        await self.broadcast("\U0001f9e0 分析任务，生成多角度搜索策略...")
        sub_queries_text = await self.call_llm(
            system_prompt=SUBQUERY_PROMPT,
            user_prompt=f"请将以下搜索任务拆解为 3-5 个子查询：\n\n{task}",

        )
        sub_queries = [q.strip() for q in sub_queries_text.strip().splitlines() if q.strip()]
        seen = set()
        unique_queries = []
        for q in sub_queries:
            if q not in seen and len(q) > 2:
                seen.add(q)
                unique_queries.append(q)
        sub_queries = unique_queries[:5]

        if not sub_queries:
            sub_queries = [task[:60]]

        q_preview = " | ".join(q[:20] for q in sub_queries)
        await self.broadcast(f"\U0001f4e1 计划搜索 {len(sub_queries)} 个方向：{q_preview}")

        # Step 2: 依次搜索每个子查询，合并结果
        all_search_results = []
        for idx, query in enumerate(sub_queries):
            await self.broadcast(f"\U0001f50e 搜索 ({idx+1}/{len(sub_queries)})：{query[:40]}...")
            result = search_and_fetch(query, max_results=3)
            if result.startswith("\u26a0"):
                fallback = " ".join(query.split()[:3])
                if fallback and fallback != query:
                    result = search_and_fetch(fallback, max_results=3)
            section = f"## 搜索方向 {idx+1}：{query}\n\n{result}"
            all_search_results.append(section)

        combined_search = "\n\n---\n\n".join(all_search_results)

        # Step 3: 降级保护——如果所有方向都搜空了，直接用原文搜
        if all(r.startswith("\u26a0") for r in all_search_results if r.strip()):
            await self.broadcast("\U0001f504 多方向搜索未返回有效结果，尝试直接搜索...")
            final_result = search_and_fetch(task[:60], max_results=5)
            combined_search = f"## 网络搜索结果\n\n{final_result}"

        # Step 4: 整合网络搜索 + 知识库资料
        all_materials = f"## 综合搜索结果（{len(sub_queries)} 个搜索方向）\n{combined_search}"
        if has_knowledge:
            await self.broadcast("\U0001f4da 正在检索知识库中的参考资料...")
            all_materials += f"\n\n---\n\n## 用户知识库资料\n{knowledge_ctx[:3000]}"

        result = await self.call_llm(
            system_prompt=SEARCH_SYSTEM_PROMPT,
            user_prompt=f"""## 搜索任务
{task}

## 参考材料
{all_materials}

请基于以上材料，整理一份结构清晰的信息报告。
""",
        )

        self._bus.record_result(self.name, result)
        source_hint = "+ 用户知识库" if has_knowledge else ""
        await self.broadcast(f"\u2705 搜索完成！获取了网络信息{source_hint}并整理完毕")

        return result
