"""Pluggable language-model backend for the prose layer.

Two backends, same interface:

  ollama     local models over http://localhost:11434 - no key, no network,
             no per-call cost. The default, and what the demo runs on.
  anthropic  used only if ANTHROPIC_API_KEY is set and FIF_LLM=anthropic.

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

Environment
  FIF_LLM         "ollama" (default) or "anthropic"
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
    """Which backend will actually be used, given the environment."""
    want = os.environ.get("FIF_LLM", "ollama").lower()
    if want == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
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
    elif name == "anthropic":
        d["model"] = ANTHROPIC_MODEL
    return d


def generate(prompt: str, system: str | None = None, max_tokens: int = 900) -> str:
    name = backend_name()
    if name == "ollama":
        return ollama_generate(prompt, system=system, max_tokens=max_tokens)
    if name == "anthropic":
        return anthropic_generate(prompt, system=system, max_tokens=max_tokens)
    raise LLMUnavailable(
        "No language model available. Start ollama (it needs no key) or set "
        "ANTHROPIC_API_KEY. The evidence ledger works without either.")


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
