"""Fixed-choice morning observations stored in the existing check-in history."""

from typing import Literal

FIRST_STEPS_KEY = "phone-first-steps:"
WalkingResponse = Literal["gone", "eased", "same", "worse", "too_early"]

# These are the complete set of notes this form can write. Only these choices
# are projected into coach snapshots; other check-in notes remain private.
WALKING_NOTES: dict[WalkingResponse | None, str] = {
    None: "First steps: no ankle pain.",
    "gone": "First-step ankle pain: gone after walking.",
    "eased": "First-step ankle pain: eased after walking.",
    "same": "First-step ankle pain: unchanged after walking.",
    "worse": "First-step ankle pain: worse after walking.",
    "too_early": "First-step ankle pain: too early to assess walking response.",
}


def morning_observation(key: str, note: str | None, symptoms: list[dict]) -> dict:
    if not key.startswith(FIRST_STEPS_KEY):
        return {}
    if note == WALKING_NOTES[None] and not symptoms:
        return {"morning_ankle": {"pain": 0, "walking_response": None}}
    for response, label in WALKING_NOTES.items():
        if response is not None and note == label and len(symptoms) == 1:
            return {"morning_ankle": {"pain": symptoms[0]["severity"], "walking_response": response}}
    return {}
