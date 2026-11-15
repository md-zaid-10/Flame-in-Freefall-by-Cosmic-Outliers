"""Pluggable language-model backend for the prose layer.

Three backends, same interface:

  groq       Groq's free-tier API. Used automatically when GROQ_API_KEY is set.
             Fast, needs nothing running locally, and is what rebuilds the
             cached demo answers.
  ollama     local models over http://localhost:11434 - no key, no network,
             no per-call cost. Used when there is no Groq key.
  anthropic  used only if ANTHROPIC_API_KEY is set.

Why a local 7B model is a defensible choice here, not a compromise:

The prose layer is the only part of this system that can invent anything, and
it is the only part we do not trust. rag.verify checks every number in a draft
verbatim against the retrieved sources and every citation against what was
actually retrieved, and blocks the draft if either fails. That gate is
mechanical, so it does not care how good the model is - a weaker model simply
gets blocked more often. Running on a local 7B is therefore a demonstration
that the grounding guarantee comes from the architecture, not from the model.

It also means the demo works with no internet, no API key and no rate limit,
which on a hackathon stage matters more than model quality.

NEVER put GROQ_API_KEY in anything the browser downloads. The published site
is static and its source is public, so a key shipped to the client is a key
given away. Groq runs server-side only: in frontend/serve.py, and in
frontend/build_cache.py when the cached answers are rebuilt.

Environment
  FIF_LLM           force one: "groq" | "ollama" | "anthropic".
                    Unset: Groq if a key exists, else ollama, else Anthropic.
  GROQ_API_KEY      Groq free-tier key (FIF_GROQ_KEY also accepted)
  FIF_GROQ_MODEL    pin a model id; unset picks the best the key can reach
  FIF_OLLAMA_MODEL  default "qwen2.5:7b"
  FIF_OLLAMA_HOST   default "http://localhost:11434"

Run:  python -m rag.llm           # report what is available, and smoke-test it
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

OLLAMA_HOST = os.environ.get("FIF_OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("FIF_OLLAMA_MODEL", "qwen2.5:7b")
ANTHROPIC_MODEL = os.environ.get("FIF_ANTHROPIC_MODEL", "claude-opus-5")

GROQ_HOST = os.environ.get("FIF_GROQ_HOST", "https://api.groq.com/openai/v1")
# Left empty on purpose: Groq's free tier rotates and retires model ids, so a
# hardcoded default goes stale and fails at demo time. pick_groq_model() asks
# the API what is actually available and chooses from GROQ_PREFERRED.
GROQ_MODEL = os.environ.get("FIF_GROQ_MODEL", "")
# Larger first: this task is constrained restatement with citations, and a
# bigger model gets blocked by rag.verify less often. This is a preference
# order, not a requirement - anything the key can reach is usable, and
# pick_groq_model() falls back to the listing when none of these are served.
GROQ_PREFERRED = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
    "allam-2-7b",
]
# Groq also serves speech, safety and embedding models. Those are filtered out
# by modality below; this catches any that still slip through by name.
GROQ_SKIP = ("guard", "whisper", "tts", "embed", "orpheus", "safeguard")
# Groq rejects urllib's default user-agent with 403, so always send one.
GROQ_UA = "flamescope-rag"

# Low temperature: we want the model to restate the sources, not to write.
TEMPERATURE = 0.1
NUM_CTX = 8192


class LLMUnavailable(RuntimeError):
    pass


# --------------------------------------------------------------------------
# ollama
# --------------------------------------------------------------------------

def ollama_models(host: str = OLLAMA_HOST, timeout: float = 5.0):
    """Installed models, or [] if the server is not running."""
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=timeout) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        return []


def ollama_available(host: str = OLLAMA_HOST) -> bool:
    return bool(ollama_models(host))


def pick_ollama_model(preferred: str = OLLAMA_MODEL, host: str = OLLAMA_HOST):
    """Use `preferred` if installed, else the best installed instruct model.

    Never downloads. Ordering favours models that follow instructions well at
    7-8B, since the task is constrained restatement with citations.
    """
    have = ollama_models(host)
    if not have:
        raise LLMUnavailable(f"ollama not reachable at {host}")
    if preferred in have:
        return preferred
    for cand in ("qwen2.5:7b", "llama3.1:8b", "mistral:7b"):
        if cand in have:
            return cand
    # Anything with a plausible size, largest last-resort first.
    tiny = [m for m in have if ":0." in m or ":1" in m]
    rest = [m for m in have if m not in tiny]
    if rest:
        return rest[0]
    raise LLMUnavailable(f"no usable model installed; have {have}")


def ollama_generate(prompt: str, model: str | None = None, system: str | None = None,
                    host: str = OLLAMA_HOST, max_tokens: int = 900,
                    timeout: float = 300.0) -> str:
    model = model or pick_ollama_model(host=host)
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": TEMPERATURE, "num_ctx": NUM_CTX,
                    "num_predict": max_tokens},
    }
    if system:
        body["system"] = system
    req = urllib.request.Request(
        f"{host}/api/generate", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r).get("response", "").strip()
    except urllib.error.URLError as e:
        raise LLMUnavailable(f"ollama request failed: {e}") from e


# --------------------------------------------------------------------------
# anthropic (optional)
# --------------------------------------------------------------------------

def groq_key() -> str | None:
    return os.environ.get("GROQ_API_KEY") or os.environ.get("FIF_GROQ_KEY")


def groq_models(timeout: float = 10.0):
    """Chat model ids this key can actually use, or [] if unreachable."""
    key = groq_key()
    if not key:
        return []
    req = urllib.request.Request(
        f"{GROQ_HOST}/models",
        headers={"Authorization": f"Bearer {key}", "User-Agent": GROQ_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r).get("data", [])
    except Exception:
        return []
    out = []
    for m in data:
        mid = m.get("id")
        if not mid or not m.get("active", True):
            continue
        # Keep only models that take text in and give text out.
        if "text" not in (m.get("output_modalities") or ["text"]):
            continue
        if "text" not in (m.get("input_modalities") or ["text"]):
            continue
        if any(skip in mid.lower() for skip in GROQ_SKIP):
            continue
        out.append(mid)
    return out


def groq_available() -> bool:
    return bool(groq_key())


def pick_groq_model(preferred: str = GROQ_MODEL) -> str:
    """An explicit choice if given, else the best model the key can reach.

    Never guesses a hardcoded id: Groq retires models, and a stale default
    fails with a 404 at exactly the wrong moment.
    """
    if preferred:
        return preferred
    have = groq_models()
    if not have:
        # Listing failed (offline, or the key cannot list). Fall back to the
        # first preference and let the request itself report the real error.
        return GROQ_PREFERRED[0]
    for cand in GROQ_PREFERRED:
        if cand in have:
            return cand
    return have[0]


def groq_generate(prompt: str, model: str | None = None, system: str | None = None,
                  max_tokens: int = 900, timeout: float = 120.0) -> str:
    """One chat completion from Groq's OpenAI-compatible endpoint.

    Uses urllib so the project keeps working with no extra dependency - the
    same choice the ollama backend makes.
    """
    key = groq_key()
    if not key:
        raise LLMUnavailable("GROQ_API_KEY is not set")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    chosen = model or pick_groq_model()
    body = {
        "model": chosen,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": max_tokens,
        "stream": False,
    }
    # gpt-oss models think before answering, and those reasoning tokens come
    # out of the SAME budget as the answer. Left alone, reasoning eats the
    # whole allowance and `content` comes back empty. This task is constrained
    # restatement, so ask for minimal reasoning and give the budget room.
    if "gpt-oss" in chosen:
        body["reasoning_effort"] = "low"
        body["max_tokens"] = max(max_tokens * 3, 1200)
    req = urllib.request.Request(
        f"{GROQ_HOST}/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": GROQ_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.load(e).get("error", {}).get("message", "")
        except Exception:
            pass
        if e.code == 401:
            raise LLMUnavailable("Groq rejected the API key (401).") from e
        if e.code == 429:
            raise LLMUnavailable(
                f"Groq rate limit hit (429). {detail}".strip()) from e
        if e.code == 404:
            raise LLMUnavailable(
                f"Groq does not serve model {body['model']!r} (404). "
                f"Available: {', '.join(groq_models()) or 'could not list'}") from e
        raise LLMUnavailable(f"Groq request failed ({e.code}). {detail}".strip()) from e
    except urllib.error.URLError as e:
        raise LLMUnavailable(f"Groq unreachable: {e}") from e

    choices = payload.get("choices") or []
    if not choices:
        raise LLMUnavailable("Groq returned no completion")
    choice = choices[0]
    text = (choice.get("message", {}).get("content") or "").strip()
    if not text:
        why = choice.get("finish_reason")
        raise LLMUnavailable(
            f"Groq returned an empty answer from {body['model']} "
            f"(finish_reason={why}). On a reasoning model this means the token "
            f"budget was spent thinking; raise max_tokens.")
    return text


def anthropic_generate(prompt: str, system: str | None = None,
                       max_tokens: int = 900) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
    try:
        import anthropic
    except ImportError as e:
        raise LLMUnavailable("anthropic package not installed") from e
    kwargs = {"model": ANTHROPIC_MODEL, "max_tokens": max_tokens,
              "temperature": TEMPERATURE,
              "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    msg = anthropic.Anthropic(api_key=key).messages.create(**kwargs)
    return "".join(b.text for b in msg.content if b.type == "text").strip()


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

def backend_name() -> str:
    """Which backend will actually be used, given the environment.

    FIF_LLM forces one. With nothing forced, Groq wins when a key is present -
    it is far faster than a local 7B and needs no model running - then a
    reachable ollama, then Anthropic.
    """
    want = os.environ.get("FIF_LLM", "").lower()
    if want == "groq" and groq_available():
        return "groq"
    if want == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if want == "ollama" and ollama_available():
        return "ollama"

    if groq_available():
        return "groq"
    if ollama_available():
        return "ollama"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "none"


def describe() -> dict:
    name = backend_name()
    d = {"backend": name}
    if name == "ollama":
        try:
            d["model"] = pick_ollama_model()
        except LLMUnavailable:
            d["model"] = None
        d["installed"] = ollama_models()
        d["host"] = OLLAMA_HOST
    elif name == "groq":
        d["model"] = pick_groq_model()
        d["available"] = groq_models()
        d["host"] = GROQ_HOST
    elif name == "anthropic":
        d["model"] = ANTHROPIC_MODEL
    return d


def generate(prompt: str, system: str | None = None, max_tokens: int = 900) -> str:
    name = backend_name()
    if name == "groq":
        return groq_generate(prompt, system=system, max_tokens=max_tokens)
    if name == "ollama":
        return ollama_generate(prompt, system=system, max_tokens=max_tokens)
    if name == "anthropic":
        return anthropic_generate(prompt, system=system, max_tokens=max_tokens)
    raise LLMUnavailable(
        "No language model available. Set GROQ_API_KEY (free tier), start "
        "ollama (no key needed), or set ANTHROPIC_API_KEY. The evidence "
        "ledger works without any of them.")


def available() -> bool:
    return backend_name() != "none"


# --------------------------------------------------------------------------
# smoke test
# --------------------------------------------------------------------------

def _main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    info = describe()
    print("backend  :", info["backend"])
    if info.get("model"):
        print("model    :", info["model"])
    if info.get("installed"):
        print("installed:", ", ".join(info["installed"]))
    if not available():
        print("\nMINI-GOAL 6 (local LLM backend): FAIL - no backend reachable")
        return 1

    # Does it obey a hard constraint? This is the behaviour the prose layer
    # depends on, and the reason rag.verify exists when it does not.
    out = generate(
        "Sources:\n[BASS] Flames self-extinguished at 0.21 oxygen mole fraction.\n\n"
        "Question: At what oxygen level did flames self-extinguish?\n"
        "Answer in one sentence, cite [BASS], and use only the source.",
        system="You restate NASA sources exactly. Never invent numbers.",
        max_tokens=120)
    print("\nresponse :", out.replace("\n", " ")[:300])

    from rag import verify
    chunks = [{"accession": "PSI-26", "acronym": "BASS", "also_in": [],
               "text": "Flames self-extinguished at 0.21 oxygen mole fraction."}]
    verdict, rep = verify.enforce(out, chunks)
    print("verdict  :", verdict,
          f"(numbers {rep['numbers']['supported']}/{rep['numbers']['numbers_checked']}"
          f" verbatim, {len(rep['citations']['invalid'])} bad citations)")

    ok = bool(out) and verdict in ("pass", "flag")
    print("\nMINI-GOAL 6 (local LLM backend):", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_main())
