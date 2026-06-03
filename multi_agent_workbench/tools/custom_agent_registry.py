"""自定义 Agent 注册表——管理用户自定义的 Agent 类型

用户可以在 Web UI 中创建自己的 Agent，无需写代码。
配置存储在 ~/.awb_agents/ 目录下。

每个自定义 Agent 需要：
- name: 名称（如"数据分析专员"）
- description: 描述（简短的能力说明）
- system_prompt: 系统提示词（定义行为和能力）
- capabilities: 能力关键词列表（用于 Planner 智能分配）
"""

import json
import time
import uuid
from pathlib import Path

AGENTS_DIR = Path.home() / ".awb_agents"


def _ensure_dir():
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)


def _file_path(agent_id: str) -> Path:
    return AGENTS_DIR / f"{agent_id}.json"


def list_agents() -> list[dict]:
    """列出所有自定义 Agent"""
    _ensure_dir()
    agents = []
    for f in sorted(AGENTS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            agents.append(data)
        except Exception:
            pass
    return agents


def get_agent(agent_id: str) -> dict | None:
    """获取单个自定义 Agent"""
    path = _file_path(agent_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return None


def create_agent(
    name: str,
    description: str,
    system_prompt: str,
    capabilities: list[str],
) -> dict:
    """创建自定义 Agent"""
    _ensure_dir()
    agent = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "description": description,
        "system_prompt": system_prompt,
        "capabilities": capabilities,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "is_custom": True,
    }
    _file_path(agent["id"]).write_text(
        json.dumps(agent, ensure_ascii=False, indent=2)
    )
    return agent


def update_agent(
    agent_id: str,
    name: str | None = None,
    description: str | None = None,
    system_prompt: str | None = None,
    capabilities: list[str] | None = None,
) -> dict | None:
    """更新自定义 Agent"""
    agent = get_agent(agent_id)
    if not agent:
        return None

    if name is not None:
        agent["name"] = name
    if description is not None:
        agent["description"] = description
    if system_prompt is not None:
        agent["system_prompt"] = system_prompt
    if capabilities is not None:
        agent["capabilities"] = capabilities
    agent["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    _file_path(agent_id).write_text(
        json.dumps(agent, ensure_ascii=False, indent=2)
    )
    return agent


def delete_agent(agent_id: str) -> bool:
    """删除自定义 Agent"""
    path = _file_path(agent_id)
    if path.exists():
        path.unlink()
        return True
    return False


def get_all_agents_info() -> list[dict]:
    """获取所有 Agent 信息（内置 + 自定义），给 Planner 用"""
    from ..agent import (
        SearchAgent, WriterAgent, SummarizerAgent,
        DiscussAgent, CodingAgent, TranslateAgent,
    )

    # 内置 Agent 信息
    builtin = [
        {"name": "搜索专员", "description": "负责真实搜索互联网、信息整理和事实核查", "capabilities": ["搜索", "信息", "资料", "调研", "查找", "了解", "搜集", "查询", "整理", "归纳", "最新", "趋势"]},
        {"name": "写作专员", "description": "负责内容创作和表达优化", "capabilities": ["写作", "创作", "写", "文章", "文案", "内容", "故事", "小说", "润色", "改写", "摘要", "总结"]},
        {"name": "总结专员", "description": "负责内容总结、质量审核和改进优化", "capabilities": ["总结", "审校", "审核", "质检", "提炼", "要点", "改进", "优化", "review", "检查", "校对"]},
        {"name": "讨论专员", "description": "团队讨论主持人，收集各方反馈、归纳意见", "capabilities": ["讨论", "反馈", "建议", "头脑风暴", "整合意见", "归纳"]},
        {"name": "编程专员", "description": "负责编写代码、运行测试和技术方案设计", "capabilities": ["编程", "代码", "写代码", "开发", "Python", "JavaScript", "脚本", "程序", "算法", "函数", "API", "Web开发", "自动化", "爬虫", "数据库", "debug", "调试", "技术方案", "前后端", "架构", "实现", "部署", "数据分析"]},
        {"name": "翻译专员", "description": "负责多语言翻译和本地化", "capabilities": ["翻译", "译", "translate", "英文", "英语", "中文", "本地化", "多语言", "语言"]},
    ]

    # 自定义 Agent
    custom = [
        {"name": a["name"], "description": a["description"], "capabilities": a.get("capabilities", [])}
        for a in list_agents()
    ]

    return builtin + custom
