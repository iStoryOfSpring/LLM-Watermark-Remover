import pytest
from pydantic import ValidationError

from backend.app.api.routes import TextRewriteRequest


def test_pasted_text_request_is_limited_to_2000_characters() -> None:
    with pytest.raises(ValidationError):
        TextRewriteRequest(text="字" * 2001)

    request = TextRewriteRequest(text="字" * 2000)
    assert len(request.text) == 2000
