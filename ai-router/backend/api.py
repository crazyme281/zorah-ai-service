"""
HTTP entrypoint for deployment (Render, or anywhere else running
ASGI). The CLI in main.py is unaffected and still works for local
testing — this is the second, separate way to run the same router.

Run locally:   uvicorn api:app --reload
Render runs:   uvicorn api:app --host 0.0.0.0 --port $PORT
"""
import asyncio
import json
import logging
import os
from typing import Any

import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from router import AIRouter
from emotion.engine import EmotionEngine
from access.tiers import SubscriptionStore, Tier
from access.image_policy import ImageStore, ImageQuotaExceeded
from access.payments import FlutterwaveClient, PaymentVerificationError, upgrade_plan
from branding import scrub_result_for_user
from config import API_KEYS, FLUTTERWAVE_SECRET_KEY, REQUEST_TIMEOUT
from utils.errors import AllProvidersFailedError

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Single shared instances for the process's lifetime. Subscription tier
# and image quota now live in Supabase (see access/db.py), so these are
# safe across restarts and multiple instances — only the emotion engine
# is still in-process state (see its own module for that tradeoff).
emotion_engine = EmotionEngine()
subscriptions = SubscriptionStore()
image_store = ImageStore(subscriptions)
flutterwave = FlutterwaveClient(FLUTTERWAVE_SECRET_KEY) if FLUTTERWAVE_SECRET_KEY else None
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
    # A plain string for ordinary text turns, or a list of
    # {"type": "text"|"image_url", ...} blocks once the frontend has an
    # attachment on the message (see frontend/src/lib/aiBackend.ts).
    content: str | list[dict[str, Any]]


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    session_id: str
    user_id: str | None = None
    persona: bool = True


class ChatResponse(BaseModel):
    reply: str
    model_label: str


class TranscribeResponse(BaseModel):
    text: str


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


# Words per SSE frame. This is NOT true token-by-token model streaming —
# none of the five providers behind this router are wired for it yet.
# This chunks the complete reply into a typing-speed stream so the
# frontend's existing /chat/stream consumer (streamAIBackend in
# aiBackend.ts) gets the progressive reveal it's already built for.
CHUNK_WORDS = 4
CHUNK_DELAY_S = 0.05


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    messages = [m.model_dump() for m in req.messages]

    async def event_stream():
        try:
            result = await asyncio.to_thread(
                router.chat,
                messages,
                persona=req.persona,
                session_id=req.session_id,
                user_id=req.user_id,
            )
        except AllProvidersFailedError as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        scrubbed = scrub_result_for_user(result)
        words = scrubbed["reply"].split(" ")
        for i in range(0, len(words), CHUNK_WORDS):
            chunk = " ".join(words[i : i + CHUNK_WORDS])
            if i + CHUNK_WORDS < len(words):
                chunk += " "
            yield f"data: {json.dumps({'delta': chunk, 'model_label': scrubbed['model_label']})}\n\n"
            await asyncio.sleep(CHUNK_DELAY_S)

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


GROQ_TRANSCRIBE_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(audio: UploadFile = File(...)):
    """
    Server-side speech-to-text for browsers with no SpeechRecognition —
    see transcribeAudio in aiBackend.ts. Uses Groq's hosted Whisper
    endpoint since GROQ_API_KEY is already configured for chat.
    """
    if not API_KEYS["groq"]:
        raise HTTPException(status_code=503, detail="transcription not configured")

    audio_bytes = await audio.read()
    files = {"file": (audio.filename or "recording.webm", audio_bytes, audio.content_type or "audio/webm")}
    data = {"model": "whisper-large-v3"}
    headers = {"Authorization": f"Bearer {API_KEYS['groq']}"}

    try:
        resp = await asyncio.to_thread(
            requests.post,
            GROQ_TRANSCRIBE_ENDPOINT,
            headers=headers,
            files=files,
            data=data,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=503, detail=f"transcription request failed: {e}")

    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"transcription failed: {resp.text[:200]}")

    return {"text": resp.json().get("text", "")}


# ---------------------------------------------------------------------------
# Plan / quota / payments
# ---------------------------------------------------------------------------

class AuthorizeUploadRequest(BaseModel):
    user_id: str
    # Client-generated UUID, also used as the Storage path — lets the
    # backend track this specific image's retention clock, not just
    # the daily quota count.
    image_id: str


class SelectPlanRequest(BaseModel):
    user_id: str
    tier: str  # "FREE" only — paid tiers go through /payments/verify


class VerifyPaymentRequest(BaseModel):
    user_id: str
    tier: str  # "GO" or "PRO"
    tx_id: str


@app.get("/account/plan/{user_id}")
def get_plan(user_id: str):
    """Tier + subscription window + today's image quota, for the frontend
    to render (plan badge, grace-period banner, 'N of 6 images used')."""
    status = subscriptions.status_for(user_id)
    quota = image_store.remaining_today(user_id)
    return {**status, "image_quota": quota}


@app.post("/account/plan/select")
def select_plan(req: SelectPlanRequest):
    """Onboarding only picks FREE for free — Go/Pro must go through
    /payments/verify, which is the only place a paid tier gets granted."""
    if req.tier != Tier.FREE.value:
        raise HTTPException(
            status_code=400,
            detail="Go/Pro require a verified payment — call /payments/verify instead.",
        )
    subscriptions.set_free(req.user_id)
    return subscriptions.status_for(req.user_id)


@app.post("/images/authorize")
def authorize_upload(req: AuthorizeUploadRequest):
    """
    Called by the frontend (attachments.ts) right before an image is
    compressed and uploaded to Storage — the only place quota is
    actually decremented. A rejected call here means the upload never
    happens, so quota can't be burned by a failed or duplicate attempt.
    """
    try:
        quota = image_store.record_upload(req.user_id, req.image_id)
    except ImageQuotaExceeded as e:
        raise HTTPException(
            status_code=429,
            detail=f"You've used all {e.limit} images for today on the {e.tier} plan. "
            f"Try again tomorrow, or upgrade for a higher daily limit.",
        )
    return {"authorized": True, "image_quota": quota}


class ResyncImageRequest(BaseModel):
    image_id: str
    device_has_it: bool


@app.get("/images/{image_id}/availability")
def image_availability(image_id: str):
    """
    What the AI layer (or the frontend, before referencing an old
    attachment) should check before assuming an image is still visible
    server-side. Never reports "available" for something that's aged
    out of SERVER_RETENTION — see access/image_policy.py.
    """
    return image_store.access_result(image_id)


@app.post("/images/resync")
def resync_image(req: ResyncImageRequest):
    """
    Called when the frontend still has an image on-device that the
    server has aged out — refreshes the server's retention clock so it
    becomes available again. If the device doesn't have it either,
    this is a no-op and the image stays unavailable.
    """
    resynced = image_store.resync_from_device(req.image_id, req.device_has_it)
    return {"resynced": resynced, **image_store.access_result(req.image_id)}


@app.post("/payments/verify")
def verify_payment(req: VerifyPaymentRequest):
    if flutterwave is None:
        raise HTTPException(status_code=503, detail="payments not configured")
    try:
        tier = Tier(req.tier)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"unknown tier '{req.tier}'")

    try:
        result = upgrade_plan(req.user_id, req.tx_id, tier, flutterwave, subscriptions)
    except PaymentVerificationError as e:
        raise HTTPException(status_code=402, detail=str(e))

    return result