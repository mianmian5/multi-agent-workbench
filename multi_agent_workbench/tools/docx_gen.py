"""DOCX 生成工具——自动选择最佳引擎

策略：
1. macOS: 用 textutil（Apple 内置，100% 兼容 WPS/Word）
2. 其他平台: 用纯 Python 生成标准 OOXML（降级方案）
"""

import os
import re
import subprocess
import tempfile
import zipfile
import io

# ==================== Markdown → HTML（两种引擎共用） ====================


def _render_inline(text: str) -> str:
    """渲染行内 Markdown：粗体、斜体、代码、链接"""
    text = _e(text)
    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'[图片: \1]', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<![\s*])\*(?![\s*])(.+?)\*', r'<em>\1</em>', text)
    return text


def _md_to_html(md_text: str, title: str = "") -> str:
    """将 Markdown 转为 HTML（含行内渲染）"""
    parts = []
    if title:
        parts.append(f"<h1>{_render_inline(title)}</h1>")

    in_code = False
    for line in md_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            parts.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            parts.append(_e(line))
            continue
        if not stripped:
            continue
        if stripped.startswith("### "):
            parts.append(f"<h3>{_render_inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            parts.append(f"<h2>{_render_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# ") and not title:
            parts.append(f"<h1>{_render_inline(stripped[2:])}</h1>")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            parts.append(f"<li>{_render_inline(stripped[2:])}</li>")
        elif re.match(r"^\d+[.、]\s", stripped):
            parts.append(f"<li>{_render_inline(stripped)}</li>")
        else:
            parts.append(f"<p>{_render_inline(stripped)}</p>")
    return "\n".join(parts)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body {{ font-family: -apple-system, "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 12pt; line-height: 1.6; }}
h1 {{ font-size: 22pt; margin-top: 20pt; }} h2 {{ font-size: 16pt; margin-top: 16pt; }} h3 {{ font-size: 14pt; margin-top: 12pt; }}
p {{ margin: 6pt 0; }} li {{ margin: 3pt 0 3pt 20pt; }}
pre {{ background: #f5f6fa; padding: 10pt; font-family: "Courier New", monospace; }}
</style></head><body>{body}</body></html>"""


def _e(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


# ==================== 引擎 1：macOS textutil（优先） ====================


def _has_textutil() -> bool:
    """检查 textutil 是否可用"""
    try:
        return subprocess.run(["which", "textutil"], capture_output=True).returncode == 0
    except Exception:
        return False


def _make_docx_textutil(markdown_text: str, title: str = "") -> bytes:
    """用 macOS textutil 将 HTML 转 DOCX"""
    html_body = _md_to_html(markdown_text, title)
    html = _HTML_TEMPLATE.replace("{body}", html_body)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        docx_path = html_path + ".docx"
        subprocess.run(
            ["textutil", "-convert", "docx", "-output", docx_path, html_path],
            capture_output=True, timeout=15, check=True,
        )
        with open(docx_path, "rb") as f:
            return f.read()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"textutil 转换失败: {e.stderr.decode() if e.stderr else '未知错误'}")
    finally:
        for p in [html_path, docx_path]:
            try:
                os.unlink(p)
            except Exception:
                pass


# ==================== 引擎 2：纯 Python OOXML（降级方案） ====================


def _make_docx_fallback(markdown_text: str, title: str = "") -> bytes:
    """纯 Python 生成标准 OOXML DOCX"""
    buf = io.BytesIO()
    body_parts = []

    if title:
        body_parts.append(_xml_p(f'<w:r><w:rPr><w:b/><w:sz w:val="44"/></w:rPr><w:t xml:space="preserve">{_e(title)}</w:t></w:r>', "Title"))

    in_code = False
    for line in markdown_text.split("\n"):
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            body_parts.append(_xml_p(f'<w:r><w:rPr><w:rFonts w:ascii="Courier New"/><w:sz w:val="20"/></w:rPr><w:t xml:space="preserve">{_e(line)}</w:t></w:r>', "Code"))
            continue
        if not s:
            continue
        if s.startswith("### "):
            body_parts.append(_xml_p(f'<w:r><w:rPr><w:b/><w:sz w:val="28"/></w:rPr><w:t xml:space="preserve">{_e(s[4:])}</w:t></w:r>', "Heading2"))
        elif s.startswith("## "):
            body_parts.append(_xml_p(f'<w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr><w:t xml:space="preserve">{_e(s[3:])}</w:t></w:r>', "Heading1"))
        elif s.startswith("# ") and not title:
            body_parts.append(_xml_p(f'<w:r><w:rPr><w:b/><w:sz w:val="44"/></w:rPr><w:t xml:space="preserve">{_e(s[2:])}</w:t></w:r>', "Title"))
        elif s.startswith("- ") or s.startswith("* "):
            body_parts.append(_xml_p(f'<w:r><w:t xml:space="preserve">{_e("• " + s[2:])}</w:t></w:r>'))
        else:
            body_parts.append(_xml_p(f'<w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">{_e(s)}</w:t></w:r>'))

    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '  <w:body>\n'
        + "\n".join(f"    {p}" for p in body_parts) + "\n"
        '    <w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:mar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>\n'
        '  </w:body>\n</w:document>'
    )

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", doc_xml)

    return buf.getvalue()


def _xml_p(runs: str, style: str = "") -> str:
    pPr = ""
    if style == "Title":
        pPr = '<w:pPr><w:pStyle w:val="Title"/><w:spacing w:before="240" w:after="120"/></w:pPr>'
    elif style in ("Heading1", "Heading2"):
        pPr = f'<w:pPr><w:pStyle w:val="{style}"/><w:spacing w:before="240" w:after="120"/></w:pPr>'
    return f"<w:p>{pPr}{runs}</w:p>"


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


# ==================== 统一入口 ====================


def _html_to_pdf(html_text: str) -> bytes:
    """纯 Python 将 HTML 转为 PDF（无额外依赖）"""
    import zlib, struct

    # 提取文本（去掉 HTML 标签）
    import re
    text = re.sub(r'<[^>]+>', ' ', html_text)
    text = re.sub(r'&[a-z]+;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    lines = []
    for line in text.split('\n'):
        line = line.strip()
        if line:
            lines.append(line)

    if not lines:
        lines = ["(空文档)"]

    # 构建 PDF 对象
    objects = []
    def add_obj(data):
        objects.append(data)
        return len(objects)

    # 编码文本 - 只处理 ASCII，非 ASCII 用近似替换
    def enc(text):
        return text.encode('latin-1', errors='replace')

    # 构建页面内容
    content_lines = [b'BT', b'/F1 11 Tf']
    y = 760
    for line in lines:
        if len(line) > 90:
            line = line[:87] + '...'
        safe = enc(line)
        content_lines.append(b'56 ' + str(y).encode() + b' Td (' + safe + b') Tj')
        y -= 16
        if y < 40:
            break
    content_lines.append(b'ET')
    content_stream = b'\n'.join(content_lines)
    compressed = zlib.compress(content_stream)

    # PDF 文件结构
    font = add_obj(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    ct_stream = add_obj(b'<< /Length ' + str(len(compressed)).encode() + b' /Filter /FlateDecode >> stream\n' + compressed + b'\nendstream')
    resources = b'<< /Font << /F1 ' + str(font).encode() + b' 0 R >> >>'
    page = add_obj(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents ' + str(ct_stream).encode() + b' 0 R /Resources ' + resources + b' >>')
    pages = add_obj(b'<< /Type /Pages /Kids [' + str(page).encode() + b' 0 R] /Count 1 >>')
    catalog = add_obj(b'<< /Type /Catalog /Pages ' + str(pages).encode() + b' 0 R >>')

    pdf_parts = [b'%PDF-1.4']
    offsets = []
    for i, obj in enumerate(objects):
        offsets.append(sum(len(p) for p in pdf_parts))
        pdf_parts.append(str(i+1).encode() + b' 0 obj ' + obj + b' endobj\n')

    xref_offset = sum(len(p) for p in pdf_parts)
    xref = b'xref\n0 ' + str(len(objects)+1).encode() + b'\n' + b'0'*10 + b' 65535 f \n'
    for off in offsets:
        xref += f'{off:010d} 00000 n \n'.encode()

    pdf_parts += [xref, b'trailer << /Size ' + str(len(objects)+1).encode() + b' /Root ' + str(catalog).encode() + b' 0 R >>\nstartxref\n', str(xref_offset).encode(), b'\n%%EOF']
    return b''.join(pdf_parts)


def markdown_to_docx(markdown_text: str, title: str = "") -> bytes:
    """将 Markdown 转为 DOCX

    自动选择引擎：
    - macOS: textutil（Apple 官方引擎）
    - 其他: 纯 Python OOXML
    """
    if _has_textutil():
        return _make_docx_textutil(markdown_text, title)
    return _make_docx_fallback(markdown_text, title)


def markdown_to_pdf(markdown_text: str, title: str = "") -> bytes:
    """将 Markdown 转为 PDF（纯 Python，无需外部依赖）"""
    html_body = _md_to_html(markdown_text, title)
    html = _HTML_TEMPLATE.replace("{body}", html_body)
    return _html_to_pdf(html)
