"""
Email processing pipeline: parse → translate → reconstruct → forward.
"""

import logging
from email import message_from_bytes
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings
from app.services import translator
from app.services.email_sender import send_email

logger = logging.getLogger(__name__)

# Headers that become invalid after forwarding (DKIM, ARC, etc.)
_HEADERS_TO_STRIP = {
    "dkim-signature",
    "domainkey-signature",
    "arc-seal",
    "arc-message-signature",
    "arc-authentication-results",
    "authentication-results",
    "received",
    "received-spf",
    "x-google-dkim-signature",
    "x-forwarded-to",
    "delivered-to",
    "return-path",
}


def _get_charset(part: Message) -> str:
    charset = part.get_content_charset()
    return charset if charset else "utf-8"


def _decode_payload(part: Message) -> str:
    raw = part.get_payload(decode=True)
    if raw is None:
        return ""
    return raw.decode(_get_charset(part), errors="replace")


def _extract_parts(msg: Message) -> tuple[str | None, str | None]:
    """Return (plain_text, html_text) from a (possibly multipart) email."""
    if msg.is_multipart():
        plain: str | None = None
        html: str | None = None
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain" and plain is None:
                plain = _decode_payload(part)
            elif ctype == "text/html" and html is None:
                html = _decode_payload(part)
        return plain, html
    else:
        ctype = msg.get_content_type()
        content = _decode_payload(msg)
        if ctype == "text/html":
            return None, content
        return content, None


def _copy_safe_headers(original: Message, new_msg: MIMEMultipart, dest_email: str) -> None:
    """Copy whitelisted headers from original to new_msg."""
    preserve = {"subject", "from", "reply-to", "date", "message-id", "list-unsubscribe"}
    for key, value in original.items():
        if key.lower() in preserve:
            if key.lower() == "subject":
                continue  # subject is set separately (translated)
            new_msg[key] = value

    # Set routing headers
    new_msg["To"] = dest_email
    original_to = original.get("To", original.get("Delivered-To", ""))
    if original_to:
        new_msg["X-Original-To"] = original_to


def process_email(
    raw_content: bytes,
    dest_email: str,
    source_lang: str = "en",
    target_lang: str = "zh",
) -> dict:
    """
    Full pipeline: parse raw email bytes → translate → reconstruct → send.

    Returns a dict with usage stats and status for logging.
    """
    msg = message_from_bytes(raw_content)
    original_subject = msg.get("Subject", "(no subject)")
    from_addr = msg.get("From", "unknown")

    logger.info("Processing email from=%s subject=%r", from_addr, original_subject)

    total_input = 0
    total_output = 0
    total_cache_read = 0

    # --- Translate subject ---
    translated_subject, s_usage = translator.translate_subject(
        original_subject, source_lang, target_lang
    )
    total_input += s_usage.input_tokens
    total_output += s_usage.output_tokens
    total_cache_read += s_usage.cache_read_tokens

    # --- Extract body parts ---
    plain_text, html_text = _extract_parts(msg)

    translated_plain: str | None = None
    translated_html: str | None = None

    if html_text:
        translated_html, h_usage = translator.translate_html(html_text, source_lang, target_lang)
        total_input += h_usage.input_tokens
        total_output += h_usage.output_tokens
        total_cache_read += h_usage.cache_read_tokens

    if plain_text:
        translated_plain, p_usage = translator.translate_plain_text(plain_text, source_lang, target_lang)
        total_input += p_usage.input_tokens
        total_output += p_usage.output_tokens
        total_cache_read += p_usage.cache_read_tokens

    # --- Reconstruct email ---
    if translated_html and translated_plain:
        new_msg: Message = MIMEMultipart("alternative")
        new_msg.attach(MIMEText(translated_plain, "plain", "utf-8"))
        new_msg.attach(MIMEText(translated_html, "html", "utf-8"))
    elif translated_html:
        new_msg = MIMEMultipart("alternative")
        new_msg.attach(MIMEText(translated_html, "html", "utf-8"))
    elif translated_plain:
        new_msg = MIMEText(translated_plain, "plain", "utf-8")
    else:
        # Nothing translatable — forward as-is
        new_msg = MIMEText("(No translatable content found)", "plain", "utf-8")

    # --- Set headers ---
    new_msg["Subject"] = translated_subject
    _copy_safe_headers(msg, new_msg if isinstance(new_msg, MIMEMultipart) else new_msg, dest_email)
    new_msg["X-Translated-From"] = source_lang
    new_msg["X-Translated-To"] = target_lang
    new_msg["X-Translated-By"] = f"newsletter-translator ({settings.translation_model})"

    if not new_msg.get("From"):
        new_msg["From"] = settings.smtp_send_from or from_addr

    # --- Send ---
    send_email(new_msg, dest_email)

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
