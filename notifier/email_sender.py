"""
email_sender.py — 通过 Gmail SMTP 发送每日论文报告（PDF 或 Markdown 附件）。

使用 Gmail App Password（非账号密码）认证，通过 SSL 加密连接（端口 465）。
若 PDF 不可用，自动降级为发送 Markdown 文件。
发送失败时记录错误并以非零状态码退出，便于 cron 或调度器检测。
"""

import logging
import os
import smtplib
import sys
from datetime import date
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)

SMTP_TIMEOUT = 30  # 秒


def send(
    attachment_path: Path,
    target_date: date,
    smtp_host: str,
    smtp_port: int,
    recipients: list[str],
) -> None:
    """
    发送每日报告邮件，附件为 PDF 或 Markdown 文件。
    发送失败时记录错误并调用 sys.exit(1)，使调度器能感知失败。

    Args:
        attachment_path: 附件文件路径（PDF 优先，Markdown 备选）。
        target_date:     报告日期，用于邮件主题。
        smtp_host:       SMTP 服务器地址。
        smtp_port:       SMTP 端口（465 = SSL）。
        recipients:      收件人邮箱列表。
    """
    gmail_address = os.environ["GMAIL_ADDRESS"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]

    subject = f"arXiv quant-ph 每日速递 — {target_date.isoformat()}"
    body = (
        f"您好，\n\n"
        f"附件为 {target_date.isoformat()} 的 arXiv quant-ph 论文日报。\n\n"
        f"共收录 {_count_papers(attachment_path)} 篇论文，标题及摘要已翻译为中文。\n\n"
        f"— arXiv Daily Tracker"
    )

    msg = MIMEMultipart()
    msg["From"] = gmail_address
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # 添加附件
    _attach_file(msg, attachment_path)

    logger.info(f"正在发送邮件至 {recipients}，附件：{attachment_path.name}")

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=SMTP_TIMEOUT) as server:
            server.login(gmail_address, app_password)
            server.sendmail(gmail_address, recipients, msg.as_string())

        logger.info("邮件发送成功")

    except smtplib.SMTPAuthenticationError:
        logger.error("Gmail 认证失败。请检查 GMAIL_ADDRESS 和 GMAIL_APP_PASSWORD 是否正确。")
        sys.exit(1)
    except smtplib.SMTPException as e:
        logger.error(f"SMTP 发送失败：{e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"邮件发送时发生意外错误：{e}")
        sys.exit(1)


def _attach_file(msg: MIMEMultipart, file_path: Path) -> None:
    """
    将文件作为附件添加到邮件消息中。

    Args:
        msg:       MIMEMultipart 邮件对象。
        file_path: 要附加的文件路径。
    """
    with open(file_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())

    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f'attachment; filename="{file_path.name}"',
    )
    msg.attach(part)


def _count_papers(attachment_path: Path) -> str:
    """
    从附件路径提取信息（仅用于邮件正文，无法精确计数时返回占位符）。

    Args:
        attachment_path: 附件文件路径。

    Returns:
        论文数量字符串或占位符。
    """
    # 精确数量由调用方在 main.py 中注入；此处作为备选
    return "若干"
