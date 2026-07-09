"""SMTP email delivery (stdlib, run in thread pool)."""

import asyncio
import smtplib
from email.message import EmailMessage

from memory_engine.config import get_settings
from memory_engine.core.user_api_errors import UserApiError


def _send_smtp_sync(
    *,
    to_addr: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
) -> None:
    settings = get_settings()
    host = settings.smtp_host.strip()
    if not host:
        raise UserApiError(
            "GENERAL_ERROR",
            "邮件服务未配置（请设置 SMTP_HOST 等环境变量）",
        )
    from_addr = settings.smtp_from.strip() or settings.smtp_user.strip()
    if not from_addr:
        raise UserApiError("GENERAL_ERROR", "邮件发件人未配置（SMTP_FROM）")

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    port = settings.smtp_port
    use_tls = settings.smtp_use_tls
    user = settings.smtp_user.strip()
    password = settings.smtp_password

    if use_tls and port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
        return

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if use_tls:
            smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)


async def send_email(
    *,
    to_addr: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
) -> None:
    """Send an email via configured SMTP."""
    await asyncio.to_thread(
        _send_smtp_sync,
        to_addr=to_addr,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )
