"""Web 搜索工具——真实搜索互联网

使用 Bing 网页搜索（免费，无需 API Key）
和 Wikipedia API 作为补充数据源。
"""

import re
import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = 5
MAX_RESULTS = 5


# ==================== Bing 搜索引擎 ====================


def search_bing(query: str, max_results: int = MAX_RESULTS) -> list[dict]:
    """通过 Bing 搜索网页（免费，无需 API Key）

    Returns:
        [{"title": str, "url": str, "snippet": str}, ...]
    """
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                "https://www.bing.com/search",
                params={"q": query, "setlang": "zh-Hans"},
                headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
            )
            resp.raise_for_status()
            return _parse_bing_results(resp.text, max_results)
    except Exception as e:
        return [{"title": "[搜索失败]", "url": "", "snippet": f"搜索出错: {e}"}]


def _parse_bing_results(html: str, max_results: int) -> list[dict]:
    """解析 Bing 搜索结果"""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Bing 的结果区
    for result in soup.select(".b_algo")[:max_results]:
        title_el = result.select_one("h2 a")
        snippet_el = result.select_one(".b_caption p, .b_lineclamp2, .b_algoSlug")

        if title_el:
            title = title_el.get_text(strip=True)
            url = title_el.get("href", "")
            snippet = ""
            if snippet_el:
                snippet = snippet_el.get_text(strip=True)
            results.append({"title": title, "url": url, "snippet": snippet})

    return results


# ==================== Wikipedia 搜索 ====================


def search_wikipedia(query: str, lang: str = "zh") -> list[dict]:
    """通过 Wikipedia API 搜索（适合百科类查询）

    Returns:
        [{"title": str, "url": str, "snippet": str}, ...]
    """
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "srlimit": 3,
                },
                headers={"User-Agent": "MultiAgentWorkbench/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("query", {}).get("search", []):
                title = item.get("title", "")
                snippet = BeautifulSoup(item.get("snippet", ""), "html.parser").get_text(strip=True)
                results.append({
                    "title": title,
                    "url": f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}",
                    "snippet": snippet,
                })
            return results
    except Exception:
        return []


# ==================== 内容抓取 ====================


def fetch_page(url: str, max_chars: int = 8000) -> str:
    """抓取网页正文"""
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text[:max_chars]
    except Exception as e:
        return f"[抓取失败] {url}: {e}"


# ==================== 统一搜索入口 ====================


def search_and_fetch(query: str, max_results: int = 3) -> str:
    """搜索 + 抓取内容，返回整理后的 Markdown

    这是给 SearchAgent 使用的主要接口。
    使用多源搜索策略：
    1. 先用 Bing 搜索
    2. 如果结果少，补充 Wikipedia

    Args:
        query: 搜索关键词
        max_results: 获取前几条结果的内容

    Returns:
        搜索结果的 Markdown 摘要
    """
    # 1. Bing 搜索
    results = search_bing(query, max_results)

    if not results or results[0].get("title") == "[搜索失败]":
        # 2. 尝试 Wikipedia 作为后备
        wiki_results = search_wikipedia(query)
        if wiki_results:
            results = wiki_results
        else:
            return f"⚠️ 搜索「{query}」未返回有效结果。\n\n{results[0].get('snippet', '')}"

    # 3. 补充 Wikipedia 结果
    if len(results) < max_results:
        wiki_results = search_wikipedia(query)
        existing_urls = {r["url"] for r in results}
        for r in wiki_results:
            if r["url"] not in existing_urls:
                results.append(r)
                if len(results) >= max_results:
                    break

    # 格式化输出
    output = [f"## 🔍 搜索结果: {query}", ""]

    for i, r in enumerate(results[:max_results], 1):
        output.append(f"### {i}. {r['title']}")
        output.append(f"**链接:** {r['url']}")
        if r.get("snippet"):
            output.append(f"**摘要:** {r['snippet']}")
        output.append("")

        # 抓取前 2 条的详细内容
        if i <= 2 and r.get("url") and not r["url"].startswith("[搜索结果"):
            content = fetch_page(r["url"], max_chars=3000)
            if not content.startswith("[抓取失败]"):
                output.append(f"**详细内容:**")
                output.append(content[:2000])
                output.append("")

    return "\n".join(output)
