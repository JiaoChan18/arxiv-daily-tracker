"""
markdown_writer.py — 将分析后的论文列表写成结构化 Markdown 报告。

输出路径：output/YYYY-MM-DD/quant-ph-YYYY-MM-DD.md
每篇论文包含：序号、中文标题、英文标题、作者、arXiv 链接、
核心价值（blockquote）、英文摘要（关键词加粗）、中文摘要（关键词加粗）。
"""

import logging
import re
from datetime import date
from pathlib import Path

from fetcher.arxiv_fetcher import Paper

logger = logging.getLogger(__name__)

# 匹配 LLM 输出的 <mark>...</mark> 高亮标签；re.DOTALL 允许内容跨行
_MARK_RE = re.compile(r'<mark>(.*?)</mark>', re.DOTALL)


def _replace_mark_with_bold(text: str) -> str:
    """
    将 <mark>...</mark> 替换为 **...**，以兼容 Obsidian 及手机端 Markdown 渲染。

    LLM 产出的高亮标签在标准 Markdown 渲染器中不生效；加粗是移动端兼容性最好的强调方式。

    Args:
        text: 原始 Markdown 文本。

    Returns:
        替换后的文本。
    """
    return _MARK_RE.sub(r'**\1**', text)


def write(papers: list[Paper], target_date: date, output_dir: Path, category: str = "quant-ph") -> Path:
    """
    生成当日论文的 Markdown 报告文件。

    Args:
        papers:      已翻译的 Paper 列表。
        target_date: 报告日期。
        output_dir:  输出根目录（如 ./output），函数内自动创建子目录。
        category:    arXiv 分类标识，用于文件名。

    Returns:
        生成的 Markdown 文件路径。
    """
    date_str = target_date.isoformat()
    day_dir = output_dir / date_str
    day_dir.mkdir(parents=True, exist_ok=True)

    md_path = day_dir / f"{category}-{date_str}.md"

    lines = _build_markdown(papers, target_date, category)

    # 将 <mark> 标签转为 **加粗**，使 Obsidian 及手机端能正确渲染重点内容
    content = _replace_mark_with_bold("\n".join(lines))
    md_path.write_text(content, encoding="utf-8")
    logger.info(f"Markdown 报告已写入：{md_path}（共 {len(papers)} 篇）")

    return md_path


def _build_markdown(papers: list[Paper], target_date: date, category: str) -> list[str]:
    """
    构建 Markdown 内容的行列表。

    Args:
        papers:      Paper 列表。
        target_date: 报告日期。
        category:    分类标识，显示在标题中。

    Returns:
        Markdown 行列表（join 后写文件）。
    """
    lines: list[str] = []

    # 报告头部
    lines.append(f"# arXiv {category} 每日速递 — {target_date.isoformat()}")
    lines.append("")
    lines.append(f"> 共收录 **{len(papers)}** 篇论文，标题及摘要已由 AI 翻译为中文。")
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, paper in enumerate(papers, start=1):
        # 优先显示中文标题，若为空则回退到英文
        title_display = paper.title_zh or paper.title

        authors_str = "、".join(paper.authors[:5])
        if len(paper.authors) > 5:
            authors_str += f" 等（共 {len(paper.authors)} 人）"

        lines.append(f"## {i}. {title_display}")
        lines.append("")
        lines.append(f"**英文原题**：{paper.title}")
        lines.append("")
        lines.append(f"**作者**：{authors_str}")
        lines.append("")
        lines.append(f"**链接**：<{paper.url}>")
        lines.append("")

        # Core Value 区块——仅在字段非空时渲染，防止出现空 blockquote
        if paper.core_value:
            lines.append("**🌟 Core Value**")
            lines.append("")
            lines.append(f"> {paper.core_value}")
            lines.append("")

        lines.append("**Abstract (Original)**")
        lines.append("")
        # 优先使用关键词加粗版本；LLM 失败时回退到原始英文
        lines.append(paper.abstract_en_highlighted or paper.abstract)
        lines.append("")
        lines.append("**中文摘要**")
        lines.append("")
        lines.append(paper.abstract_zh or paper.abstract)
        lines.append("")
        lines.append("---")
        lines.append("")

    return lines
