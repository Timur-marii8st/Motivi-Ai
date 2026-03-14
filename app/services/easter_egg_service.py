"""Easter Egg Responses — occasional surprise elements.

1-in-50 chance per interaction of injecting a surprise into the LLM prompt.
"""
from __future__ import annotations

import random

from app.config import settings

EASTER_EGG_TYPES = [
    (
        "Include a relevant, inspiring quote naturally woven into your response. "
        "Don't announce it as a quote — just integrate it smoothly."
    ),
    (
        "Include a fun, surprising fact related to something the user is interested in "
        "or working on. Frame it naturally: 'Fun fact: ...'"
    ),
    (
        "End your response with a playful, unexpected micro-challenge "
        "related to the conversation. Make it fun and achievable."
    ),
]

EASTER_EGG_PROBABILITY = 1 / 50


def should_trigger_easter_egg() -> bool:
    """Return True with a 1-in-50 probability (if feature enabled)."""
    if not settings.is_feature_enabled("F027_EASTER_EGGS"):
        return False
    return random.random() < EASTER_EGG_PROBABILITY


def get_easter_egg_prompt() -> str:
    """Return a prompt modifier for the LLM to include a surprise element."""
    return random.choice(EASTER_EGG_TYPES)
