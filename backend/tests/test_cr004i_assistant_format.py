"""CR-004-I: AI assistant response-formatting instructions."""
from app.services.ai import ASSISTANT_SYSTEM


def test_assistant_prompt_requests_bullet_and_bold_format():
    assert "madde" in ASSISTANT_SYSTEM            # bullet points
    assert "**" in ASSISTANT_SYSTEM               # bold markdown for numbers
    assert "300" in ASSISTANT_SYSTEM              # word cap
    assert "proje" in ASSISTANT_SYSTEM.lower()    # cite the project/data used
