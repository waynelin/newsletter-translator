"""
Outbound email sender using the Mailgun API.
"""

import logging

import requests

from app.config import settings

logger = logging.getLogger(__name__)


def send_email(
    subject: str,
    to_addr: str,
    body_plain: str | None = None,
    body_html: str | None = None,
) -> None:
    """Send a translated email via Mailgun. Raises on non-2xx response."""
    data: dict[str, str] = {
        "from": f"Newsletter Translator <{settings.from_addr}>",
        "to": to_addr,
        "subject": subject,
    }
    if body_plain:
        data["text"] = body_plain
    if body_html:
        data["html"] = body_html

    logger.info("Sending translated email to %s via Mailgun", to_addr)

    resp = requests.post(
        f"https://api.mailgun.net/v3/{settings.mailgun_domain}/messages",
        auth=("api", settings.mailgun_api_key),
        data=data,
        timeout=30,
    )
    resp.raise_for_status()
    logger.info("Email sent successfully to %s", to_addr)
