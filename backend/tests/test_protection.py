from backend.app.core.models import ProtectedSpan, SpanType
from backend.app.protection.engine import ProtectedSpanEngine


def test_user_term_wins_over_builtin_and_regex_overlap() -> None:
    engine = ProtectedSpanEngine()
    spans = engine.merge(
        [
            ProtectedSpan(
                start=0,
                end=8,
                text="DeepSeek",
                type=SpanType.USER_TERM,
                reason="user",
                priority=100,
            ),
            ProtectedSpan(
                start=0,
                end=8,
                text="DeepSeek",
                type=SpanType.NAMED_ENTITY,
                reason="ner",
                priority=70,
            ),
            ProtectedSpan(
                start=2,
                end=5,
                text="epS",
                type=SpanType.BUILTIN_TERM,
                reason="builtin",
                priority=80,
            ),
        ]
    )
    assert len(spans) == 1
    assert spans[0].type == SpanType.USER_TERM

