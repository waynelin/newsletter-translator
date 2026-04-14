"""
Translation service using the Anthropic API with prompt caching.

The system prompt (translation instructions) is stable across all calls for the
same language pair, so it is marked with cache_control to enable prompt caching.
The per-email content is supplied as the user message (not cached).
"""

import re
from dataclasses import dataclass

import anthropic
from bs4 import BeautifulSoup, NavigableString

from app.config import settings

# Minimum cacheable prefix for claude-haiku is 2048 tokens.
# This system prompt is intentionally detailed to exceed that threshold.
_SYSTEM_PROMPT_TEMPLATE = """\
You are a professional translator specializing in email newsletters, marketing copy, \
and editorial content. Your task is to translate content from {source_lang_name} to \
{target_lang_name}.

## Core Translation Principles

1. **Accuracy**: Render the full meaning of the source text faithfully. Do not omit, \
add, or paraphrase content beyond what is necessary for natural expression in the \
target language.

2. **Tone preservation**: Match the register of the original — if the source is formal \
and professional, the translation must be formal and professional. If it is casual or \
conversational, reflect that in the target language.

3. **Fluency**: The translation should read naturally to a native speaker of the target \
language. Restructure sentences as needed to achieve natural flow, but do not change the \
meaning.

4. **Newsletter-specific guidance**:
   - Preserve all calls-to-action (CTAs) such as "Read more", "Subscribe", "Get started" \
— translate them naturally into common equivalents used in the target language.
   - Preserve product names, brand names, company names, and personal names exactly as \
written in the source.
   - Preserve all URLs, email addresses, phone numbers, and other identifiers unchanged.
   - Translate section headings and subheadings with the same energy and style as the body.
   - For numbered or bulleted lists, translate each item maintaining the list structure.

5. **HTML content** (when translating HTML segments):
   - You will receive plain text segments extracted from an HTML email. Translate only \
the text content. Do not output HTML tags.
   - Each segment is enclosed in numbered markers like [1]text here[/1]. Preserve these \
markers exactly in your output. Do not reorder, merge, or split segments.
   - Whitespace-only segments should be returned unchanged.

6. **Subject lines**: When given a subject line prefixed with "Subject: ", translate it \
concisely and with impact, matching the style conventions of the target language for \
email subject lines.

7. **Cultural adaptation**: Where idioms, cultural references, or expressions do not \
translate directly, use an equivalent in the target culture that conveys the same \
meaning and emotional resonance.

8. **Output format**: Return ONLY the translated content. Do not include explanations, \
notes, disclaimers, or commentary about the translation.

## Language Pair

Source language: {source_lang_name} ({source_lang_code})
Target language: {target_lang_name} ({target_lang_code})
"""

_LANG_NAMES = {
    "en": "English",
    "zh": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "it": "Italian",
}


@dataclass
class UsageStats:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


def _build_system_prompt(source_lang: str, target_lang: str) -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(
        source_lang_name=_LANG_NAMES.get(source_lang, source_lang),
        source_lang_code=source_lang,
        target_lang_name=_LANG_NAMES.get(target_lang, target_lang),
        target_lang_code=target_lang,
    )


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def translate_plain_text(
    text: str,
    source_lang: str = "en",
    target_lang: str = "zh",
) -> tuple[str, UsageStats]:
    """Translate plain text content. Returns (translated_text, usage_stats)."""
    if not text.strip():
        return text, UsageStats(0, 0, 0, 0)

    client = _get_client()
    system_prompt = _build_system_prompt(source_lang, target_lang)

    response = client.messages.create(
        model=settings.translation_model,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Translate the following email content:\n\n{text}",
            }
        ],
    )

    translated = response.content[0].text
    usage = response.usage
    stats = UsageStats(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )
    return translated, stats


def translate_subject(
    subject: str,
    source_lang: str = "en",
    target_lang: str = "zh",
) -> tuple[str, UsageStats]:
    """Translate an email subject line."""
    if not subject.strip():
        return subject, UsageStats(0, 0, 0, 0)

    client = _get_client()
    system_prompt = _build_system_prompt(source_lang, target_lang)

    response = client.messages.create(
        model=settings.translation_model,
        max_tokens=256,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Subject: {subject}",
            }
        ],
    )

    translated = response.content[0].text.strip()
    # Strip "Subject: " prefix if Claude echoed it back
    if translated.lower().startswith("subject:"):
        translated = translated[len("subject:"):].strip()

    usage = response.usage
    stats = UsageStats(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )
    return translated, stats


def translate_html(
    html: str,
    source_lang: str = "en",
    target_lang: str = "zh",
) -> tuple[str, UsageStats]:
    """
    Translate an HTML email body.

    Strategy:
    1. Parse with BeautifulSoup and collect all non-empty text nodes.
    2. Build a single translation request using numbered markers [N]...[/N].
    3. Map translated segments back to the original DOM nodes.
    4. Re-serialize the modified HTML.

    This preserves all HTML structure, attributes, links, images, and CSS.
    """
    if not html.strip():
        return html, UsageStats(0, 0, 0, 0)

    soup = BeautifulSoup(html, "lxml")

    # Remove <style> and <script> tags — not translatable
    for tag in soup.find_all(["style", "script"]):
        tag.decompose()

    # Collect translatable text nodes (NavigableString with non-whitespace content)
    text_nodes: list[NavigableString] = []
    for node in soup.find_all(string=True):
        if isinstance(node, NavigableString) and node.strip():
            text_nodes.append(node)

    if not text_nodes:
        return html, UsageStats(0, 0, 0, 0)

    # Build marked-up translation request
    marked_segments = "\n".join(
        f"[{i + 1}]{node}[/{i + 1}]" for i, node in enumerate(text_nodes)
    )

    client = _get_client()
    system_prompt = _build_system_prompt(source_lang, target_lang)

    response = client.messages.create(
        model=settings.translation_model,
        max_tokens=8192,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    "Translate the following HTML email segments. "
                    "Each segment is wrapped in numbered markers [N]...[/N]. "
                    "Preserve the markers exactly. Return all segments in order.\n\n"
                    + marked_segments
                ),
            }
        ],
    )

    translated_text = response.content[0].text
    usage = response.usage
    stats = UsageStats(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )

    # Parse translated segments back out using the markers
    translated_map: dict[int, str] = {}
    for match in re.finditer(r"\[(\d+)\](.*?)\[/\1\]", translated_text, re.DOTALL):
        idx = int(match.group(1))
        translated_map[idx] = match.group(2)

    # Replace text nodes in the DOM
    for i, node in enumerate(text_nodes):
        replacement = translated_map.get(i + 1)
        if replacement is not None:
            node.replace_with(NavigableString(replacement))

    return str(soup), stats
