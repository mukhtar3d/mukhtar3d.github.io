"""The AI layer.

Talks to Anthropic by default, or any OpenAI-compatible endpoint if you'd rather
use a different provider — set AI_PROVIDER=openai and AI_BASE_URL. Everything
below is defensive on purpose: a hackathon demo that dies because an API call
timed out is a demo that doesn't get shown, so every failure path falls back to
the deterministic ranking in matching.py.
"""

from __future__ import annotations

import json
import logging
import re
import time

import requests
from django.conf import settings

from .matching import StudentProfile
from .prompts import SYSTEM_PROMPT, build_user_prompt, candidate_payload

log = logging.getLogger(__name__)


class AIUnavailable(Exception):
    """Raised when the provider can't be reached or returns something unusable."""


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------
def extract_json(text: str) -> dict:
    """Pull the first complete JSON object out of a model response.

    Models occasionally wrap JSON in fences or add a sentence of preamble even
    when told not to, so scanning for balanced braces is more reliable than
    trusting the whole string to parse.
    """
    if not text:
        raise AIUnavailable("Empty response from the model.")

    cleaned = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start == -1:
        raise AIUnavailable("No JSON object in the model response.")

    depth, in_string, escaped = 0, False, False
    for i, ch in enumerate(cleaned[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start : i + 1])
                except json.JSONDecodeError as exc:
                    raise AIUnavailable(f"Malformed JSON from the model: {exc}") from exc
    raise AIUnavailable("Truncated JSON from the model — try raising AI_MAX_TOKENS.")


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
def _call_anthropic(system: str, user: str) -> str:
    base = settings.AI_BASE_URL or "https://api.anthropic.com"
    response = requests.post(
        f"{base.rstrip('/')}/v1/messages",
        headers={
            "content-type": "application/json",
            "x-api-key": settings.AI_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": settings.AI_MODEL,
            "max_tokens": settings.AI_MAX_TOKENS,
            "temperature": 0.2,
            "system": system,
            "messages": [
                {"role": "user", "content": user},
                # Prefilling an opening brace keeps the model from adding a
                # preamble; we stitch it back on below.
                {"role": "assistant", "content": "{"},
            ],
        },
        timeout=settings.AI_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise AIUnavailable(f"Anthropic API {response.status_code}: {response.text[:400]}")
    data = response.json()
    text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    return "{" + text


def _call_openai_compatible(system: str, user: str) -> str:
    base = settings.AI_BASE_URL or "https://api.openai.com/v1"
    response = requests.post(
        f"{base.rstrip('/')}/chat/completions",
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {settings.AI_API_KEY}",
        },
        json={
            "model": settings.AI_MODEL,
            "max_tokens": settings.AI_MAX_TOKENS,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=settings.AI_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise AIUnavailable(f"Provider API {response.status_code}: {response.text[:400]}")
    data = response.json()
    return data["choices"][0]["message"]["content"]


def call_model(system: str, user: str) -> str:
    if not settings.AI_API_KEY:
        raise AIUnavailable("AI_API_KEY is not set.")
    try:
        if settings.AI_PROVIDER == "anthropic":
            return _call_anthropic(system, user)
        return _call_openai_compatible(system, user)
    except requests.Timeout as exc:
        raise AIUnavailable("The model took too long to respond.") from exc
    except requests.RequestException as exc:
        raise AIUnavailable(f"Could not reach the model provider: {exc}") from exc


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
VALID_CATEGORIES = {"dream", "target", "safe"}


def validate_plan(plan: dict, allowed_ids: set[int]) -> dict:
    """Make sure the model returned four real universities in the right bands.

    The model is instructed to pick only from the candidate list, but the
    frontend should never have to trust that, so it's checked here.
    """
    if not isinstance(plan, dict):
        raise AIUnavailable("Model response was not an object.")

    picks = plan.get("picks")
    if not isinstance(picks, list) or not picks:
        raise AIUnavailable("Model response contained no picks.")

    clean: list[dict] = []
    seen: set[int] = set()
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        try:
            uid = int(pick.get("id"))
        except (TypeError, ValueError):
            continue
        if uid not in allowed_ids or uid in seen:
            log.warning("Dropping pick %s: not in the candidate shortlist.", uid)
            continue
        seen.add(uid)
        category = str(pick.get("category", "")).lower().strip()
        pick["category"] = category if category in VALID_CATEGORIES else "target"
        pick["id"] = uid
        try:
            pick["fit_score"] = max(0, min(100, int(round(float(pick.get("fit_score", 70))))))
        except (TypeError, ValueError):
            pick["fit_score"] = 70
        try:
            pick["admission_chance"] = max(0.01, min(0.99, float(pick.get("admission_chance", 0.4))))
        except (TypeError, ValueError):
            pick["admission_chance"] = 0.4
        for key in ("why", "risks"):
            value = pick.get(key)
            pick[key] = [str(v) for v in value][:4] if isinstance(value, list) else []
        clean.append(pick)

    if not clean:
        raise AIUnavailable("None of the model's picks were in the candidate list.")

    plan["picks"] = clean
    plan.setdefault("summary", "")
    plan.setdefault("comparison", {"columns": [], "rows": []})
    plan.setdefault("timeline", [])
    plan.setdefault("advice", {})
    return plan


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def select_universities(profile: StudentProfile, rows: list[dict]) -> tuple[dict, dict]:
    """Ask the model to build the four-school list.

    Returns (plan, meta). Raises AIUnavailable so the caller can fall back.
    """
    payload = candidate_payload(rows)
    user_prompt = build_user_prompt(profile, payload)

    started = time.monotonic()
    raw = call_model(SYSTEM_PROMPT, user_prompt)
    latency_ms = int((time.monotonic() - started) * 1000)

    plan = validate_plan(extract_json(raw), {row["id"] for row in payload})
    meta = {
        "engine": "ai",
        "model": settings.AI_MODEL,
        "provider": settings.AI_PROVIDER,
        "latency_ms": latency_ms,
        "candidates_considered": len(payload),
    }
    log.info("AI plan built in %sms from %s candidates.", latency_ms, len(payload))
    return plan, meta
