"""
arxiv_fetcher.py — 双引擎混合抓取器 (Hybrid Fetcher)

引擎路由规则：
  - RSS 引擎（主引擎）：target_date == 最新业务日期时使用，与网站 New Submissions
    完全同步，一次请求返回全部当日新提交，无需分页。
  - Search API 引擎（历史引擎）：target_date < 最新业务日期时使用，通过
    submittedDate 时间窗口过滤历史日期的论文，支持分页。

对外只暴露一个入口：fetch_papers(target_date, category, latest_date)
"""

import time
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser

import feedparser
import requests

logger = logging.getLogger(__name__)

ARXIV_RSS_BASE = "http://export.arxiv.org/rss/"
ARXIV_SEARCH_BASE = "http://export.arxiv.org/api/query"
REQUEST_TIMEOUT = 30       # 秒
SEARCH_PAGE_SIZE = 500     # Search API 每页最大条数
SEARCH_PAGE_DELAY = 3      # 翻页间隔（秒），遵守 arXiv API 速率限制


@dataclass
class Paper:
    """单篇论文的结构化数据。"""
    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    url: str
    title_zh: str = ""
    abstract_zh: str = ""
    core_value: str = ""               # 1-2句核心贡献提炼（非科普）
    abstract_en_highlighted: str = ""  # 原文摘要，关键词 <mark> 高亮


# ── HTML 工具 ──────────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    """从 HTML 字符串中提取纯文本内容的辅助类。"""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _strip_html(text: str) -> str:
    """
    剥离 HTML 标签，返回纯文本，并折叠多余空白。

    arXiv RSS 的摘要字段可能含有 <p>、<br/> 等 HTML 标签，
    使用 stdlib HTMLParser 而非正则，以正确处理嵌套或残缺标签。

    Args:
        text: 可能含 HTML 标签的原始字符串。

    Returns:
        去除标签并折叠空白后的纯文本字符串。
    """
    extractor = _TextExtractor()
    extractor.feed(text)
    # 折叠所有连续空白（空格、换行、制表符）为单个空格
    return " ".join(extractor.get_text().split())


# ── 作者解析 ───────────────────────────────────────────────────────────────

def _parse_authors_rss(author_str: str) -> list[str]:
    """
    解析 RSS entry 中的作者字符串，返回作者名列表。

    arXiv RSS 的 author 字段为纯文本，作者之间以逗号或分号分隔。
    优先尝试逗号分隔；若仅得到一个元素且字符串含分号，改用分号分隔。

    Args:
        author_str: 原始作者字符串，如 "Alice Smith, Bob Jones"。

    Returns:
        作者名列表，已去除首尾空白及空字符串。
    """
    if not author_str:
        return []
    parts = [p.strip() for p in author_str.split(",")]
    if len(parts) == 1 and ";" in author_str:
        parts = [p.strip() for p in author_str.split(";")]
    return [p for p in parts if p]


def _parse_authors_atom(entry: feedparser.FeedParserDict) -> list[str]:
    """
    解析 Atom API entry 中的结构化作者列表。

    Atom API 的 authors 字段是含 name 属性的对象列表，
    与 RSS 的纯文本字符串不同。

    Args:
        entry: feedparser 解析的单条 Atom entry 对象。

    Returns:
        作者名列表，已去除首尾空白及空字符串。
    """
    authors = []
    for author in entry.get("authors", []):
        name = author.get("name", "").strip()
        if name:
            authors.append(name)
    return authors


# ── RSS 引擎（主引擎，当日论文）────────────────────────────────────────────

def _parse_rss_entry(entry: feedparser.FeedParserDict) -> Paper | None:
    """
    将 RSS entry 转换为 Paper dataclass。

    仅处理 announce_type == "new" 的条目；
    replace、replace-cross（替换版本）和 cross（跨领域收录）均返回 None。

    Args:
        entry: feedparser 解析的单条 RSS entry 对象。

    Returns:
        Paper 对象；非新提交或解析失败时返回 None。
    """
    try:
        # arxiv:announce_type 通过 feedparser 命名空间映射访问
        announce_type = entry.get("arxiv_announce_type", "")
        logger.debug(f"RSS entry announce_type={announce_type!r} link={entry.get('link', '')}")

        # 只保留全新提交，过滤掉替换版本和跨领域收录
        if announce_type != "new":
            return None

        # entry.link 形如 "http://arxiv.org/abs/2504.12345v1"，去掉版本号
        raw_link = entry.get("link", "")
        arxiv_id = raw_link.split("/abs/")[-1].split("v")[0]

        title = entry.get("title", "").replace("\n", " ").strip()

        # RSS 摘要可能含 HTML 标签（如 <p>、<br/>），需剥离为纯文本
        abstract = _strip_html(entry.get("summary", ""))

        # RSS 的 author 字段是逗号或分号分隔的纯文本字符串
        authors = _parse_authors_rss(entry.get("author", ""))

        url = raw_link or f"https://arxiv.org/abs/{arxiv_id}"

        return Paper(arxiv_id=arxiv_id, title=title, abstract=abstract, authors=authors, url=url)
    except Exception as e:
        logger.warning(f"解析 RSS entry 失败，跳过：{e}")
        return None


def _fetch_via_rss(category: str, max_results: int | None = None) -> list[Paper]:
    """
    RSS 引擎：抓取 arXiv 当日公告的"新提交"论文。

    RSS Feed 与网站 New Submissions 完全同步，单次请求返回当日所有条目，
    无需分页，也无需指定日期（始终返回最新批次）。

    Args:
        category:    arXiv 分类标识，如 'quant-ph'。
        max_results: 返回论文数量上限；None 表示不限制。

    Returns:
        announce_type 为 "new" 的 Paper 列表。

    Raises:
        requests.RequestException: 网络请求失败时抛出。
    """
    url = f"{ARXIV_RSS_BASE}{category}"
    logger.info(f"[RSS 引擎] 请求：{url}")

    resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"Accept": "application/rss+xml"})
    resp.raise_for_status()

    feed = feedparser.parse(resp.text)
    logger.debug(f"[RSS 引擎] 共 {len(feed.entries)} 条 entry，过滤 announce_type='new'")

    papers: list[Paper] = []
    for entry in feed.entries:
        paper = _parse_rss_entry(entry)
        if paper:
            papers.append(paper)

    if max_results is not None and max_results > 0:
        papers = papers[:max_results]
        logger.info(f"[RSS 引擎] max_results={max_results}，截断后返回 {len(papers)} 篇")

    return papers


# ── Search API 引擎（历史引擎，支持任意日期）──────────────────────────────

def _parse_atom_entry(entry: feedparser.FeedParserDict) -> Paper | None:
    """
    将 Atom Search API entry 转换为 Paper dataclass。

    Atom API 不含 announce_type 字段，通过 submittedDate 时间窗口查询
    已保证结果均为指定日期的新提交论文。

    Args:
        entry: feedparser 解析的单条 Atom entry 对象。

    Returns:
        Paper 对象；解析失败时返回 None。
    """
    try:
        # entry.id 形如 "http://arxiv.org/abs/2504.12345v1"
        raw_id = entry.get("id", "")
        arxiv_id = raw_id.split("/abs/")[-1].split("v")[0]

        title = entry.get("title", "").replace("\n", " ").strip()

        # Atom API 返回的摘要为纯文本（偶有多余换行），折叠空白即可
        abstract = " ".join(entry.get("summary", "").split())

        authors = _parse_authors_atom(entry)

        url = f"https://arxiv.org/abs/{arxiv_id}"

        return Paper(arxiv_id=arxiv_id, title=title, abstract=abstract, authors=authors, url=url)
    except Exception as e:
        logger.warning(f"解析 Atom entry 失败，跳过：{e}")
        return None


def _fetch_via_search_api(target_date: date, category: str, max_results: int | None = None) -> list[Paper]:
    """
    Search API 引擎：通过 submittedDate 时间窗口抓取指定历史日期的论文。

    使用 arXiv Atom Search API，以 submittedDate 范围限定目标日期，
    支持分页（每页 500 条），翻页间隔 3 秒以遵守速率限制。

    Args:
        target_date: 目标历史日期。
        category:    arXiv 分类标识。
        max_results: 返回论文数量上限；None 表示不限制。

    Returns:
        指定日期提交的 Paper 列表。
    """
    # arXiv submittedDate 格式：YYYYMMDDHHMMSS
    date_str = target_date.strftime("%Y%m%d")
    search_query = f"cat:{category} AND submittedDate:[{date_str}000000 TO {date_str}235959]"

    # 打印查询字符串，便于核对日期是否正确（不依赖 --verbose）
    print(f"[Search API] 查询字符串：{search_query}")

    papers: list[Paper] = []
    start = 0

    while True:
        params = {
            "search_query": search_query,
            "start": str(start),
            "max_results": str(SEARCH_PAGE_SIZE),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        query_string = urllib.parse.urlencode(params)
        request_url = f"{ARXIV_SEARCH_BASE}?{query_string}"
        logger.info(f"[Search API 引擎] 请求第 {start // SEARCH_PAGE_SIZE + 1} 页：start={start}")
        logger.info(f"[Search API 引擎] 完整 URL：{request_url}")

        try:
            with urllib.request.urlopen(request_url, timeout=REQUEST_TIMEOUT) as resp:
                raw = resp.read()
        except Exception as e:
            logger.error(f"[Search API 引擎] 请求失败（start={start}）：{e}")
            raise

        feed = feedparser.parse(raw)
        entries = feed.entries
        logger.debug(f"[Search API 引擎] 本页返回 {len(entries)} 条 entry")

        for entry in entries:
            paper = _parse_atom_entry(entry)
            if paper:
                papers.append(paper)

        # 若已达到 max_results，提前停止翻页
        if max_results is not None and len(papers) >= max_results:
            papers = papers[:max_results]
            logger.info(f"[Search API 引擎] 已达 max_results={max_results}，停止翻页")
            break

        # 若本页结果少于页面大小，说明已是最后一页
        if len(entries) < SEARCH_PAGE_SIZE:
            break

        start += SEARCH_PAGE_SIZE
        # 遵守 arXiv API 速率限制：翻页前等待 3 秒
        logger.debug(f"[Search API 引擎] 翻页等待 {SEARCH_PAGE_DELAY} 秒...")
        time.sleep(SEARCH_PAGE_DELAY)

    return papers


# ── 公开入口：自动路由引擎 ──────────────────────────────────────────────────

def fetch_papers(
    target_date: date | str,
    category: str = "quant-ph",
    latest_date: date | None = None,
    max_results: int | None = None,
) -> list[Paper]:
    """
    混合抓取器入口：根据 target_date 与 latest_date 的关系自动选择引擎。

    路由规则：
      - target_date == latest_date → RSS 引擎（100% 完整的当日数据）
      - target_date <  latest_date → Search API 引擎（历史日期回溯）

    Args:
        target_date:  目标日期（date 对象或 'YYYY-MM-DD' 字符串）。
        category:     arXiv 分类标识，如 'quant-ph'。
        latest_date:  最新业务日期（由 main.py 的 get_arxiv_latest_date() 计算后
                      传入）。若为 None，则将 target_date 视为历史日期并走
                      Search API 引擎（保守策略，不在此模块重复计算 ET 时区逻辑）。
        max_results:  返回论文数量上限；None 表示不限制（配置中的 null）。

    Returns:
        Paper 列表；若无结果则返回空列表。

    Raises:
        requests.RequestException / urllib.error.URLError: 网络请求失败时透传。
    """
    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)

    use_rss = (latest_date is not None) and (target_date == latest_date)

    if use_rss:
        logger.info(f"[Hybrid Fetcher] 使用 RSS 引擎（当日批次 {target_date}）")
        papers = _fetch_via_rss(category, max_results=max_results)
    else:
        logger.info(f"[Hybrid Fetcher] 使用 Search API 引擎（历史日期 {target_date}）")
        papers = _fetch_via_search_api(target_date, category, max_results=max_results)

    logger.info(f"[Hybrid Fetcher] 共抓取 {len(papers)} 篇 {category} 论文（{target_date}）")
    return papers
