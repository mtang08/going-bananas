"""Backend coach prompts match the UI contract strings."""

from app.services.exceptions.detector import PROMPTS


def test_prompts_match_contract():
    assert PROMPTS == {
        "exception": "Use $going-bananas-coach for an exception review. Read the open findings in the app and patch only what they require.",
        "block": "Use $going-bananas-coach for a block review. An exception needs a bigger review.",
        "benchmark": "Use $going-bananas-coach for a block review. Review the block benchmark.",
        "race": "Use $going-bananas-coach for a post-race review of {event_name} on {event_date}.",
        "reassess": "Use $going-bananas-coach to reassess the open exception patch.",
    }
