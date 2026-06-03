"""记忆系统——让 Agent 能记住历史对话和用户信息

Agent 在执行任务时可以查询之前学到的信息，
实现跨会话的长期记忆。

存储结构：
~/.awb_memory/
├── index.json        # 记忆索引
└── entries/          # 单条记忆
    ├── <id>.json
    └── ...
"""

import json
import re
import time
import uuid
from pathlib import Path

MEMORY_DIR = Path.home() / ".awb_memory"
ENTRIES_DIR = MEMORY_DIR / "entries"
INDEX_FILE = MEMORY_DIR / "index.json"

# 记忆类型
MEMORY_TYPES = ("fact", "preference", "summary", "note")


def _ensure():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    ENTRIES_DIR.mkdir(exist_ok=True)


def _load_index() -> dict:
    _ensure()
    if INDEX_FILE.exists():
        try:
            return json.loads(INDEX_FILE.read_text())
        except Exception:
            pass
    return {"entries": [], "version": 1}


def _save_index(index: dict):
    INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2))


# ==================== CRUD ====================


def add_memory(content: str, mem_type: str = "note",
               tags: list[str] | None = None,
               source: str = "") -> dict:
    """添加一条记忆"""
    if mem_type not in MEMORY_TYPES:
        mem_type = "note"

    _ensure()
    mem_id = uuid.uuid4().hex[:12]
    entry = {
        "id": mem_id,
        "type": mem_type,
        "content": content.strip(),
        "tags": tags or [],
        "source": source,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    (ENTRIES_DIR / f"{mem_id}.json").write_text(
        json.dumps(entry, ensure_ascii=False, indent=2)
    )

    index = _load_index()
    index["entries"].insert(0, {
        "id": mem_id,
        "type": mem_type,
        "summary": content[:80],
        "tags": entry["tags"],
        "created_at": entry["created_at"],
    })
    _save_index(index)

    return entry


def list_memories(mem_type: str = "", tag: str = "",
                  limit: int = 50) -> list[dict]:
    """列出记忆"""
    index = _load_index()
    entries = index.get("entries", [])

    if mem_type:
        entries = [e for e in entries if e.get("type") == mem_type]
    if tag:
        entries = [e for e in entries if tag in e.get("tags", [])]

    return entries[:limit]


def get_memory(mem_id: str) -> dict | None:
    path = ENTRIES_DIR / f"{mem_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return None


def delete_memory(mem_id: str) -> bool:
    path = ENTRIES_DIR / f"{mem_id}.json"
    if not path.exists():
        return False
    path.unlink()

    index = _load_index()
    index["entries"] = [e for e in index["entries"] if e["id"] != mem_id]
    _save_index(index)
    return True


# ==================== 搜索 ====================


def search_memories(query: str, max_results: int = 5) -> list[dict]:
    """搜索记忆（关键词匹配）"""
    keywords = set(re.findall(r"[\w\u4e00-\u9fff]+", query.lower()))
    if not keywords:
        return []

    results = []
    for f in ENTRIES_DIR.glob("*.json"):
        try:
            entry = json.loads(f.read_text())
            text = (entry.get("content", "") + " " + " ".join(entry.get("tags", []))).lower()
            matched = sum(1 for kw in keywords if kw in text)
            if matched > 0:
                results.append((matched, entry))
        except Exception:
            pass

    results.sort(key=lambda x: -x[0])
    return [r[1] for r in results[:max_results]]


def get_memory_context(query: str, max_results: int = 3) -> str:
    """获取记忆上下文（给 Agent 用的文本格式）"""
    memories = search_memories(query, max_results)
    if not memories:
        return ""

    parts = ["## 🧠 历史记忆"]
    for mem in memories:
        mem_type_icon = {"fact": "📌", "preference": "❤️", "summary": "📝", "note": "💡"}
        icon = mem_type_icon.get(mem.get("type", "note"), "💡")
        parts.append(f"{icon} [{mem.get('type', 'note')}] {mem['content'][:300]}")
        if mem.get("tags"):
            parts.append(f"  标签: {', '.join(mem['tags'])}")

    return "\n\n".join(parts)


# ==================== 自动总结 ====================


def summarize_conversation(task: str, result: str, agents: list[str]) -> dict | None:
    """自动记录一次任务到记忆

    只保存一条简洁的任务摘要，不提取碎片化事实。
    太短的任务 (<200字) 不保存，避免记忆被无关内容污染。
    """
    # 结果太短不存
    if len(result) < 200:
        return None

    # 生成简洁的摘要
    task_short = task.replace("\n", " ").strip()
    if len(task_short) > 80:
        task_short = task_short[:77] + "..."

    agent_list = ", ".join(a.replace("专员", "") for a in agents[:4])
    content = f"📋 {task_short}\n👥 参与: {agent_list}\n📏 输出: {len(result)} 字"

    summary = add_memory(
        content=content,
        mem_type="summary",
        tags=["auto", "conversation"],
        source=task_short,
    )

    return summary


# ==================== 统计 ====================


def get_memory_stats() -> dict:
    """获取记忆统计"""
    index = _load_index()
    entries = index.get("entries", [])
    counts = {}
    for e in entries:
        t = e.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return {
        "total": len(entries),
        "by_type": counts,
    }
