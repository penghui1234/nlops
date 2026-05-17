"""Amazon Nova Sonic adapter for ASR (and TTS placeholder).

Nova Sonic is a Speech-to-Speech bidirectional model on Bedrock. For
the v1 NLOps API path (REST), we use it as:
  * ASR: audio bytes -> transcript text
  * (TTS): text -> audio chunks (base64 in response, or pre-uploaded to S3)

The actual streaming protocol is bidirectional WebSocket-style; for
REST entry we accept a base64-encoded audio chunk (≤ 30s) and call the
synchronous transcribe API. For longer / streaming voice we recommend
moving the entry path to an API Gateway WebSocket route.
"""
from __future__ import annotations

import base64
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

from common.logging_utils import get_logger

logger = get_logger(__name__)

_REGION = os.getenv("AWS_REGION", "us-east-1")
_NOVA_SONIC_MODEL = os.getenv(
    "NOVA_SONIC_MODEL_ID",
    "amazon.nova-2-sonic-v1:0",
)


class NovaSonic:
    """Thin facade over Nova Sonic ASR."""

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or _NOVA_SONIC_MODEL
        self._bedrock = boto3.client("bedrock-runtime", region_name=_REGION)

    # ------------------------------------------------------------------ #
    def transcribe_b64(self, audio_b64: str, language: str = "zh-CN") -> str:
        """Transcribe a base64-encoded short audio clip to text."""
        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception as exc:
            raise ValueError(f"invalid base64 audio: {exc}") from exc

        body = {
            "input_audio": {
                "data": base64.b64encode(audio_bytes).decode("ascii"),
                "format": "wav",                          # caller responsibility
                "sampleRate": 16000,
            },
            "task": "transcribe",
            "language": language,
        }
        try:
            import json as _json
            resp = self._bedrock.invoke_model(
                modelId=self.model_id,
                body=_json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            payload = _json.loads(resp["body"].read())
            return payload.get("text", "") or payload.get("transcript", "")
        except ClientError as exc:
            logger.exception("nova_sonic.transcribe_failed")
            return f"[ASR error: {exc.response['Error']['Code']}]"
        except Exception as exc:
            logger.exception("nova_sonic.unexpected_error")
            return f"[ASR error: {exc}]"

    # ------------------------------------------------------------------ #
    def synthesize(self, text: str, language: str = "zh-CN") -> bytes:
        """Synthesize speech from text. Returns raw audio bytes (wav)."""
        body = {
            "text": text,
            "task": "synthesize",
            "language": language,
            "voice": os.getenv("NOVA_SONIC_VOICE", "default"),
        }
        try:
            import json as _json
            resp = self._bedrock.invoke_model(
                modelId=self.model_id,
                body=_json.dumps(body),
                contentType="application/json",
                accept="audio/wav",
            )
            return resp["body"].read()
        except ClientError as exc:
            logger.exception("nova_sonic.synth_failed")
            return b""
