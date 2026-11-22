from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from app.config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, text: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    if not settings.smtp_host or settings.environment == "test":
        logger.info("email skipped", extra={"to": to, "subject": subject, "body": text})
        return
    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_tls,
            timeout=10,
        )
    except Exception:
        logger.exception("failed to send email", extra={"to": to, "subject": subject})
