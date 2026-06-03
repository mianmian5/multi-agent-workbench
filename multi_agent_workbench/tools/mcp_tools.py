"""MCP 工具调用系统——富工具集（20+ 工具）

Agent 可以在执行任务时动态调用各种工具：
搜索、文件操作、代码执行、Git、数据处理、时间计算等。

参考 OpenClaw / Claude Code 的工具设计理念：
每个工具职责单一、输入输出清晰、出错有明确的错误信息。
"""

import json
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

# 文件操作的安全目录
WORK_DIR = Path("/tmp/awb_workspace")


class Tool:
    """一个可被 Agent 调用的工具"""

    def __init__(self, name: str, description: str, input_schema: dict, handler: Callable):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler

    def to_openai_format(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    async def call(self, **kwargs) -> str:
        try:
            result = self.handler(**kwargs)
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            return f"[工具错误] {self.name}: {type(e).__name__}: {e}"


class ToolRegistry:
    """工具注册表——管理所有可用的 MCP 工具"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, description: str, input_schema: dict, handler: Callable):
        self._tools[name] = Tool(name, description, input_schema, handler)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def to_openai_functions(self) -> list[dict]:
        return [t.to_openai_format() for t in self._tools.values()]

    def to_mcp_format(self) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
            for t in self._tools.values()
        ]


# ==================== 全局默认工具注册表 ====================

_default_registry = ToolRegistry()


def get_default_registry() -> ToolRegistry:
    if not _default_registry._tools:
        _init_default_tools(_default_registry)
    return _default_registry


# ==================== 工具实现函数 ====================
# 每个函数对应一个工具，命名规范：_tool_<name>


def _ensure_work_dir():
    WORK_DIR.mkdir(parents=True, exist_ok=True)


def _safe_path(subpath: str) -> Path:
    """确保路径在安全的工作目录内"""
    _ensure_work_dir()
    p = (WORK_DIR / subpath).resolve()
    if not str(p).startswith(str(WORK_DIR.resolve())):
        raise PermissionError(f"路径超出安全目录: {subpath}")
    return p


# --- Web 工具 ---

def _tool_web_search(query: str, max_results: int = 3) -> str:
    from .web_search import search_and_fetch
    return search_and_fetch(query, max_results)


def _tool_fetch_page(url: str) -> str:
    from .web_search import fetch_page
    return fetch_page(url)


def _tool_check_url(url: str) -> str:
    """检查 URL 是否可达"""
    import httpx
    try:
        resp = httpx.head(url, timeout=10, follow_redirects=True)
        return f"✅ {resp.status_code} {resp.reason_phrase}\n大小: {resp.headers.get('content-length', '未知')} bytes\n类型: {resp.headers.get('content-type', '未知')}"
    except httpx.TimeoutException:
        return "❌ 连接超时"
    except httpx.ConnectError:
        return "❌ 无法连接"
    except Exception as e:
        return f"❌ {e}"


# --- 文件 && 项目工具 ---

def _tool_read_file(path: str, max_chars: int = 50000) -> str:
    fp = _safe_path(path)
    if not fp.exists():
        return f"❌ 文件不存在: {path}"
    if not fp.is_file():
        return f"❌ 不是文件: {path}"
    content = fp.read_text(encoding="utf-8", errors="replace")
    if len(content) > max_chars:
        content = content[:max_chars] + f"\n\n... (文件过长，截取前 {max_chars} 字符)"
    return content


def _tool_write_file(path: str, content: str) -> str:
    fp = _safe_path(path)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    return f"✅ 已写入 {len(content)} 字符到 {path}"


def _tool_edit_file(path: str, old_text: str, new_text: str) -> str:
    """编辑文件中的文本（替换）"""
    fp = _safe_path(path)
    if not fp.exists():
        return f"❌ 文件不存在: {path}"
    content = fp.read_text(encoding="utf-8")
    if old_text not in content:
        return f"❌ 未找到匹配的文本: {old_text[:50]}..."
    count = content.count(old_text)
    content = content.replace(old_text, new_text, 1)
    fp.write_text(content, encoding="utf-8")
    return f"✅ 已替换 1 处匹配（共 {count} 处）"


def _tool_list_files(path: str = ".", pattern: str = "") -> str:
    fp = _safe_path(path)
    if not fp.exists():
        return f"❌ 目录不存在: {path}"
    if not fp.is_dir():
        return f"❌ 不是目录: {path}"

    lines = [f"📁 {fp}/"]
    for entry in sorted(fp.iterdir()):
        if pattern and pattern not in entry.name:
            continue
        prefix = "📄" if entry.is_file() else "📁"
        size = entry.stat().st_size if entry.is_file() else 0
        size_str = f"{size}B" if size < 1024 else f"{size/1024:.1f}KB"
        lines.append(f"  {prefix} {entry.name} ({size_str})")

    return "\n".join(lines)


def _tool_grep_search(pattern: str, path: str = ".", include: str = "") -> str:
    """在文件中搜索文本"""
    fp = _safe_path(path)
    if not fp.exists():
        return f"❌ 路径不存在: {path}"

    exts = include.split(",") if include else []
    results = []

    for f in fp.rglob("*"):
        if f.is_file() and f.suffix.lower() in exts if exts else True:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(content.splitlines(), 1):
                    if pattern in line:
                        rel = f.relative_to(WORK_DIR) if WORK_DIR in f.parents else f
                        results.append(f"{rel}:{i}: {line.strip()[:120]}")
            except Exception:
                pass

    if not results:
        return f"🔍 在 {path} 中未找到 \"{pattern}\""
    return f"🔍 找到 {len(results)} 处匹配:\n" + "\n".join(results[:50])


# --- Shell / Git 工具 ---

def _tool_run_shell(command: str, timeout: int = 15) -> str:
    """在沙箱中执行 shell 命令"""
    import subprocess
    _ensure_work_dir()
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(WORK_DIR),
            env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
        )
        out = (proc.stdout or "")[:30000]
        err = (proc.stderr or "")[:5000]
        result = f"退出码: {proc.returncode}\n"
        if out:
            result += f"\n标准输出:\n{out}\n"
        if err:
            result += f"\n标准错误:\n{err}\n"
        return result
    except subprocess.TimeoutExpired:
        return f"⏰ 命令超时（{timeout} 秒限制）"
    except Exception as e:
        return f"❌ 执行失败: {e}"


def _tool_git_status(path: str = ".") -> str:
    """检查 Git 仓库状态"""
    fp = _safe_path(path)
    if not (fp / ".git").exists():
        return f"❌ 不是 Git 仓库: {path}"
    import subprocess
    try:
        result = subprocess.run(
            ["git", "status", "--short", "--branch"],
            capture_output=True, text=True, timeout=10, cwd=str(fp),
        )
        branch_out = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            capture_output=True, text=True, timeout=10, cwd=str(fp),
        )
        out = result.stdout + result.stderr
        out += "\n\n最近提交:\n" + branch_out.stdout
        return out.strip() or "✅ 工作区干净"
    except Exception as e:
        return f"❌ Git 操作失败: {e}"


def _tool_run_code(code: str) -> str:
    from .code_sandbox import CodeSandbox
    sandbox = CodeSandbox(timeout=15)
    result = sandbox.run_python(code)
    return result.format_markdown()


# --- 数据工具 ---

def _tool_parse_json(text: str, format_output: bool = True) -> str:
    """解析 JSON 文本"""
    try:
        data = json.loads(text)
        if format_output:
            return json.dumps(data, ensure_ascii=False, indent=2)
        return str(data)
    except json.JSONDecodeError as e:
        return f"❌ JSON 解析失败: {e}"


def _tool_parse_csv(text: str, max_rows: int = 30) -> str:
    """解析 CSV 文本为表格"""
    import csv, io

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return "❌ 空数据"

    out = [f"行数: {len(rows)}, 列数: {len(rows[0]) if rows else 0}\n"]
    for i, row in enumerate(rows):
        if i > max_rows:
            out.append(f"... 还有 {len(rows) - max_rows} 行未显示")
            break
        out.append(" | ".join(f"{c:20}" if len(c) < 20 else c[:18] + ".." for c in row))
        if i == 0:
            out.append("-" * min(80, len(row) * 22))

    return "\n".join(out)


def _tool_diff_text(text1: str, text2: str, context_lines: int = 3) -> str:
    """比较两段文本的差异"""
    import difflib
    lines1 = text1.splitlines(keepends=True)
    lines2 = text2.splitlines(keepends=True)
    diff = difflib.unified_diff(lines1, lines2, n=context_lines)
    result = "".join(diff)
    if not result:
        return "✅ 两段文本完全相同"
    return result[:10000]


def _tool_count_tokens(text: str, model: str = "gpt-4o") -> str:
    """估算文本的 token 数量（近似）"""
    # 简单估算：中文字 ≈ 2 token, 英文 ≈ 0.25 token/char
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    other_chars = len(text) - chinese_chars
    tokens = chinese_chars * 2 + other_chars // 4
    return f"字符数: {len(text)}\n估算 tokens: ~{tokens}\n(基于模型 {model} 的近似估算)"


# --- 时间工具 ---

def _tool_get_time(timezone: str = "Asia/Shanghai") -> str:
    """获取当前日期和时间信息"""
    try:
        from datetime import datetime, timezone, timedelta
        # 简单时区处理
        tz_offsets = {
            "Asia/Shanghai": 8, "Asia/Tokyo": 9, "Asia/Singapore": 8,
            "America/New_York": -5, "America/Chicago": -6, "America/Los_Angeles": -8,
            "Europe/London": 0, "Europe/Berlin": 1, "Europe/Paris": 1,
            "Australia/Sydney": 11, "Pacific/Auckland": 13, "UTC": 0,
        }
        offset = tz_offsets.get(timezone, 8)
        now = datetime.now(timezone.utc) + timedelta(hours=offset)
        return f"当前时间 ({timezone}):\n{now.strftime('%Y-%m-%d %H:%M:%S %A')}\n\
Unix 时间戳: {int(time.time())}\n\
UTC 偏移: UTC{'+' if offset >= 0 else ''}{offset}"
    except Exception as e:
        return f"❌ 时间获取失败: {e}"


def _tool_calculate(expression: str) -> str:
    """执行数学计算（安全沙箱）"""
    # 只允许安全的数学运算
    allowed = set("0123456789+-*/()., %sqrtpisinlog")
    cleaned = "".join(c for c in expression if c in allowed or c.isalpha())
    try:
        import math
        ns = {"__builtins__": {}, "math": math}
        result = eval(cleaned, ns)
        return f"{expression} = {result}"
    except Exception as e:
        return f"❌ 计算失败: {e}"


# --- 多媒体/信息工具 ---

def _tool_weather(location: str) -> str:
    """获取天气信息"""
    import httpx
    try:
        resp = httpx.get(
            f"https://wttr.in/{urllib.parse.quote(location)}?format=%C+%t+%h+%w&m",
            timeout=10,
        )
        return f"📍 {location}: {resp.text.strip()}"
    except Exception as e:
        return f"❌ 天气查询失败: {e}"


def _tool_hash_text(text: str, algorithm: str = "md5") -> str:
    """计算文本的哈希值"""
    import hashlib
    algos = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha256": hashlib.sha256}
    h = algos.get(algorithm, hashlib.md5)(text.encode()).hexdigest()
    return f"{algorithm}: {h}"


def _tool_url_analyze(url: str) -> str:
    """分析 URL 的各个组成部分"""
    parsed = urllib.parse.urlparse(url)
    parts = {
        "协议": parsed.scheme,
        "域名": parsed.netloc,
        "路径": parsed.path or "/",
        "查询参数": parsed.query or "无",
        "锚点": parsed.fragment or "无",
    }
    # 解析查询参数
    params = urllib.parse.parse_qs(parsed.query)
    if params:
        parts["参数详情"] = "\n".join(f"  {k}: {', '.join(v)}" for k, v in params.items())

    return "\n".join(f"{k}: {v}" for k, v in parts.items())


# ==================== 注册所有工具 ====================


def _init_default_tools(registry: ToolRegistry):
    """注册所有内置工具（按类别分组）"""

    # ====== Web 工具 (3) ======
    registry.register(
        name="web_search",
        description="搜索互联网获取最新信息。适用于查找资料、新闻、验证事实。",
        input_schema={
            "type": "object", "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {"type": "integer", "description": "返回结果数量", "default": 3},
            }, "required": ["query"],
        }, handler=_tool_web_search,
    )

    registry.register(
        name="fetch_page",
        description="抓取指定网页的正文内容。适用于阅读文章、文档等。",
        input_schema={
            "type": "object", "properties": {
                "url": {"type": "string", "description": "网页 URL"},
            }, "required": ["url"],
        }, handler=_tool_fetch_page,
    )

    registry.register(
        name="check_url",
        description="检查 URL 是否可达，返回 HTTP 状态码和响应信息。",
        input_schema={
            "type": "object", "properties": {
                "url": {"type": "string", "description": "要检查的 URL"},
            }, "required": ["url"],
        }, handler=_tool_check_url,
    )

    # ====== 文件系统工具 (5) ======
    registry.register(
        name="read_file",
        description="读取文件内容。路径相对于安全工作目录 /tmp/awb_workspace/。",
        input_schema={
            "type": "object", "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "max_chars": {"type": "integer", "description": "最大读取字符数", "default": 50000},
            }, "required": ["path"],
        }, handler=_tool_read_file,
    )

    registry.register(
        name="write_file",
        description="写入文件内容（会覆盖已存在的文件）。路径相对于安全工作目录。",
        input_schema={
            "type": "object", "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "文件内容"},
            }, "required": ["path", "content"],
        }, handler=_tool_write_file,
    )

    registry.register(
        name="edit_file",
        description="编辑已有文件，替换其中的文本内容。",
        input_schema={
            "type": "object", "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "old_text": {"type": "string", "description": "要替换的旧文本"},
                "new_text": {"type": "string", "description": "新文本"},
            }, "required": ["path", "old_text", "new_text"],
        }, handler=_tool_edit_file,
    )

    registry.register(
        name="list_files",
        description="列出目录中的文件和子目录。",
        input_schema={
            "type": "object", "properties": {
                "path": {"type": "string", "description": "目录路径", "default": "."},
                "pattern": {"type": "string", "description": "文件名过滤关键词", "default": ""},
            }, "required": [],
        }, handler=_tool_list_files,
    )

    registry.register(
        name="grep_search",
        description="在文件中搜索文本内容。",
        input_schema={
            "type": "object", "properties": {
                "pattern": {"type": "string", "description": "要搜索的文本"},
                "path": {"type": "string", "description": "搜索目录", "default": "."},
                "include": {"type": "string", "description": "文件后缀过滤，如 .py,.js", "default": ""},
            }, "required": ["pattern"],
        }, handler=_tool_grep_search,
    )

    # ====== Shell / 代码 / Git 工具 (4) ======
    registry.register(
        name="run_shell",
        description="在沙箱中执行 shell 命令。适用于文件操作、项目构建、运行脚本等。注意：不能访问用户主目录以外。",
        input_schema={
            "type": "object", "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
                "timeout": {"type": "integer", "description": "超时秒数", "default": 15},
            }, "required": ["command"],
        }, handler=_tool_run_shell,
    )

    registry.register(
        name="run_code",
        description="在安全沙箱中执行 Python 代码并返回运行结果。注意：代码必须有 print() 输出。",
        input_schema={
            "type": "object", "properties": {
                "code": {"type": "string", "description": "要执行的 Python 代码"},
            }, "required": ["code"],
        }, handler=_tool_run_code,
    )

    registry.register(
        name="git_status",
        description="检查 Git 仓库的状态、分支和最近提交记录。",
        input_schema={
            "type": "object", "properties": {
                "path": {"type": "string", "description": "Git 仓库目录", "default": "."},
            }, "required": [],
        }, handler=_tool_git_status,
    )

    # ====== 数据处理工具 (5) ======
    registry.register(
        name="parse_json",
        description="解析 JSON 数据并格式化输出。适用于查看和调试 JSON 结构。",
        input_schema={
            "type": "object", "properties": {
                "text": {"type": "string", "description": "JSON 文本"},
                "format_output": {"type": "boolean", "description": "是否格式化输出", "default": True},
            }, "required": ["text"],
        }, handler=_tool_parse_json,
    )

    registry.register(
        name="parse_csv",
        description="解析 CSV 数据并以表格形式展示。不包含文件操作，需要传入 CSV 文本。",
        input_schema={
            "type": "object", "properties": {
                "text": {"type": "string", "description": "CSV 文本内容"},
                "max_rows": {"type": "integer", "description": "最大显示行数", "default": 30},
            }, "required": ["text"],
        }, handler=_tool_parse_csv,
    )

    registry.register(
        name="diff_text",
        description="比较两段文本的差异，输出类似 git diff 的结果。",
        input_schema={
            "type": "object", "properties": {
                "text1": {"type": "string", "description": "原始文本"},
                "text2": {"type": "string", "description": "修改后的文本"},
                "context_lines": {"type": "integer", "description": "上下文行数", "default": 3},
            }, "required": ["text1", "text2"],
        }, handler=_tool_diff_text,
    )

    registry.register(
        name="count_tokens",
        description="估算文本的 token 数量（近似值）。适用于评估 LLM 调用的成本。",
        input_schema={
            "type": "object", "properties": {
                "text": {"type": "string", "description": "要估算的文本"},
                "model": {"type": "string", "description": "模型名称", "default": "gpt-4o"},
            }, "required": ["text"],
        }, handler=_tool_count_tokens,
    )

    registry.register(
        name="hash_text",
        description="计算文本的哈希值（MD5/SHA1/SHA256）。",
        input_schema={
            "type": "object", "properties": {
                "text": {"type": "string", "description": "要计算哈希的文本"},
                "algorithm": {"type": "string", "description": "算法 (md5/sha1/sha256)", "default": "md5"},
            }, "required": ["text"],
        }, handler=_tool_hash_text,
    )

    # ====== 时间 / 信息工具 (3) ======
    registry.register(
        name="get_time",
        description="获取当前日期、时间、星期和 Unix 时间戳。支持多个时区。",
        input_schema={
            "type": "object", "properties": {
                "timezone": {"type": "string", "description": "时区，如 Asia/Shanghai, UTC, America/New_York", "default": "Asia/Shanghai"},
            }, "required": [],
        }, handler=_tool_get_time,
    )

    registry.register(
        name="calculate",
        description="执行数学计算。支持 +-*/ 和 math 模块函数。",
        input_schema={
            "type": "object", "properties": {
                "expression": {"type": "string", "description": "数学表达式，如 1+2*3 或 math.sqrt(16)"},
            }, "required": ["expression"],
        }, handler=_tool_calculate,
    )

    registry.register(
        name="weather",
        description="查询指定城市的当前天气情况（温度、湿度、风向）。",
        input_schema={
            "type": "object", "properties": {
                "location": {"type": "string", "description": "城市名称，如 Beijing, Shanghai, London"},
            }, "required": ["location"],
        }, handler=_tool_weather,
    )

    registry.register(
        name="url_analyze",
        description="分析 URL 的结构：协议、域名、路径、查询参数等。",
        input_schema={
            "type": "object", "properties": {
                "url": {"type": "string", "description": "要分析的 URL"},
            }, "required": ["url"],
        }, handler=_tool_url_analyze,
    )
