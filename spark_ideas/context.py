"""Form summary + fixed embedding query for spark ideas."""

from __future__ import annotations

from theme_recommendation.constants import ThemeFormInput
from theme_recommendation.context import form_summary_for_prompt

__all__ = ["form_summary_for_prompt", "build_spark_query"]

_QUERY_BASE = (
    "Unique and memorable {event_type} party ideas that add a special, "
    "standout touch — creative statement pieces, personalized details, "
    "or one-of-a-kind moments guests will remember"
)


def build_spark_query(form: ThemeFormInput) -> str:
    """Fixed embedding query; append celebratee only when filled."""
    event_type = form.event_type.strip()
    base = _QUERY_BASE.format(event_type=event_type)
    celebratee = (form.celebratee or "").strip()
    if celebratee:
        return f"{base}, for a {celebratee}."
    return f"{base}."
