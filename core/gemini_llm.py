"""Google Gemini calls (free tier from aistudio.google.com). One request per user action, no automatic retries."""

from __future__ import annotations

from typing import TypeVar

import pandas as pd
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from .common import (
    CATEGORIZE_SYSTEM,
    INSIGHTS_SYSTEM,
    MAX_UNIQUE_DESCRIPTIONS,
    AnalyzerError,
    categorize_prompt,
    insights_prompt,
)
from .schema import CategorizationResult, InsightsResult

# Used when the model list can't be fetched. Flash-Lite first: it has the most generous free-tier limits.
FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"]
_SKIP = ("image", "tts", "audio", "live", "embedding", "vision", "robotics", "computer-use", "learnlm")

T = TypeVar("T", bound=BaseModel)


def make_client(api_key: str | None) -> genai.Client:
    # With no key passed, the SDK reads GEMINI_API_KEY / GOOGLE_API_KEY from the environment.
    try:
        return genai.Client(api_key=api_key) if api_key else genai.Client()
    except ValueError as exc:  # raised when no key is configured at all
        raise AnalyzerError("No Gemini API key found. Enter one in the sidebar or set GEMINI_API_KEY in .env.") from exc


def _model_names(client: genai.Client) -> list[str]:
    names = [
        m.name.removeprefix("models/")
        for m in client.models.list()
        if m.name and m.name.startswith("models/gemini")
        and "generateContent" in (m.supported_actions or [])
        and not any(s in m.name for s in _SKIP)
    ]
    names = sorted(set(names), reverse=True)  # newest versions first
    return sorted(names, key=lambda n: (0 if "flash-lite" in n else 1 if "flash" in n else 2))


def list_models(api_key: str) -> list[str]:
    """Text-generation Gemini models available to this key; Flash-Lite models first."""
    try:
        return _model_names(make_client(api_key)) or FALLBACK_MODELS
    except Exception:
        return FALLBACK_MODELS


def check_key(api_key: str) -> tuple[bool, str, list[str]]:
    """Validate a key with a free model-list request (no generation, no quota used).

    Returns (connected, user-facing error message, available models)."""
    try:
        return True, "", _model_names(make_client(api_key)) or FALLBACK_MODELS
    except Exception as exc:
        return False, str(_wrap_errors(exc)), FALLBACK_MODELS


def _wrap_errors(exc: Exception) -> AnalyzerError:
    if isinstance(exc, AnalyzerError):
        return exc
    if isinstance(exc, errors.APIError):
        detail = (exc.message or "").strip()
        if exc.code == 429:
            return AnalyzerError(
                "Gemini free-tier limit reached for this model. If it's a per-minute limit, wait about a minute; "
                "if it's a daily limit, try a Flash-Lite model or come back tomorrow (it resets at midnight "
                f"Pacific time, about 2 PM in Bangladesh).\n\nDetails: {detail[:400]}"
            )
        if exc.code in (401, 403) or "API key not valid" in detail:
            return AnalyzerError("Invalid Gemini API key. Create one at aistudio.google.com and paste it in the sidebar.")
        if exc.code == 404:
            return AnalyzerError("This Gemini model isn't available for your key. Pick another model in the sidebar.")
        if exc.code == 400:
            return AnalyzerError(f"Gemini rejected the request: {detail[:400]}")
        return AnalyzerError(f"Gemini API error ({exc.code}). Please try again in a moment.")
    if "connect" in type(exc).__name__.lower() or "timeout" in type(exc).__name__.lower():
        return AnalyzerError("Could not reach the Gemini API. Check your internet connection.")
    return AnalyzerError(f"Unexpected error: {exc}")


def _structured(client: genai.Client, model: str, system: str, prompt: str, schema: type[T]) -> T:
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0.2,
        max_output_tokens=16000,
    )
    try:
        response = client.models.generate_content(model=model, contents=prompt, config=config)
    except Exception as exc:
        raise _wrap_errors(exc) from exc
    result = response.parsed
    if isinstance(result, schema):
        return result
    try:  # fall back to validating the raw JSON text
        return schema.model_validate_json(response.text or "")
    except Exception as exc:
        reason = ""
        if response.candidates and response.candidates[0].finish_reason:
            reason = f" (finish reason: {response.candidates[0].finish_reason.name})"
        raise AnalyzerError(f"Gemini returned an incomplete result{reason}. Please try again.") from exc


def categorize(client: genai.Client, model: str, uniq: pd.DataFrame) -> dict[str, tuple[str, str]]:
    """ONE batched request for all unique (masked) descriptions. Returns key -> (merchant, category)."""
    sent = uniq.head(MAX_UNIQUE_DESCRIPTIONS)
    result = _structured(client, model, CATEGORIZE_SYSTEM, categorize_prompt(sent), CategorizationResult)
    by_uid = {it.id: it for it in result.items}
    return {r.key: (by_uid[r.uid].merchant.strip() or "Unknown", by_uid[r.uid].category)
            for r in sent.itertuples() if r.uid in by_uid}


def insights(client: genai.Client, model: str, summary: dict, currency: str) -> InsightsResult:
    """ONE request with aggregated numbers only."""
    return _structured(client, model, INSIGHTS_SYSTEM, insights_prompt(summary, currency), InsightsResult)
