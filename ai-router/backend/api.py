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
from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from router import AIRouter
from emotion.engine import EmotionEngine
from access.tiers import SubscriptionStore, Tier
from access.image_policy import ImageStore, ImageQuotaExceeded
from access.payments import FlutterwaveClient, PaymentVerificationError, upgrade_plan, initiate_payment
from access import devices as device_links
from access import apk as apk_releases
from access.db import select
from access import codefix_db
from access import codefix_pipeline
from config import MAX_UPLOAD_ZIP_BYTES
from branding import scrub_result_for_user
from config import API_KEYS, FLUTTERWAVE_SECRET_KEY, REQUEST_TIMEOUT, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
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


def require_user(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency: verifies the bearer token by asking Supabase
    who it belongs to (GET /auth/v1/user), rather than decoding the JWT
    ourselves — this way it's automatically correct if Supabase ever
    rotates its signing keys, and a revoked/expired token is rejected by
    the same authority that issued it. Defined here, near the top, since
    /payments/* and /account/* (below) need it just as much as the
    device-linking endpoints further down do — minting a login session
    and granting a paid tier are both too high-stakes to trust a bare
    client-supplied user_id for."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")

    resp = requests.get(
        f"{SUPABASE_URL}/auth/v1/user",
        headers={"apikey": SUPABASE_SERVICE_ROLE_KEY, "Authorization": authorization},
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="invalid or expired session")
    return resp.json()["id"]


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


class SuggestionsRequest(BaseModel):
    user_message: str
    assistant_reply: str


class SuggestionsResponse(BaseModel):
    suggestions: list[str]


SUGGESTIONS_SYSTEM_PROMPT = (
    "You suggest natural follow-up questions for a chat assistant. Given the "
    "user's last message and the assistant's reply, propose exactly 3 short "
    "follow-up questions or requests the user might realistically want to ask "
    "next, specific to what was just discussed — never generic filler like "
    "'tell me more'. Each under 8 words. Respond with ONLY a JSON array of "
    "3 strings, nothing else — no markdown fences, no commentary."
)

# How much of each side of the exchange we'll actually send — long
# replies don't need to be sent in full for a next-question guess, and it
# keeps this call cheap regardless of how long the real answer ran.
SUGGESTIONS_CONTEXT_CHARS = 1200


@app.post("/suggestions", response_model=SuggestionsResponse)
def suggestions(req: SuggestionsRequest):
    """
    Cheap, fast follow-up suggestions using Groq directly — bypassing the
    full router, since this needs no classification, persona, or fallback
    chain, just one quick well-formed reply. Called by the frontend after
    a message finishes streaming; never blocks or errors the main chat —
    any failure here just means no suggestion chips render.
    """
    groq = router.providers.get("groq")
    if groq is None:
        return {"suggestions": []}

    user_text = req.user_message[:SUGGESTIONS_CONTEXT_CHARS]
    reply_text = req.assistant_reply[:SUGGESTIONS_CONTEXT_CHARS]
    prompt = f"User: {user_text}\n\nAssistant: {reply_text}"

    try:
        raw = groq.chat(
            [
                {"role": "system", "content": SUGGESTIONS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=150,
            temperature=0.7,
        )
        cleaned = raw.strip().strip("`")
        if cleaned[:4].lower() == "json":
            cleaned = cleaned[4:].strip()
        parsed = json.loads(cleaned)
        items = [str(s).strip() for s in parsed if isinstance(s, str) and s.strip()]
        return {"suggestions": items[:3]}
    except Exception as e:
        logging.warning("suggestions generation failed: %s", e)
        return {"suggestions": []}


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
    tier: str  # "FREE" only — paid tiers go through /payments/initiate + /payments/verify


class InitiatePaymentRequest(BaseModel):
    tier: str  # "GO" or "PRO"


class VerifyPaymentRequest(BaseModel):
    tier: str  # "GO" or "PRO" — must match what was initiated
    transaction_id: str  # Flutterwave's own numeric id, from the checkout callback


@app.get("/account/plan")
def get_plan(user_id: str = Depends(require_user)):
    """Tier + subscription window + today's image quota, for the frontend
    to render (plan badge, grace-period banner, 'N of 6 images used')."""
    status = subscriptions.status_for(user_id)
    quota = image_store.remaining_today(user_id)
    return {**status, "image_quota": quota}


@app.post("/account/plan/select")
def select_plan(req: SelectPlanRequest, user_id: str = Depends(require_user)):
    """Onboarding only picks FREE for free — Go/Pro must go through
    /payments/initiate + /payments/verify, the only path a paid tier
    gets granted through."""
    if req.tier != Tier.FREE.value:
        raise HTTPException(
            status_code=400,
            detail="Go/Pro require a verified payment — see /payments/initiate.",
        )
    subscriptions.set_free(user_id)
    return subscriptions.status_for(user_id)


@app.post("/payments/initiate")
def start_payment(req: InitiatePaymentRequest, user_id: str = Depends(require_user)):
    """Step 1 of paying for Go/Pro — called the moment 'Pay Now' is
    tapped, before Flutterwave's checkout widget even opens. Records
    which account is about to pay for which tier, so /payments/verify
    can later refuse any transaction that doesn't match this record."""
    if flutterwave is None:
        raise HTTPException(status_code=503, detail="payments not configured")
    try:
        tier = Tier(req.tier)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"unknown tier '{req.tier}'")

    try:
        return initiate_payment(user_id, tier)
    except PaymentVerificationError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
def verify_payment(req: VerifyPaymentRequest, user_id: str = Depends(require_user)):
    """Step 2 — called once Flutterwave's checkout widget reports
    success. See access/payments.py:upgrade_plan for the full trust
    chain this goes through before any tier is actually granted."""
    if flutterwave is None:
        raise HTTPException(status_code=503, detail="payments not configured")
    try:
        tier = Tier(req.tier)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"unknown tier '{req.tier}'")

    try:
        result = upgrade_plan(user_id, req.transaction_id, tier, flutterwave, subscriptions)
    except PaymentVerificationError as e:
        raise HTTPException(status_code=402, detail=str(e))

    return result

# =============================================================================
# Device linking
#
# Every endpoint below that acts on an account requires a real Supabase
# access token, via require_user() defined near the top of this file
# (moved there once /payments/* needed it too — minting a login session
# and granting a paid tier are both too high-stakes to trust a bare
# client-supplied user_id for).
# =============================================================================

class LinkStartResponse(BaseModel):
    code: str
    expires_in: int


class LinkConsumeRequest(BaseModel):
    code: str
    device_installation_id: str
    platform: str
    push_token: str | None = None


class LinkConsumeResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    user_id: str


class RegisterDeviceRequest(BaseModel):
    device_installation_id: str
    platform: str
    push_token: str | None = None


class RevokeDeviceRequest(BaseModel):
    device_id: str


class DeviceOut(BaseModel):
    id: str
    device_installation_id: str
    platform: str
    linked_at: str
    last_seen: str
    revoked_at: str | None = None


@app.post("/devices/link/start", response_model=LinkStartResponse)
def devices_link_start(user_id: str = Depends(require_user)):
    """Called from the website (already authenticated) to generate a
    pairing code for the mobile app to consume."""
    return device_links.start_link(user_id)


@app.post("/devices/link/consume", response_model=LinkConsumeResponse)
def devices_link_consume(req: LinkConsumeRequest):
    """Called from the mobile app, deliberately without a session — the
    code itself is the credential here. See device_links.consume_link for
    why that's safe."""
    try:
        session = device_links.consume_link(
            req.code, req.device_installation_id, req.platform, req.push_token
        )
    except device_links.InvalidOrExpiredCode as e:
        raise HTTPException(status_code=400, detail=str(e))
    except device_links.DeviceLinkError as e:
        logging.error("device link session mint failed: %s", e)
        raise HTTPException(status_code=502, detail="couldn't complete sign-in")
    return session


@app.post("/devices/register")
def devices_register(req: RegisterDeviceRequest, user_id: str = Depends(require_user)):
    """Called after a normal Google/password login (any platform) so
    every login path — not just the pairing-code one — ends up recorded
    in user_devices."""
    device_links.register_device(user_id, req.device_installation_id, req.platform, req.push_token)
    return {"ok": True}


@app.get("/devices", response_model=list[DeviceOut])
def devices_list(user_id: str = Depends(require_user)):
    return device_links.list_devices(user_id)


@app.post("/devices/revoke")
def devices_revoke(req: RevokeDeviceRequest, user_id: str = Depends(require_user)):
    device_links.revoke_device(user_id, req.device_id)
    return {"ok": True}


@app.get("/devices/self")
def devices_self(device_installation_id: str, user_id: str = Depends(require_user)):
    """Polled by the app itself (on foreground) to notice its own
    revocation — see the note on revoke_device() for why this is a
    check-in model rather than instant token kill."""
    status = device_links.device_status(user_id, device_installation_id)
    if status is None:
        return {"known": False, "revoked": False}
    device_links.touch_device(user_id, device_installation_id)
    return {"known": True, "revoked": status["revoked_at"] is not None}


# =============================================================================
# APK releases — "Get App" download, admin management, and auto-update.
#
# The Android app and the website are the same Capacitor build (see the
# other repo, zorah-mobile) — "admin exists only on the web" is enforced
# here in two independent ways: the frontend never routes to the admin
# page when Capacitor.isNativePlatform() is true, AND every admin endpoint
# below requires role == 'admin' looked up fresh from profiles on every
# call, so hiding the UI is a courtesy, not the actual security boundary.
# =============================================================================

def require_admin(user_id: str = Depends(require_user)) -> str:
    rows = select("profiles", {"user_id": f"eq.{user_id}", "select": "role", "limit": "1"})
    if not rows or rows[0].get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin access required")
    return user_id


class ApkOut(BaseModel):
    version: str
    version_code: int
    file_name: str
    file_size: int
    uploaded_at: str


class ApkAdminOut(ApkOut):
    id: str
    package_name: str
    storage_path: str
    uploaded_by: str


class ApkDownloadOut(BaseModel):
    url: str
    expires_in: int
    version: str
    version_code: int
    file_name: str
    file_size: int


class PopupMarkRequest(BaseModel):
    popup_type: str


@app.get("/admin/apk")
def admin_apk_current(user_id: str = Depends(require_admin)):
    current = apk_releases.get_current()
    return {"exists": current is not None, "release": current}


@app.post("/admin/apk/upload", response_model=ApkAdminOut)
async def admin_apk_upload(file: UploadFile = File(...), user_id: str = Depends(require_admin)):
    if not file.filename.lower().endswith(".apk"):
        raise HTTPException(status_code=400, detail="only .apk files are accepted")

    data = await file.read()
    try:
        return apk_releases.upload_release(data, file.filename, user_id)
    except apk_releases.ApkAlreadyExists as e:
        raise HTTPException(status_code=409, detail=str(e))
    except apk_releases.InvalidApkFile as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/admin/apk")
def admin_apk_delete(user_id: str = Depends(require_admin)):
    try:
        apk_releases.delete_current()
    except apk_releases.NoCurrentApk as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@app.get("/apk/current", response_model=ApkOut | None)
def apk_current(user_id: str = Depends(require_user)):
    current = apk_releases.get_current()
    if current is None:
        return None
    return {
        "version": current["version"],
        "version_code": current["version_code"],
        "file_name": current["file_name"],
        "file_size": current["file_size"],
        "uploaded_at": current["uploaded_at"],
    }


@app.get("/apk/download", response_model=ApkDownloadOut)
def apk_download(user_id: str = Depends(require_user)):
    try:
        return apk_releases.signed_download_url()
    except apk_releases.NoCurrentApk as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/apk/popup/should-show")
def apk_popup_should_show(popup_type: str, user_id: str = Depends(require_user)):
    if popup_type not in ("promo", "outdated"):
        raise HTTPException(status_code=400, detail="popup_type must be 'promo' or 'outdated'")
    return {"show": apk_releases.should_show_popup(user_id, popup_type)}


@app.post("/apk/popup/mark-shown")
def apk_popup_mark_shown(req: PopupMarkRequest, user_id: str = Depends(require_user)):
    if req.popup_type not in ("promo", "outdated"):
        raise HTTPException(status_code=400, detail="popup_type must be 'promo' or 'outdated'")
    apk_releases.mark_popup_shown(user_id, req.popup_type)
    return {"ok": True}


# =============================================================================
# Code Fixer — see access/codefix_pipeline.py for the actual pipeline.
# Every job is scoped to the uploader's verified user_id; codefix_db's
# get_job()/list_jobs() filter by it on every read, so a job_id alone is
# never enough to see someone else's upload, report, or result.
# =============================================================================

class CodeFixerJobOut(BaseModel):
    id: str
    status: str
    project_type: str | None = None
    original_file_name: str
    attempts: int
    problems_found: list
    files_changed: list
    dependencies_changed: dict
    validation: dict
    unresolved_issues: list
    final_status: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


@app.post("/code-fixer/jobs", response_model=CodeFixerJobOut)
async def create_code_fixer_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Depends(require_user),
):
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="only .zip files are accepted")

    data = await file.read()
    if len(data) > MAX_UPLOAD_ZIP_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"file exceeds the {MAX_UPLOAD_ZIP_BYTES // (1024*1024)}MB limit",
        )
    if data[:4] != b"PK\x03\x04":
        raise HTTPException(status_code=400, detail="not a valid zip file")

    job = codefix_db.create_job(user_id, file.filename, upload_path="")
    upload_path = codefix_pipeline.store_upload(job["id"], data)
    codefix_db.update_job(job["id"], upload_path=upload_path)

    # Returns immediately with status "queued" — the actual pipeline runs
    # after the response goes out, updating the job row as it progresses.
    # The frontend finds out what's happening by polling GET
    # /code-fixer/jobs/{id}, not by this request staying open.
    background_tasks.add_task(codefix_pipeline.run_job, job["id"], data)

    return job


@app.get("/code-fixer/jobs", response_model=list[CodeFixerJobOut])
def list_code_fixer_jobs(user_id: str = Depends(require_user)):
    return codefix_db.list_jobs(user_id)


@app.get("/code-fixer/jobs/{job_id}", response_model=CodeFixerJobOut)
def get_code_fixer_job(job_id: str, user_id: str = Depends(require_user)):
    job = codefix_db.get_job(job_id, user_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/code-fixer/jobs/{job_id}/download")
def download_code_fixer_result(job_id: str, user_id: str = Depends(require_user)):
    job = codefix_db.get_job(job_id, user_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] != "complete" or not job.get("result_path"):
        raise HTTPException(status_code=409, detail="this job doesn't have a result ready yet")
    url = codefix_pipeline.signed_url(codefix_pipeline.RESULT_BUCKET, job["result_path"])
    return {"url": url, "expires_in": 300}