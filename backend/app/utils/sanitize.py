"""Input sanitisation against XSS (CR-002-I 10.5)."""
import bleach


def sanitize_text(value: str | None) -> str | None:
    """Strip all HTML tags/attributes from free-text input.

    Construction data has no legitimate need for HTML, so we strip everything
    rather than allow-list — the safest default. Returns plain text.
    """
    if value is None:
        return None
    # strip=True removes disallowed tags entirely (no escaped remnants).
    cleaned = bleach.clean(value, tags=[], attributes={}, strip=True)
    return cleaned.strip()
