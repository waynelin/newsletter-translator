"""
Outbound email sender using smtplib with STARTTLS.
"""

import logging
import smtplib
from email.message import Message

from app.config import settings

logger = logging.getLogger(__name__)


def send_email(msg: Message, to_addr: str) -> None:
    """
    Send an email message to to_addr via the configured outbound SMTP relay.

    Raises smtplib.SMTPException (or subclass) on failure.
    """
    host = settings.smtp_send_host
    port = settings.smtp_send_port
    user = settings.smtp_send_user
    password = settings.smtp_send_password

    logger.info("Sending translated email to %s via %s:%d", to_addr, host, port)

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()

        if user and password:
            smtp.login(user, password)

        smtp.send_message(msg, to_addrs=[to_addr])

    logger.info("Email sent successfully to %s", to_addr)
