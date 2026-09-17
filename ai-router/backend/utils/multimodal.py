"""
Shared helpers for message content that may be a plain string or a list
of multimodal blocks — {"type": "text", "text": ...} /
{"type": "image_url", "image_url": {"url": ...}} — which is the shape
the frontend sends once an image is attached (see aiBackend.ts).

Only Claude and Gemini get real conversion here. Groq and Z.ai are
OpenAI-compatible APIs that already accept this exact block shape
as-is, so their providers don't need to change at all — they just pass
`messages` straight through like they always have.
"""
import base64
import mimetypes
import requests

FETCH_TIMEOUT = 15


def extract_text(content) -> str:
    """Plain string content passes through unchanged. Block-list content
    is flattened to its text parts, with a placeholder for any image —
    used by the classifier (which only reasons over text) and for
    logging, never sent to a provider as-is."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif block.get("type") == "image_url":
                parts.append("[image attached]")
        return "\n".join(p for p in parts if p).strip()
    return ""


def has_image(messages: list[dict]) -> bool:
    """True if any message's content is a block list containing an image."""
    for m in messages:
        content = m.get("content")
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "image_url" for b in content
        ):
            return True
    return False


def _image_url_to_base64(url: str) -> tuple[str, str]:
    """
    Returns (media_type, base64_data) for an image referenced either as:
      - a data: URL (already inline — this is what the frontend sends
        when the Supabase Storage upload failed client-side, so image
        chat still works before the bucket exists), or
      - a remote https URL (Supabase Storage public URL) — fetched and
        re-encoded server-side, since neither Claude's nor Gemini's
        public API can fetch a URL itself; both require base64 bytes.
    """
    if url.startswith("data:"):
        header, b64 = url.split(",", 1)
        media_type = header.split(";")[0].removeprefix("data:") or "image/jpeg"
        return media_type, b64

    resp = requests.get(url, timeout=FETCH_TIMEOUT)
    resp.raise_for_status()
    media_type = resp.headers.get("Content-Type", "").split(";")[0]
    if not media_type or not media_type.startswith("image/"):
        media_type = mimetypes.guess_type(url)[0] or "image/jpeg"
    return media_type, base64.b64encode(resp.content).decode("ascii")


def to_anthropic_blocks(content) -> list[dict]:
    """Our block shape -> Anthropic's. Anthropic images need a base64
    `source` object, not a bare URL."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    blocks = []
    for block in content:
        if block.get("type") == "text":
            blocks.append({"type": "text", "text": block.get("text", "")})
        elif block.get("type") == "image_url":
            url = block.get("image_url", {}).get("url", "")
            if not url:
                continue
            media_type, data = _image_url_to_base64(url)
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": data},
            })
    return blocks or [{"type": "text", "text": ""}]


def to_gemini_parts(content) -> list[dict]:
    """Our block shape -> Gemini's `parts`. Images go in as inline_data
    with base64, same reasoning as Anthropic above."""
    if isinstance(content, str):
        return [{"text": content}]

    parts = []
    for block in content:
        if block.get("type") == "text":
            parts.append({"text": block.get("text", "")})
        elif block.get("type") == "image_url":
            url = block.get("image_url", {}).get("url", "")
            if not url:
                continue
            media_type, data = _image_url_to_base64(url)
            parts.append({"inline_data": {"mime_type": media_type, "data": data}})
    return parts or [{"text": ""}]