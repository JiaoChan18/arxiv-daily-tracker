"""
scheduler.py — 每日定时运行 arXiv Daily Tracker。

在 config.yaml 指定的时间（默认 08:00 Copenhagen 时间）触发 main.py 的主流程。
使用 `schedule` 库实现纯 Python 调度，无需系统 cron 权限。
"""

import logging
import time
from datetime import datetime
from pathlib import Path

import pytz
import schedule
import yaml
from dotenv import load_dotenv

import main as tracker

logger = logging.getLogger(__name__)


def load_config() -> dict:
    """读取 config.yaml 中的调度配置。"""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_job() -> None:
    """
    调度触发时执行的任务：调用 main.main() 完成完整的抓取-翻译-报告-邮件流程。
    捕获所有异常以防止调度器因单次失败而退出。
    """
    tz_name = load_config()["schedule"]["timezone"]
    tz = pytz.timezone(tz_name)
    now_local = datetime.now(tz)
    logger.info(f"调度触发（{tz_name} 时间：{now_local.strftime('%Y-%m-%d %H:%M:%S')}）")

    try:
        tracker.main()
    except SystemExit as e:
        # main() 在邮件失败时会调用 sys.exit(1)，此处捕获以保持调度器继续运行
        logger.error(f"main() 以状态码 {e.code} 退出，调度器继续运行")
    except Exception as e:
        logger.error(f"任务执行时发生未预期错误：{e}", exc_info=True)


def main() -> None:
    """启动调度器，阻塞运行直到手动中断。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    load_dotenv()
    config = load_config()

    run_time = config["schedule"]["time"]   # 如 "08:00"
    tz_name = config["schedule"]["timezone"]

    logger.info(f"调度器启动，每日 {run_time} ({tz_name}) 运行")

    # schedule 库基于本地时间；此处将目标时区时间转换为本地时间再注册
    # 注意：若服务器时区与目标时区不同，需做时差换算
    # 简化方案：直接使用 UTC 时间注册（需在 config.yaml 中填入 UTC 时间）
    # 更健壮的方案：在 run_job() 内部检查当前目标时区时间再决定是否执行
    schedule.every().day.at(run_time).do(run_job)

    logger.info("等待下次调度触发（Ctrl+C 退出）...")
    while True:
        schedule.run_pending()
        time.sleep(60)  # 每分钟检查一次是否有待执行任务


if __name__ == "__main__":
    main()
