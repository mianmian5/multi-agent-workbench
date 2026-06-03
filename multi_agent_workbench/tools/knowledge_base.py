"""知识库——管理用户上传的文档，让 Agent 能引用用户自己的资料

支持的文件格式：
- .txt / .md → 直接读取
- .csv → 解析为文本
- .pdf → 提取文本（需要 pdfminer.six）

知识库目录结构：
~/.awb_knowledge/
├── meta.json          # 文件索引
├── chunks/            # 文本分块
│   ├── <file_id>.json
│   └── ...
└── raw/               # 原始上传文件
    ├── <file_id>.ext
    └── ...
"""

import hashlib
import json
import os
import re
import time
from pathlib import Path

# 知识库根目录
KB_DIR = Path.home() / ".awb_knowledge"
RAW_DIR = KB_DIR / "raw"
CHUNKS_DIR = KB_DIR / "chunks"
META_FILE = KB_DIR / "meta.json"

# 支持的文件类型
SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".pdf"}

# 分块大小
CHUNK_SIZE = 1000  # 每块约 1000 字
CHUNK_OVERLAP = 100


def _ensure_dirs():
    """确保知识库目录结构存在"""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)


def _load_meta() -> dict:
    """加载文件索引"""
    _ensure_dirs()
    if META_FILE.exists():
        try:
            return json.loads(META_FILE.read_text())
        except Exception:
            pass
    return {"files": [], "version": 1}


def _save_meta(meta: dict):
    """保存文件索引"""
    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2))


def _file_id(filename: str) -> str:
    """根据文件名生成唯一 ID"""
    return hashlib.md5(f"{filename}_{time.time()}".encode()).hexdigest()[:12]


def _split_chunks(text: str) -> list[str]:
    """将文本按段落分块

    策略：按段落切割，每块约 CHUNK_SIZE 字
    """
    paragraphs = re.split(r"\n\s*\n", text)
    chunks = []
    current = []

    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        current.append(p)
        current_text = "\n\n".join(current)
        if len(current_text) >= CHUNK_SIZE:
            chunks.append(current_text)
            # 保留最后一段作为 overlap
            current = [current[-1]] if len(current) > 1 else []

    if current:
        chunks.append("\n\n".join(current))

    return chunks if chunks else [text[:CHUNK_SIZE]]


def _extract_text_from_pdf(filepath: Path) -> str:
    """从 PDF 提取文本（纯 Python，无需外部库）"""
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(str(filepath))
        return text.strip()
    except ImportError:
        pass

    try:
        with open(filepath, "rb") as f:
            raw = f.read()

        # 纯 Python PDF 文本提取
        text_parts = []
        raw_text = raw.decode("latin-1")

        # 方法1: 提取括号内的文本 (Tj 和 TJ 操作符)
        import re
        # 查找 (text) 后面跟着 Tj 的文本
        for m in re.finditer(r'\(([^)]*)\)\s*Tj', raw_text):
            t = m.group(1)
            # 解码 PDF 转义
            t = t.replace('\\n', '\n').replace('\\r', '\r').replace('\\t', '\t')
            t = re.sub(r'\\([0-7]{3})', lambda x: chr(int(x.group(1), 8)), t)
            t = re.sub(r'\\(.)', r'\1', t)
            if t.strip():
                text_parts.append(t)

        # 方法2: 提取括号内的文本（不带 Tj，单纯括号内容）
        if len(text_parts) < 3:
            text_parts = []
            for m in re.finditer(r'\(([^)]{2,})\)', raw_text):
                t = m.group(1)
                if any(c.isalpha() for c in t) and len(t) > 3:
                    text_parts.append(t)

        if text_parts:
            result = "\n".join(text_parts)
            # 清理
            result = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', result)
            return result[:50000]

        # 方法3: 最终 fallback
        text = raw.decode("utf-8", errors="ignore")
        text = re.sub(r"[^\x20-\x7E\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\n]", "", text)
        return text[:50000] if text.strip() else ""
    except Exception:
        return ""


def _extract_text(filepath: Path) -> str:
    """根据文件类型提取文本"""
    suffix = filepath.suffix.lower()

    if suffix in (".txt", ".md"):
        return filepath.read_text(encoding="utf-8", errors="ignore")

    elif suffix == ".csv":
        import csv
        import io

        rows = []
        with open(filepath, newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                rows.append(f"第{i+1}行: {' | '.join(row)}")
        return "\n".join(rows)

    elif suffix == ".pdf":
        return _extract_text_from_pdf(filepath)

    return ""


# ==================== 对外 API ====================


def upload_file(filepath: str, filename: str | None = None) -> dict:
    """上传文件到知识库

    Args:
        filepath: 文件路径
        filename: 原始文件名（用于判断文件类型）

    Returns:
        {"id": str, "name": str, "size": int, "chunks": int, "error": str|null}
    """
    src = Path(filepath)
    if not src.exists():
        return {"error": f"文件不存在: {filepath}"}

    # 用原始文件名判断类型，临时文件可能没有后缀
    type_filename = filename or src.name
    suffix = Path(type_filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return {
            "error": f"不支持的文件类型: {suffix}",
            "supported": list(SUPPORTED_EXTENSIONS),
        }

    _ensure_dirs()

    fid = _file_id(type_filename)
    display_name = filename or src.name

    # 复制原始文件（带正确后缀）
    dest = RAW_DIR / f"{fid}{suffix}"
    dest.write_bytes(src.read_bytes())

    # 提取文本并分块
    text = _extract_text(dest)
    if not text:
        dest.unlink()
        return {"error": "无法提取文件内容，请检查文件是否为空或损坏"}

    chunks = _split_chunks(text)

    # 保存分块
    chunk_data = {
        "file_id": fid,
        "filename": display_name,
        "chunks": chunks,
        "total_chars": len(text),
        "created_at": time.time(),
    }
    (CHUNKS_DIR / f"{fid}.json").write_text(
        json.dumps(chunk_data, ensure_ascii=False)
    )

    # 更新索引
    meta = _load_meta()
    meta["files"].append({
        "id": fid,
        "name": display_name,
        "type": suffix,
        "size": len(text),
        "chunks": len(chunks),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    _save_meta(meta)

    return {
        "id": fid,
        "name": display_name,
        "type": suffix,
        "size": len(text),
        "chunks": len(chunks),
        "total_chars": len(text),
    }


def list_files() -> list[dict]:
    """列出知识库中所有文件"""
    meta = _load_meta()
    return meta.get("files", [])


def delete_file(file_id: str) -> bool:
    """从知识库删除文件"""
    meta = _load_meta()
    before = len(meta["files"])
    meta["files"] = [f for f in meta["files"] if f["id"] != file_id]
    if len(meta["files"]) == before:
        return False

    _save_meta(meta)

    # 删除原始文件和分块
    for f in RAW_DIR.glob(f"{file_id}.*"):
        f.unlink()
    chunk_file = CHUNKS_DIR / f"{file_id}.json"
    if chunk_file.exists():
        chunk_file.unlink()

    return True


def search_knowledge(query: str, max_results: int = 5) -> str:
    """在知识库中搜索相关内容

    使用关键词匹配 + 位置评分，返回最相关的文本块。

    Args:
        query: 搜索关键词
        max_results: 返回结果数量

    Returns:
        Markdown 格式的搜索结果
    """
    keywords = set(re.findall(r"[\w\u4e00-\u9fff]+", query.lower()))

    if not keywords:
        return ""

    results = []

    for chunk_file in CHUNKS_DIR.glob("*.json"):
        try:
            data = json.loads(chunk_file.read_text())
            filename = data.get("filename", "未知文件")

            for i, chunk in enumerate(data.get("chunks", [])):
                chunk_lower = chunk.lower()
                matched = sum(1 for kw in keywords if kw in chunk_lower)
                if matched > 0:
                    # 计算匹配密度作为评分
                    score = matched / (len(chunk) + 1) * 1000
                    results.append((score, filename, i, chunk))
        except Exception:
            continue

    # 按评分排序
    results.sort(key=lambda x: -x[0])

    if not results:
        return ""

    # 格式化为 Markdown
    output = ["## 📚 知识库参考资料", ""]
    seen = set()

    for score, filename, chunk_idx, chunk in results[:max_results]:
        key = f"{filename}#{chunk_idx}"
        if key in seen:
            continue
        seen.add(key)

        output.append(f"### 📄 {filename} (片段 {chunk_idx + 1})")
        # 高亮匹配关键词
        snippet = chunk[:500] + ("..." if len(chunk) > 500 else "")
        output.append(snippet)
        output.append("")

    return "\n".join(output)


def get_knowledge_context(query: str, max_chars: int = 3000) -> str:
    """获取知识库上下文（给 Agent 使用）

    搜索知识库并返回相关内容文本，限制总长度。

    Args:
        query: 搜索查询
        max_chars: 最大返回字符数

    Returns:
        相关文本内容
    """
    result = search_knowledge(query, max_results=3)
    if not result:
        return ""

    # 提取纯文本（去掉 Markdown 标题）
    text = re.sub(r"^#+\s+", "", result, flags=re.MULTILINE)
    return text[:max_chars]


def get_stats() -> dict:
    """获取知识库统计信息"""
    meta = _load_meta()
    files = meta.get("files", [])
    total_chunks = sum(f.get("chunks", 0) for f in files)
    total_size = sum(f.get("size", 0) for f in files)
    return {
        "file_count": len(files),
        "total_chunks": total_chunks,
        "total_size": total_size,
        "supported_formats": list(SUPPORTED_EXTENSIONS),
    }
