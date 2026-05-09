"""Notification delivery services: Email, DingTalk, WeChat Work."""

import json
import logging
import smtplib
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app

logger = logging.getLogger(__name__)


def send_email(recipients: list[str], subject: str, body: str) -> None:
    """Send email notification via SMTP.

    Args:
        recipients: List of email addresses.
        subject: Email subject line.
        body: Email body (Markdown rendered as plain text).
    """
    host = current_app.config.get("SMTP_HOST", "localhost")
    port = current_app.config.get("SMTP_PORT", 587)
    user = current_app.config.get("SMTP_USER", "")
    password = current_app.config.get("SMTP_PASSWORD", "")
    from_addr = current_app.config.get("SMTP_FROM", user or "noreply@qa-platform.local")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)

    # Plain text version
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            if port == 587:
                server.starttls()
                server.ehlo()
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, recipients, msg.as_string())
        logger.info("Email sent to %s: %s", recipients, subject)
    except Exception:
        logger.exception("Failed to send email to %s", recipients)
        raise


def send_dingtalk(webhook_url: str, title: str, content: str) -> None:
    """Send DingTalk robot webhook notification.

    Args:
        webhook_url: DingTalk robot webhook URL.
        title: Message title.
        content: Markdown content body.
    """
    payload = json.dumps({
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": content,
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("errcode", 0) != 0:
                logger.error("DingTalk API error: %s", result)
                raise RuntimeError(f"DingTalk error: {result}")
        logger.info("DingTalk notification sent: %s", title)
    except Exception:
        logger.exception("Failed to send DingTalk notification")
        raise


def send_wechat(webhook_url: str, content: str) -> None:
    """Send WeChat Work robot webhook notification.

    Args:
        webhook_url: WeChat Work robot webhook URL.
        content: Markdown content body.
    """
    payload = json.dumps({
        "msgtype": "markdown",
        "markdown": {
            "content": content,
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("errcode", 0) != 0:
                logger.error("WeChat Work API error: %s", result)
                raise RuntimeError(f"WeChat Work error: {result}")
        logger.info("WeChat Work notification sent")
    except Exception:
        logger.exception("Failed to send WeChat Work notification")
        raise
