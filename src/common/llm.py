"""Thin Bedrock LLM wrapper.

Goals:
  * Be model-agnostic (Claude / Nova / etc.) — model id is read from env.
  * Support JSON-mode invocation with retry on schema parse failure.
  * Provide a streaming hook for voice replies.
"""
from __future__ import annotations

import json
import os
from typing import Any, Iterable

import boto3
from botocore.exceptions import ClientError

from .logging_utils import get_logger

logger = get_logger(__name__)

_DEFAULT_MODEL = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
_DEFAULT_REGION = os.getenv("AWS_REGION", "us-east-1")
_MAX_RETRIES = 2


class LLMError(RuntimeError):
    """Raised when the LLM call fails or returns malformed output."""


class LLM:
    """Thin facade over ``bedrock-runtime``.

    Usage:
        llm = LLM()
        text = llm.complete("hello")
        plan = llm.complete_json("...", schema_hint={...})
    """

    def __init__(
        self,
        model_id: str | None = None,
        region: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> None:
        self.model_id = model_id or _DEFAULT_MODEL
        self.region = region or _DEFAULT_REGION
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = boto3.client("bedrock-runtime", region_name=self.region)

    # ------------------------------------------------------------------ #
    # Plain text completion
    # ------------------------------------------------------------------ #
    def complete(self, prompt: str, system: str | None = None) -> str:
        body = self._build_body(prompt, system)
        try:
            resp = self._client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
        except ClientError as exc:
            logger.exception("bedrock.invoke_model failed", extra={"model": self.model_id})
            raise LLMError(str(exc)) from exc

        return self._extract_text(json.loads(resp["body"].read()))

    # ------------------------------------------------------------------ #
    # JSON completion with retry
    # ------------------------------------------------------------------ #
    def complete_json(
        self,
        prompt: str,
        system: str | None = None,
        schema_hint: dict | None = None,
    ) -> dict:
        """Ask the model to reply in JSON; retry on parse failure."""
        sys_prompt = system or ""
        if schema_hint:
            sys_prompt += (
                "\n\nReturn ONLY a JSON object that conforms to this schema:\n"
                + json.dumps(schema_hint, ensure_ascii=False)
            )
        last_err: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            text = self.complete(prompt, system=sys_prompt)
            try:
                return _coerce_json(text)
            except ValueError as exc:
                last_err = exc
                logger.warning(
                    "llm.json_parse_failed",
                    extra={"attempt": attempt, "snippet": text[:200]},
                )
                prompt = (
                    "Your previous reply was not valid JSON. "
                    "Reply with ONLY a valid JSON object, no prose.\n\n"
                    f"Original task:\n{prompt}"
                )
        raise LLMError(f"LLM did not return valid JSON after retries: {last_err}")

    # ------------------------------------------------------------------ #
    # Streaming (used by Nova Sonic TTS bridge)
    # ------------------------------------------------------------------ #
    def stream(self, prompt: str, system: str | None = None) -> Iterable[str]:
        body = self._build_body(prompt, system)
        resp = self._client.invoke_model_with_response_stream(
            modelId=self.model_id,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        for event in resp["body"]:
            chunk = event.get("chunk")
            if not chunk:
                continue
            data = json.loads(chunk["bytes"])
            piece = self._extract_stream_delta(data)
            if piece:
                yield piece

    # ------------------------------------------------------------------ #
    # Internals — protocol shape differs per model family.
    # ------------------------------------------------------------------ #
    def _build_body(self, prompt: str, system: str | None) -> dict[str, Any]:
        # OpenAI-compatible Chat Completions (Kimi / Moonshot / etc.)
        if any(k in self.model_id for k in ("moonshot", "kimi")):
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append(
                {"role": "user", "content": [{"type": "text", "text": prompt}]}
            )
            return {
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
        # Anthropic Claude
        if "anthropic" in self.model_id or "claude" in self.model_id:
            body: dict[str, Any] = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                body["system"] = system
            return body
        # Nova / Titan style
        return {
            "inputText": (system + "\n\n" + prompt) if system else prompt,
            "textGenerationConfig": {
                "maxTokenCount": self.max_tokens,
                "temperature": self.temperature,
            },
        }

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        # OpenAI-compatible (Kimi / Moonshot)
        if "choices" in payload:
            choice = payload["choices"][0]
            msg = choice.get("message") or {}
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(c.get("text", "") for c in content if isinstance(c, dict))
            return ""
        if "content" in payload:  # Anthropic
            blocks = payload["content"]
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if "results" in payload:  # Titan
            return payload["results"][0].get("outputText", "")
        if "output" in payload:  # Nova
            return payload["output"]["message"]["content"][0].get("text", "")
        return json.dumps(payload)

    @staticmethod
    def _extract_stream_delta(data: dict[str, Any]) -> str:
        # OpenAI-style streaming
        if "choices" in data:
            ch = data["choices"][0]
            delta = ch.get("delta") or {}
            return delta.get("content", "") or ""
        # Anthropic streaming
        if data.get("type") == "content_block_delta":
            return data["delta"].get("text", "")
        # Titan / Nova streaming
        if "outputText" in data:
            return data["outputText"]
        if "delta" in data and isinstance(data["delta"], dict):
            return data["delta"].get("text", "")
        return ""


def _coerce_json(text: str) -> dict:
    """Try to parse JSON from a string that may contain code fences."""
    text = text.strip()
    if text.startswith("```"):
        # strip ```json ... ```
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found")
    return json.loads(text[start : end + 1])
