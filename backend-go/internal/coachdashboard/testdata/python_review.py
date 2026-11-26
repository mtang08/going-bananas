"""Create private, synthetic dashboard receipts with the pre-cutover writer."""
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend"))
from app.services.coach_chat_store import ChatMessage, ChatReview, ChatStore
from app.services.decision_inputs import digest

def uid(n):
    return UUID(int=n)

store = ChatStore(Path(sys.argv[1]), sys.argv[2])
with store.transaction() as state:
    for n in (1, 2):
        client = uid(n+10)
        message = ChatMessage(id=uid(n+20), role="user", text=f"Synthetic message {n}", client_message_id=client)
        review = ChatReview(id=uid(n), status="idle", messages=[message], codex_thread_id=f"resume-{n}")
        state.receipts[client] = digest({"text":message.text,"intent":None})
        if n == 1:
            store.archive(review)
        else:
            review.status = "running"
            review.active_turn = message.id
            state.review = review
