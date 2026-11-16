"""Gemini generateContent transport for installations with unavailable SSE generation.

LiveKit still schedules speech and executes function tools. Thought signatures are
retained across tool turns, as required by Gemini 3.
"""
import asyncio
import base64
import json
from uuid import uuid4
from urllib.parse import quote

import aiohttp
from livekit.agents import APIConnectionError, APIStatusError, APITimeoutError, llm
from .config import settings


def _json_default(value):
    if isinstance(value, bytes):
        return base64.b64encode(value).decode()
    raise TypeError(f"Unsupported Gemini value: {type(value).__name__}")


class GeminiCompletion:
    def __init__(self):
        self.thought_signatures = {}

    async def generate(self, chat_ctx, tools, model_settings):
        turns, extra = chat_ctx.to_provider_format(
            format="google", thought_signatures=self.thought_signatures,
        )
        body = {"contents": turns, "generationConfig": {"thinkingConfig": {"thinkingLevel": "low"}}}
        if extra.system_messages:
            body["systemInstruction"] = {"parts": [{"text": msg} for msg in extra.system_messages]}
        declarations = llm.ToolContext(tools).parse_function_tools(
            "google", use_parameters_json_schema=True,
        )
        # No-argument tools have a null schema in LiveKit. Omit it in REST payloads,
        # just as the Google SDK excludes unset/None declaration fields.
        declarations = [{key: value for key, value in declaration.items() if value is not None}
                        for declaration in declarations]
        if declarations:
            body["tools"] = [{"functionDeclarations": declarations}]
            choice = getattr(model_settings, "tool_choice", None)
            mode = {"none": "NONE", "required": "ANY"}.get(choice, "AUTO") if isinstance(choice, str) else "AUTO"
            config = {"mode": mode}
            if isinstance(choice, dict) and choice.get("type") == "function":
                config = {"mode": "ANY", "allowedFunctionNames": [choice["function"]["name"]]}
            body["toolConfig"] = {"functionCallingConfig": config}
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               + quote(settings.google_model, safe="") + ":generateContent")
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as client:
                async with client.post(
                    url, data=json.dumps(body, default=_json_default),
                    headers={"x-goog-api-key": settings.google_api_key,
                             "Content-Type": "application/json"},
                ) as response:
                    data = await response.json()
                    if response.status != 200:
                        raise APIStatusError(
                            "Gemini generateContent failed", status_code=response.status,
                            body=json.dumps(data), retryable=False,
                        )
        except asyncio.TimeoutError as exc:
            raise APITimeoutError("Gemini generateContent timed out", retryable=False) from exc
        except aiohttp.ClientError as exc:
            raise APIConnectionError("Gemini generateContent connection failed", retryable=False) from exc
        async for chunk in self.chunks(data):
            yield chunk

    async def chunks(self, data):
        candidates = data.get("candidates") or []
        if not candidates:
            raise APIStatusError("Gemini returned no response candidates", retryable=False)
        emitted = False
        response_id = data.get("responseId") or str(uuid4())
        for part in candidates[0].get("content", {}).get("parts", []):
            if part.get("thought"):
                continue
            if call := part.get("functionCall"):
                call_id = call.get("id") or str(uuid4())
                if signature := part.get("thoughtSignature"):
                    self.thought_signatures[call_id] = base64.b64decode(signature)
                emitted = True
                yield llm.ChatChunk(id=response_id, delta=llm.ChoiceDelta(
                    role="assistant", tool_calls=[llm.FunctionToolCall(
                        call_id=call_id, name=call["name"],
                        arguments=json.dumps(call.get("args") or {}),
                    )],
                ))
            elif text := part.get("text"):
                emitted = True
                yield llm.ChatChunk(id=response_id, delta=llm.ChoiceDelta(role="assistant", content=text))
        if not emitted:
            raise APIStatusError("Gemini returned no speech or tool call", retryable=False)
