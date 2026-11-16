import ast
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from uuid import uuid4
from google.genai import types
from livekit import agents
from livekit.agents import llm as agent_llm
from livekit.agents import (Agent, AgentServer, AgentSession, function_tool,
                            APIError, APIConnectOptions, SessionConnectOptions, RunContext, get_job_context)
from livekit.plugins import elevenlabs, google, silero
from .config import settings
from . import store
from .gemini_completion import GeminiCompletion
from .tool_replies import tool_reply
from .birth_dates import parse_birth_date

# Plugins also read standard environment names.
for key in ("livekit_url", "livekit_api_key", "livekit_api_secret", "eleven_api_key",
            "google_api_key"):
    if value := getattr(settings, key):
        os.environ[key.upper()] = value

logger = logging.getLogger(__name__)

class DeliveryAgent(Agent):
    def __init__(self, call_id: str):
        self.call_id = call_id
        self._quota_message = None
        self._completion = GeminiCompletion()
        self._awaiting_birth_date = False
        self._verified_context = None
        self._recipient_unknown = True
        self._end_call_task = None
        self._ending_call = False
        customer = store.call_customer(call_id)
        # Explicit titles belong to this fixed demo dataset, not a name/gender heuristic.
        titles = {"c1": "Hanım", "c2": "Bey", "c3": "Hanım", "c4": "Bey",
                  "c5": "Hanım", "c6": "Bey", "c7": "Hanım", "c8": "Bey"}
        title = titles.get(customer["id"], "")
        self.customer_address = f"{customer['name'].split()[0]} {title}".strip()
        prompt = (Path(__file__).parent / "prompts/delivery.md").read_text()
        super().__init__(instructions=prompt + f"\nAranan kayıtlı müşteri (telefondaki kişi henüz doğrulanmadı): {customer['name']}."
                         + f"\nGörüşme başlangıcı (İstanbul): {datetime.now(ZoneInfo('Europe/Istanbul')).isoformat()}")

    async def on_enter(self):
        # A fixed outbound opening does not depend on an LLM request or user speech.
        await self.session.say(
            f"Merhaba {self.customer_address}. Ben Freya'nın yapay zekâ asistanıyım. "
            "Sizinle mi görüşüyorum?",
            allow_interruptions=False,
        )

    async def llm_node(self, chat_ctx, tools, model_settings):
        if chat_ctx is not None and chat_ctx.items:
            last = chat_ctx.items[-1]
            if not self._recipient_unknown and last.type == "message" and last.role == "user":
                text = " ".join(re.sub(r"[^\w\s]", " ", last.text_content.lower()).split())
                if text in {"beni aramayın", "bir daha aramayın", "beni bir daha aramayın",
                            "tekrar aranmak istemiyorum", "bir daha aranmak istemiyorum"}:
                    yield agent_llm.ChatChunk(id=str(uuid4()), delta=agent_llm.ChoiceDelta(
                        role="assistant", tool_calls=[agent_llm.FunctionToolCall(
                            call_id=str(uuid4()), name="opt_out_calls",
                            arguments=json.dumps({"confirmed": True}),
                        )]))
                    return
            if self._recipient_unknown and last.type == "message" and last.role == "user":
                acknowledgment = " ".join(re.sub(r"[^\w\s]", " ", last.text_content.lower()).split())
                # Explicit wrong-number/name denials do not need a model request.
                denied_name = re.fullmatch(r"(?:(?:yok|hayır) )*benim adım (\w+(?: \w+)?)", acknowledgment)
                wrong_number = acknowledgment in {"yanlış numara", "hayır yanlış numara",
                    "yanlış kişiyi aradınız", "yanlış kişiyi arıyorsunuz", "bu kişi ben değilim",
                    "ben o kişi değilim"}
                if wrong_number or (denied_name and denied_name[1].split()[0] != self.customer_address.split()[0].lower()):
                    yield agent_llm.ChatChunk(id=str(uuid4()), delta=agent_llm.ChoiceDelta(
                        role="assistant", tool_calls=[agent_llm.FunctionToolCall(
                            call_id=str(uuid4()), name="confirm_recipient",
                            arguments=json.dumps({"recipient_status": "incorrect_details"}),
                        )]))
                    return
                if acknowledgment in {"evet", "evet benim", "evet buyurun", "benim buyurun",
                                       "evet benim şu anda görüşmek için müsaitim",
                                       "evet benim müsaitim", "evet benim buyurun"}:
                    result = self._run(store.confirm_recipient, "self")
                    if reply := tool_reply("confirm_recipient", result):
                        self._recipient_unknown = False
                        self._awaiting_birth_date = True
                        yield reply
                        return
            if self._awaiting_birth_date and last.type == "message" and last.role == "user":
                if birth_date := parse_birth_date(last.text_content):
                    result = self._verify_date(birth_date)
                    if reply := tool_reply("verify_identity", result):
                        self._awaiting_birth_date = not result.get("verified") and result.get("remaining_attempts", 0) > 0
                        logger.info("Speaking direct date verification result: verified=%s", result.get("verified"))
                        yield reply
                        return
            if last.type == "function_call_output" and not last.is_error:
                try:
                    result = json.loads(last.output)
                except (TypeError, ValueError):
                    # LiveKit 1.8 serializes dict tool results with str(dict), not JSON.
                    try:
                        result = ast.literal_eval(last.output)
                    except (TypeError, ValueError, SyntaxError):
                        result = None
                if reply := tool_reply(last.name, result):
                    if last.name == "confirm_recipient" and result.get("recipient_status") == "self":
                        self._recipient_unknown = False
                        self._awaiting_birth_date = True
                    if last.name == "verify_identity":
                        self._awaiting_birth_date = not result.get("verified") and result.get("remaining_attempts", 0) > 0
                    logger.info("Speaking authoritative tool result: tool=%s", last.name)
                    yield reply
                    return
        if self._quota_message:
            yield self._quota_message
            return
        try:
            context = chat_ctx
            if self._verified_context and chat_ctx is not None:
                context = chat_ctx.copy()
                context.add_message(role="system", content=(
                    "Güncel sunucu sonucu: kimlik SQLite üzerinden doğrulandı. "
                    "Tekrar doğum tarihi isteme. Seçenek kimlikleri ve mevcut rezervasyon: "
                    + json.dumps(self._verified_context, ensure_ascii=False)))
            async for chunk in self._completion.generate(context, tools, model_settings):
                yield chunk
        except APIError as exc:
            quota_exceeded = getattr(exc, "status_code", None) == 429
            message = (
                "Şu anda konuşma hizmetinin kullanım sınırına ulaşıldığı için devam edemiyorum. "
                "Lütfen daha sonra tekrar deneyin."
                if quota_exceeded else
                "Şu anda teknik bir bağlantı sorunu nedeniyle yanıt veremiyorum. "
                "Lütfen biraz sonra tekrar deneyin."
            )
            if quota_exceeded:
                # Repeated user speech must not create more requests against exhausted quota.
                self._quota_message = message
            logger.warning("LLM request failed: type=%s status=%s quota_exceeded=%s",
                           type(exc).__name__, getattr(exc, "status_code", None), quota_exceeded)
            ctx = get_job_context(required=False)
            if ctx:
                status = getattr(exc, "status_code", None)
                detail = {
                    429: "Gemini 429: proje/model kotası dolu. Google AI Studio kota ve faturalandırma ayarlarını kontrol edin.",
                    404: "Gemini 404: seçilen model bu hesapta kullanılamıyor. GOOGLE_MODEL ayarını kontrol edin.",
                    403: "Gemini 403: API anahtarının proje/model erişim izni yok.",
                    400: "Gemini 400: model istek yapılandırmasını reddetti. Backend kayıtlarını kontrol edin.",
                    504: "Gemini 504: sağlayıcı yanıtı zaman aşımına uğradı.",
                    503: "Gemini 503: model sağlayıcı yoğunluğu nedeniyle geçici olarak kullanılamıyor.",
                }.get(status, "Gemini yanıtı zamanında alınamadı. Backend kayıtlarını kontrol edin.")
                try:
                    await ctx.room.local_participant.publish_data(
                        json.dumps({"message": detail}).encode(), reliable=True,
                        topic="freya.error",
                    )
                except Exception:
                    logger.warning("Could not send provider error to the room")
            # Feed a fixed explanation to ElevenLabs without another LLM request.
            yield message

    @function_tool
    async def confirm_recipient(self, context: RunContext, recipient_status: str) -> dict:
        """Muhatabı self, other_person veya incorrect_details olarak kaydet. Yanlış muhatapta vedadan sonra görüşme otomatik kapanır."""
        result = self._run(store.confirm_recipient, recipient_status)
        if result.get("status") in ("other_person", "incorrect_details"):
            self._recipient_unknown = False
            self._awaiting_birth_date = False
            self._end_after_playout(context, reason=result["status"])
        return result

    @function_tool
    async def get_existing_booking(self) -> dict:
        """Yalnız kimlik doğrulamasından sonra mevcut rezervasyonun tarih/saatini getir."""
        return self._run(store.existing_booking)

    @function_tool
    async def verify_identity(self, birth_date: str) -> dict:
        """Müşterinin söylediği doğum tarihini YYYY-MM-DD formatında doğrula."""
        return self._verify_date(birth_date)

    def _verify_date(self, birth_date):
        result = self._run(store.verify, birth_date)
        if result.get("verified"):
            if not result.get("booking"):
                result["slots"] = store.available_slots(self.call_id)
            self._verified_context = result
        return result

    @function_tool
    async def get_available_slots(self) -> dict:
        """Doğrulanmış müşterinin ilçesindeki kalan kurye yerlerini getir."""
        return self._run(lambda call_id: {"slots": store.available_slots(call_id)})

    @function_tool
    async def reserve_delivery(self, context: RunContext, slot_id: str, confirmed: bool) -> dict:
        """Açık onaydan sonra rezervasyon yap; başarı kapanışı seslendirildikten sonra görüşme otomatik biter."""
        result = self._run(store.book, slot_id, confirmed)
        if result.get("booking_id"):
            if not result.get("delivery_date"):
                result.update(store.existing_booking(self.call_id)["booking"])
            self._end_after_playout(context)
        return result

    def _end_after_playout(self, context: RunContext, reason: str = "delivery_completed"):
        if self._ending_call:
            return
        self._ending_call = True
        context.disallow_interruptions()
        context.session.input.set_audio_enabled(False)

        def spoken(_handle):
            # The tool follow-up shares this handle. Do not await it inside its own tool.
            self._end_call_task = asyncio.create_task(self._close_completed_room(context.session, reason))

        context.speech_handle.add_done_callback(spoken)

    async def _close_completed_room(self, session, reason: str = "delivery_completed"):
        job = get_job_context()
        logger.info("Closing terminal call after final speech: reason=%s", reason)
        await job.delete_room()
        session.shutdown()
        job.shutdown(reason=reason)

    @function_tool
    async def opt_out_calls(self, context: RunContext, confirmed: bool) -> dict:
        """Müşterinin açık tekrar aranmama talebini kaydet; bekleyen geri aramaları iptal et."""
        result = self._run(store.opt_out_calls, confirmed)
        if result.get("do_not_call"):
            self._verified_context = None
            self._awaiting_birth_date = False
            self._end_after_playout(context, reason="do_not_call")
        return result

    @function_tool
    async def request_callback(self, context: RunContext, requested_at: str, confirmed: bool) -> dict:
        """Açık onayla geri aranma isteği kaydet. Başarılı kayıttan ve vedadan sonra görüşme otomatik kapanır."""
        result = self._run(store.request_callback, requested_at, confirmed)
        if result.get("callback_id") and result.get("status") == "pending":
            self._end_after_playout(context, reason="callback_requested")
        return result

    @function_tool
    async def finish_call(self, context: RunContext, outcome: str) -> dict:
        """Sonucu kaydet. Mevcut rezervasyon onaylandıysa kapanıştan sonra görüşmeyi bitir."""
        result = self._run(store.close_call, outcome)
        if result.get("status") == "existing_booking_confirmed":
            self._end_after_playout(context)
        return result

    def _run(self, fn, *args):
        started = time.monotonic()
        try:
            result = fn(self.call_id, *args)
            logger.info("Business tool completed: tool=%s duration_ms=%.1f verified=%s",
                        getattr(fn, "__name__", "tool"), (time.monotonic()-started)*1000,
                        result.get("verified") if isinstance(result, dict) else None)
            return result
        except store.RuleError as exc:
            logger.info("Business tool rejected: tool=%s duration_ms=%.1f",
                        getattr(fn, "__name__", "tool"), (time.monotonic()-started)*1000)
            return {"error": str(exc)}

server = AgentServer()

@server.rtc_session(agent_name=settings.livekit_agent_name)
async def entrypoint(ctx: agents.JobContext):
    # Jobs run in fresh processes. Apply additive migrations before any tools execute,
    # including when the worker was launched before a database schema update.
    store.initialize()
    metadata = json.loads(ctx.job.metadata or "{}")
    call_id = metadata.get("call_id")
    if not isinstance(call_id, str):
        raise ValueError("A server-issued call_id is required")
    store.call_customer(call_id)
    llm = google.LLM(
        model=settings.google_model,
        api_key=settings.google_api_key,
        vertexai=False,
        http_options=types.HttpOptions(api_version="v1beta"),
        thinking_config=types.ThinkingConfig(thinking_level="low"),
    )
    session = AgentSession(
        conn_options=SessionConnectOptions(
            llm_conn_options=APIConnectOptions(max_retry=0, timeout=12),
        ),
        stt=elevenlabs.STT(model=settings.eleven_stt_model, language_code="tr"),
        llm=llm,
        tts=elevenlabs.TTS(voice_id=settings.eleven_voice_id,
                           model=settings.eleven_tts_model, language="tr"),
        vad=silero.VAD.load(),
    )
    await ctx.connect()
    await ctx.wait_for_participant()
    await session.start(room=ctx.room, agent=DeliveryAgent(call_id))

if __name__ == "__main__":
    store.initialize()
    agents.cli.run_app(server)
