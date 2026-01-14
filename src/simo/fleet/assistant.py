from __future__ import annotations

from typing import Optional


ASSISTANT_ALORA = 'alora'
ASSISTANT_KOVAN = 'kovan'


def normalize_assistant(value) -> Optional[str]:
    if not value:
        return None
    try:
        value = str(value).strip().lower()
    except Exception:
        return None
    if value in (ASSISTANT_ALORA, ASSISTANT_KOVAN):
        return value
    return None


def assistant_from_voice(value) -> Optional[str]:
    if not value:
        return None
    try:
        value = str(value).strip().lower()
    except Exception:
        return None
    if value == 'female':
        return ASSISTANT_ALORA
    if value == 'male':
        return ASSISTANT_KOVAN
    return normalize_assistant(value)


def voice_from_assistant(value) -> Optional[str]:
    value = normalize_assistant(value)
    if value == ASSISTANT_ALORA:
        return 'female'
    if value == ASSISTANT_KOVAN:
        return 'male'
    return None


def assistant_from_wake_word_id(value) -> Optional[str]:
    try:
        wid = int(value)
    except Exception:
        return None
    if wid == 1:
        return ASSISTANT_ALORA
    if wid == 2:
        return ASSISTANT_KOVAN
    return None


def wake_word_id_from_assistant(value) -> Optional[int]:
    value = normalize_assistant(value)
    if value == ASSISTANT_ALORA:
        return 1
    if value == ASSISTANT_KOVAN:
        return 2
    return None

