import json
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4
from fastapi import Depends, FastAPI, Header, HTTPException
from livekit import api
from pydantic import BaseModel
from .config import settings
from . import store

@asynccontextmanager
async def lifespan(app):
    if not settings.backend_api_key:
        raise RuntimeError("Set BACKEND_API_KEY in backend/.env")
    store.initialize()
    yield

app = FastAPI(title="Freya Delivery API", lifespan=lifespan)

def authenticate(x_api_key: str = Header(default="")):
    if not settings.backend_api_key or not secrets.compare_digest(x_api_key, settings.backend_api_key):
        raise HTTPException(401, "Unauthorized")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/dashboard", dependencies=[Depends(authenticate)])
def dashboard():
    return store.dashboard()

class SessionRequest(BaseModel):
    customer_id: str

class CallbackResolution(BaseModel):
    status: str

@app.post("/callbacks/{callback_id}", dependencies=[Depends(authenticate)])
def resolve_callback(callback_id: str, body: CallbackResolution):
    try:
        return store.resolve_callback(callback_id, body.status)
    except store.RuleError as exc:
        raise HTTPException(400, str(exc)) from None

@app.post("/sessions", dependencies=[Depends(authenticate)])
async def create_session(body: SessionRequest):
    if not settings.demo_mode:
        raise HTTPException(403, "Browser customer selection is only available in demo mode")
    required = [settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret,
                settings.eleven_api_key, settings.eleven_voice_id]
    if not all(required) or not settings.google_api_key:
        raise HTTPException(503, "backend/.env içindeki LiveKit, ElevenLabs ve GOOGLE_API_KEY alanlarını doldurun.")
    try:
        call_id = store.create_call(body.customer_id)
    except store.RuleError as exc:
        raise HTTPException(404, str(exc)) from None
    room = f"freya-{uuid4()}"
    identity = f"demo-{uuid4()}"
    token = (api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
             .with_identity(identity).with_ttl(timedelta(minutes=15))
             .with_grants(api.VideoGrants(room_join=True, room=room)))
    # Explicit dispatch pins the trusted call id; the browser cannot choose agent metadata.
    client = api.LiveKitAPI(settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret)
    try:
        await client.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
            agent_name=settings.livekit_agent_name, room=room,
            metadata=json.dumps({"call_id": call_id})))
    except Exception:
        store.close_call(call_id, "needs_support")
        raise HTTPException(502, "LiveKit bağlantısı kurulamadı; servis ayarlarını kontrol edin.") from None
    finally:
        await client.aclose()
    return {"token": token.to_jwt(), "server_url": settings.livekit_url, "call_id": call_id}
