"""
HTTP entrypoint for deployment (Render, or anywhere else running
ASGI). The CLI in main.py is unaffected and still works for local
testing — this is the second, separate way to run the same router.

Run locally:   uvicorn api:app --reload
Render runs:   uvicorn api:app --host 0.0.0.0 --port $PORT
"""
import os
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from router import AIRouter
from emotion.engine import EmotionEngine
from access.tiers import SubscriptionStore
from branding import scrub_result_for_user
from utils.errors import AllProvidersFailedError

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Single shared instances for the process's lifetime. Fine for one
# instance; if you scale Render to multiple instances, emotion state
# and subscription tier need to move to a real DB/Redis instead of
# living in process memory, or a user's mood/tier will depend on which
# instance happens to handle their request.
emotion_engine = EmotionEngine()
subscriptions = SubscriptionStore()
router = AIRouter(emotion_engine=emotion_engine, subscriptions=subscriptions)

app = FastAPI(title="Lite AI Router")

# Comma-separated list, e.g. "https://your-frontend.onrender.com,http://localhost:5173"
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    session_id: str
    user_id: str | None = None
    persona: bool = True


class ChatResponse(BaseModel):
    reply: str
    model_label: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    messages = [m.model_dump() for m in req.messages]
    try:
        result = router.chat(
            messages,
            persona=req.persona,
            session_id=req.session_id,
            user_id=req.user_id,
        )
    except AllProvidersFailedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return scrub_result_for_user(result)
