"""
email_sender.py — 通过 SMTP 发送每日论文报告（PDF 或 Markdown 附件）。

支持多种邮件服务商（Gmail、Outlook、Yahoo 及自定义 SMTP 服务器）。
通过环境变量 SMTP_USERNAME / SMTP_PASSWORD 认证，
兼容旧版 GMAIL_ADDRESS / GMAIL_APP_PASSWORD（已弃用，会输出警告）。
连接方式支持 SSL（端口 465）、STARTTLS（端口 587）及无加密三种模式，
由 config.yaml 中的 smtp_security 字段控制。

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


def _get_credentials() -> tuple[str, str]:
    """
    从环境变量获取 SMTP 凭据。
    优先使用 SMTP_USERNAME / SMTP_PASSWORD，
    若未设置则回退到已弃用的 GMAIL_ADDRESS / GMAIL_APP_PASSWORD。

    Returns:
        (username, password) 元组。

    Raises:
        KeyError: 两组环境变量均未设置时抛出。
    """
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")

    if username and password:
        return username, password

    # 回退到已弃用的 Gmail 变量
    legacy_user = os.environ.get("GMAIL_ADDRESS")
    legacy_pass = os.environ.get("GMAIL_APP_PASSWORD")

    if legacy_user and legacy_pass:
        logger.warning(
            "GMAIL_ADDRESS / GMAIL_APP_PASSWORD 已弃用，请改用 SMTP_USERNAME / SMTP_PASSWORD。"
        )
        return legacy_user, legacy_pass

    raise KeyError(
        "未找到 SMTP 凭据。请设置环境变量 SMTP_USERNAME 和 SMTP_PASSWORD"
        "（或已弃用的 GMAIL_ADDRESS 和 GMAIL_APP_PASSWORD）。"
    )


def _connect(
    smtp_host: str, smtp_port: int, smtp_security: str
) -> smtplib.SMTP | smtplib.SMTP_SSL:
    """
    根据安全模式建立 SMTP 连接。

    Args:
        smtp_host:     SMTP 服务器地址。
        smtp_port:     SMTP 端口。
        smtp_security: 安全模式，可选 "ssl"、"starttls"、"none"。

    Returns:
        已连接的 SMTP 或 SMTP_SSL 对象。
    """
    if smtp_security == "ssl":
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=SMTP_TIMEOUT)
    elif smtp_security == "starttls":
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=SMTP_TIMEOUT)
        server.starttls()
    elif smtp_security == "none":
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=SMTP_TIMEOUT)
    else:
        raise ValueError(
            f"不支持的 smtp_security 值：'{smtp_security}'，"
            "请使用 'ssl'、'starttls' 或 'none'。"
        )
    return server


def send(
    attachment_paths: list[Path],
    target_date: date,
    smtp_host: str,
    smtp_port: int,
    smtp_security: str,
    recipients: list[str],
) -> None:
    """
    发送每日报告邮件，支持同时附加多个文件（如 PDF + Markdown）。
    发送失败时记录错误并调用 sys.exit(1)，使调度器能感知失败。

    Args:
        attachment_paths: 附件文件路径列表（PDF 在前，Markdown 备选或附加）。
        target_date:      报告日期，用于邮件主题。
        smtp_host:        SMTP 服务器地址。
        smtp_port:        SMTP 端口（465 = SSL，587 = STARTTLS）。
        smtp_security:    安全模式："ssl"、"starttls" 或 "none"。
        recipients:       收件人邮箱列表。
    """
    username, password = _get_credentials()

    subject = f"arXiv quant-ph 每日速递 — {target_date.isoformat()}"
    body = (
        f"您好，\n\n"
        f"附件为 {target_date.isoformat()} 的 arXiv quant-ph 论文日报。\n\n"
        f"共收录 {_count_papers(attachment_paths[0])} 篇论文，标题及摘要已翻译为中文。\n\n"
        f"— arXiv Daily Tracker"
    )

    msg = MIMEMultipart()
    msg["From"] = username
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # 依次添加所有附件
    for path in attachment_paths:
        _attach_file(msg, path)

    logger.info(f"正在发送邮件至 {recipients}，附件：{[p.name for p in attachment_paths]}")

    try:
        with _connect(smtp_host, smtp_port, smtp_security) as server:
            server.login(username, password)
            server.sendmail(username, recipients, msg.as_string())

        logger.info("邮件发送成功")

    except smtplib.SMTPAuthenticationError:
        logger.error(
            f"SMTP 认证失败（{smtp_host}）。"
            "请检查 SMTP_USERNAME 和 SMTP_PASSWORD 是否正确，"
            "并确认已为所用邮箱开启 SMTP 访问权限（如 Gmail 需使用 App Password）。"
        )
        sys.exit(1)
    except smtplib.SMTPException as e:
        logger.error(f"SMTP 发送失败：{e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"邮件发送时发生意外错误：{e}")
        sys.exit(1)


def _attach_file(msg: MIMEMultipart, file_path: Path) -> None:
    """
    将文件作为附件添加到邮件消息中。文件不存在时记录警告并跳过，不抛出异常。

    Args:
        msg:       MIMEMultipart 邮件对象。
        file_path: 要附加的文件路径。
    """
    if not file_path.exists():
        logger.warning(f"附件文件不存在，跳过：{file_path}")
        return

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
