"""
Email processing pipeline: translate subject + body → forward via Mailgun.
"""

import logging

from app.services import translator
from app.services.email_sender import send_email

logger = logging.getLogger(__name__)


def process_email(
    subject: str,
    from_addr: str,
    body_plain: str | None,
    body_html: str | None,
    dest_email: str,
    source_lang: str = "en",
    target_lang: str = "zh",
) -> dict:
    """
    Translate subject and body, then send to dest_email via Mailgun.

    Returns a dict with usage stats and status for logging.
    """
    logger.info("Processing email from=%s subject=%r", from_addr, subject)

    total_input = 0
    total_output = 0
    total_cache_read = 0

    translated_subject, s_usage = translator.translate_subject(subject, source_lang, target_lang)
    total_input += s_usage.input_tokens
    total_output += s_usage.output_tokens
    total_cache_read += s_usage.cache_read_tokens

    translated_html: str | None = None
    translated_plain: str | None = None

    if body_html:
        translated_html, h_usage = translator.translate_html(body_html, source_lang, target_lang)
        total_input += h_usage.input_tokens
        total_output += h_usage.output_tokens
        total_cache_read += h_usage.cache_read_tokens

    if body_plain:
        translated_plain, p_usage = translator.translate_plain_text(body_plain, source_lang, target_lang)
        total_input += p_usage.input_tokens
        total_output += p_usage.output_tokens
        total_cache_read += p_usage.cache_read_tokens

    send_email(
        subject=translated_subject,
        to_addr=dest_email,
        body_plain=translated_plain,
        body_html=translated_html,
    )

    logger.info(
        "Translation complete: input=%d output=%d cache_read=%d",
        total_input, total_output, total_cache_read,
    )

    return {
        "status": "forwarded",
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cache_read_tokens": total_cache_read,
    }
