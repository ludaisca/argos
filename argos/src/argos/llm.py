"""Cliente de LLM provider-agnostic (API compatible con OpenAI).

Sirve para cualquier proveedor con endpoint ``/chat/completions``:
OpenAI, DeepSeek, Groq, OpenRouter, Together, Ollama/LM Studio locales, etc.
Se configura por variables de entorno (pensado para Docker) o por config.yaml.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests

from argos.config import ArgosConfig
from argos.errors import ArgosError

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


class LLMError(ArgosError):
    """Falla al hablar con el proveedor de LLM."""


@dataclass(frozen=True)
class LLMSettings:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL


def resolve_llm_settings(config: ArgosConfig | None = None) -> LLMSettings | None:
    """Resuelve la configuración del LLM: env primero (Docker), luego config.yaml."""
    config = config or ArgosConfig.load()
    api_key = os.environ.get("ARGOS_LLM_API_KEY") or config.get("llm_api_key")
    if not api_key:
        return None
    base_url = (
        os.environ.get("ARGOS_LLM_BASE_URL")
        or config.get("llm_base_url")
        or DEFAULT_BASE_URL
    )
    model = os.environ.get("ARGOS_LLM_MODEL") or config.get("llm_model") or DEFAULT_MODEL
    return LLMSettings(
        api_key=str(api_key),
        base_url=str(base_url).rstrip("/"),
        model=str(model),
    )


def _post(settings: LLMSettings, payload: dict[str, Any], timeout: int) -> requests.Response:
    try:
        return requests.post(
            f"{settings.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise LLMError(f"no se pudo contactar el LLM ({settings.base_url}): {exc}") from exc


def chat(
    settings: LLMSettings,
    messages: list[dict[str, str]],
    *,
    json_mode: bool = False,
    timeout: int = 120,
    temperature: float = 0.2,
) -> str:
    """Devuelve el contenido del primer mensaje de respuesta del modelo."""
    payload: dict[str, Any] = {
        "model": settings.model,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    response = _post(settings, payload, timeout)
    if json_mode and response.status_code == 400:
        # Algunos proveedores no soportan response_format: reintentamos sin él.
        payload.pop("response_format", None)
        response = _post(settings, payload, timeout)

    if not response.ok:
        raise LLMError(
            f"el LLM ({settings.model}) devolvió HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"respuesta inesperada del LLM: {exc}") from exc
    if not isinstance(content, str):
        raise LLMError("respuesta del LLM sin contenido de texto")
    return content


def parse_json_response(content: str) -> Any:
    """Extrae JSON de una respuesta del modelo (tolera ```json ... ```)."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"el LLM no devolvió JSON válido: {exc}") from exc
