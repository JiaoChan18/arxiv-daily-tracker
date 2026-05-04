"""
main.py — arXiv Daily Tracker 的 CLI 入口。

用法：
    python main.py                         # 抓取今日论文，翻译，生成 PDF，发送邮件
    python main.py --date 2026-04-11       # 指定日期
    python main.py --no-email              # 干运行，不发送邮件
    python main.py --verbose               # 开启 DEBUG 日志
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

from fetcher.arxiv_fetcher import fetch_papers
from notifier.email_sender import send
from processor.translator import build_client, translate_paper
from renderer import markdown_writer, pdf_exporter

__version__ = "1.0.0"

_ET = ZoneInfo("America/New_York")
_ARXIV_ANNOUNCE_HOUR_ET = 20  # arXiv 每天约 20:00 ET 发布新文章

# 设为 True 可重新启用 PDF 生成（需同步恢复 config.yaml 中的 pdf 格式及工作流中的 LaTeX 安装步骤）
ENABLE_PDF = False


def _get_recipients(email_cfg: dict) -> list[str]:
    """
    获取收件人列表。优先读取环境变量 SMTP_RECIPIENTS（逗号分隔），
    若未设置则使用 config.yaml 中的 email.recipients。

    Args:
        email_cfg: config.yaml 中的 email 配置段。

    Returns:
        收件人邮箱列表。
    """
    env_val = os.environ.get("SMTP_RECIPIENTS", "").strip()
    if env_val:
        return [addr.strip() for addr in env_val.split(",") if addr.strip()]
    return email_cfg.get("recipients", [])


def _prev_business_day(d: date) -> date:
    """
    返回 d 的前一个工作日（跳过周六、周日）。

    用于将公告日期转换为对应的投稿日期：arXiv 在每个工作日约 14:00 ET 截止
    当日收稿，次工作日公告。因此，公告日 D 的论文绝大多数投稿于 D 的前一个工作日。

    Args:
        d: 参考日期。

    Returns:
        d 前的第一个工作日（周一至周五）。
    """
    prev = d - timedelta(days=1)
    while prev.weekday() >= 5:  # 5=Sat, 6=Sun
        prev -= timedelta(days=1)
    return prev


def get_arxiv_latest_date() -> date:
    """
    返回 arXiv 上最新已发布批次的日期（基于美国东部时间 ET）。

    arXiv 的发布规则：
    - 每个工作日约 20:00 ET 发布新文章
    - 周六、周日不发布
    - 发布前（< 20:00 ET）可用的最新批次是上一个工作日的
    - 发布后（>= 20:00 ET）当天批次已可用

    Returns:
        最新可用批次的日期（ET 日期）。
    """
    now_et = datetime.now(_ET)
    today_et = now_et.date()
    weekday = today_et.weekday()  # 0=Mon ... 4=Fri, 5=Sat, 6=Sun

    if weekday == 5:  # Saturday
        return today_et - timedelta(days=1)  # 上周五
    elif weekday == 6:  # Sunday
        return today_et - timedelta(days=2)  # 上周五
    else:
        # 工作日：判断今天的批次是否已发布
        if now_et.hour >= _ARXIV_ANNOUNCE_HOUR_ET:
            return today_et
        else:
            # 尚未发布，最新批次是上一个工作日
            prev = today_et - timedelta(days=1)
            # 跳过周末（例如周一早晨 → 上周五）
            while prev.weekday() >= 5:
                prev -= timedelta(days=1)
            return prev


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="arXiv Daily Tracker — 每日论文抓取、翻译、报告生成与邮件推送"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="目标日期，格式 YYYY-MM-DD（默认：今日）",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="跳过邮件发送（干运行模式）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="开启 DEBUG 级别日志",
    )
    return parser.parse_args()


def setup_logging(verbose: bool) -> None:
    """配置日志格式和级别。"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_config(config_path: Path) -> dict:
    """
    读取 config.yaml 配置文件。

    Args:
        config_path: 配置文件路径。

    Returns:
        配置字典。
    """
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    """主流程：抓取 → 翻译 → 生成报告 → 发送邮件。"""
    args = parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # 加载 .env 密钥（不存在时静默跳过，依赖系统环境变量）
    load_dotenv()

    # 加载配置
    config_path = Path(__file__).parent / "config.yaml"
    config = load_config(config_path)

    # 确定目标日期
    if args.date:
        target_date = date.fromisoformat(args.date)
    else:
        # 按 arXiv 美国东部时间（ET）和发布时间表，自动推算最新可用批次日期
        target_date = get_arxiv_latest_date()
        logger.debug(f"arXiv ET-aware 目标日期：{target_date}")

    logger.info(f"目标日期：{target_date}")

    # 读取配置项
    category = config["arxiv"]["categories"][0]
    output_dir = Path(config["output"]["directory"])
    llm_cfg = config["llm"]
    email_cfg = config["email"]

    # ── Step 1：抓取论文 ──────────────────────────────────────────────────
    logger.info("Step 1/4：从 arXiv 抓取论文...")

    # 计算最新业务日期，用于引擎路由（RSS vs Search API）
    latest_date = get_arxiv_latest_date()

    MAX_FALLBACK_DAYS = 7
    papers: list = []

    if args.date:
        # 用户明确指定了日期 → 传入真实 latest_date，让路由器自动判断引擎：
        #   - target_date == latest_date → RSS 引擎（当前批次，数据完整且准确）
        #   - target_date <  latest_date → Search API 引擎（历史日期回溯）
        papers = fetch_papers(target_date, category, latest_date=latest_date)

        # RSS 在周末可能已过期（无新公告），此时对最新批次日期回退到 Search API，
        # 但需要查询的是"投稿日期"（= 公告日期的前一个工作日），而非公告日期本身。
        # 原因：arXiv submittedDate 是论文上传时间，公告日 D 的论文投稿于 D 的前一工作日。
        if not papers and target_date == latest_date:
            submit_date = _prev_business_day(target_date)
            logger.info(
                f"RSS 批次为空（可能是周末），改用 Search API 查询投稿日 {submit_date}"
                f"（公告日 {target_date}）"
            )
            papers = fetch_papers(submit_date, category, latest_date=None)
    else:
        # 自动模式 → 优先 RSS 引擎；若当日无结果（周末/节假日）则回退到历史日期
        # 回退时 target_date < latest_date，自动切换到 Search API 引擎
        for days_back in range(MAX_FALLBACK_DAYS + 1):
            query_date = target_date - timedelta(days=days_back)
            if days_back > 0:
                logger.info(
                    f"{query_date + timedelta(days=1)} 无论文（可能是周末或节假日），"
                    f"自动回退查询 {query_date}..."
                )
            papers = fetch_papers(query_date, category, latest_date=latest_date)
            if papers:
                if days_back > 0:
                    logger.info(f"自动回退成功，使用 {query_date} 的论文（回退了 {days_back} 天）")
                    target_date = query_date
                break

    if not papers:
        logger.warning(
            f"未找到 {category} 在 {target_date} 的论文"
            + ("" if args.date else f"（已回退 {MAX_FALLBACK_DAYS} 天仍无结果）")
            + "，流程结束。"
        )
        sys.exit(0)

    logger.info(f"共抓取 {len(papers)} 篇论文")

    # ── Step 2：翻译 ──────────────────────────────────────────────────────
    logger.info("Step 2/4：翻译标题和摘要...")
    client, model, max_retries = build_client(llm_cfg["model"], llm_cfg["max_retries"])

    for i, paper in enumerate(papers, start=1):
        logger.debug(f"翻译第 {i}/{len(papers)} 篇：{paper.arxiv_id}")
        try:
            translate_paper(paper, client, model, max_retries)
        except Exception as e:
            # 单篇失败不中断流程，translate_paper 内部已做回退，此处仅记录
            logger.warning(f"论文 {paper.arxiv_id} 翻译异常（已回退到英文）：{e}")
        if i < len(papers):
            time.sleep(2)  # 每篇之间强制间隔 2s，避免密集请求触发智谱并发限制

    # ── Step 3：生成报告 ──────────────────────────────────────────────────
    logger.info("Step 3/4：生成 Markdown 报告...")
    md_path = markdown_writer.write(papers, target_date, output_dir, category)

    # PDF 生成失败时降级为发送 Markdown
    attachment_path = md_path
    pdf_path = None
    if ENABLE_PDF and "pdf" in config["output"]["formats"]:
        logger.info("Step 3/4（续）：生成 PDF...")
        try:
            pdf_path = pdf_exporter.export(md_path)
        except Exception as e:
            logger.warning(f"PDF 生成异常，跳过（{e}）")
        if pdf_path:
            attachment_path = pdf_path
        else:
            logger.warning("PDF 生成失败，将改为发送 Markdown 文件")
    else:
        logger.info("Step 3/4（续）：PDF 已禁用，仅生成 Markdown")

    # ── Step 4：通知 ──────────────────────────────────────────────────────
    # NOTIFY_MODE 控制通知方式：
    #   obsidian（默认）— 跳过邮件，Git 同步由工作流负责
    #   email           — 发送邮件（PDF + Markdown 双附件）
    #   both            — 同上；工作流同时执行 Git 同步
    notify_mode = os.environ.get("NOTIFY_MODE", "obsidian").strip().lower()

    if args.no_email:
        logger.info("Step 4/4：--no-email 模式，跳过邮件发送")
        logger.info(f"报告已保存至：{attachment_path}")
    elif not email_cfg.get("enabled", True):
        logger.info("Step 4/4：config.yaml 中 email.enabled=false，跳过邮件发送")
    elif notify_mode in ("email", "both"):
        logger.info(f"Step 4/4：NOTIFY_MODE={notify_mode}，发送邮件...")
        # 构建附件列表：PDF（若已生成）+ Markdown
        attachment_paths: list[Path] = []
        if pdf_path:
            attachment_paths.append(pdf_path)
        attachment_paths.append(md_path)
        send(
            attachment_paths=attachment_paths,
            target_date=target_date,
            smtp_host=email_cfg["smtp_host"],
            smtp_port=email_cfg["smtp_port"],
            smtp_security=email_cfg.get("smtp_security", "ssl"),
            recipients=_get_recipients(email_cfg),
        )
    else:
        # notify_mode == "obsidian"（默认）
        logger.info("Step 4/4：NOTIFY_MODE=obsidian，跳过邮件发送（Git 同步在工作流中进行）")
        logger.info(f"报告已保存至：{attachment_path}")

    logger.info("全部流程完成。")


if __name__ == "__main__":
    main()
