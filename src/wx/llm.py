"""A thin client for any OpenAI-compatible chat API.

Uses only the standard library. Proxy settings come from the environment.
The API key goes only into the request header. It is never in a URL, an
error message, or a log.
"""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

TIMEOUT = 120


class LLMError(Exception):
    """The AI did not answer, or answered with something we can't read."""


@dataclass
class Reply:
    text: str  # the answer, without any <think> part
    model: str  # the model name the provider reports
    seconds: float
    reasoning: str = ""  # the model's own thinking, if the provider sends it
    usage: dict = field(default_factory=dict)  # token counts, as the provider sends them


def strip_thinking(text: str) -> tuple[str, str]:
    """Split "<think>...</think>answer" into (answer, thinking).

    Some providers put the thinking inside the answer instead of in a
    separate field.
    """
    start, end = text.find("<think>"), text.find("</think>")
    if start == -1 or end < start:
        return text.strip(), ""
    return (text[:start] + text[end + len("</think>") :]).strip(), text[start + len("<think>") : end].strip()


def parse_json(text: str) -> dict:
    """The JSON object in an answer. Allows ``` fences and words around it."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise LLMError(f"no JSON object in the answer: {text[:200]!r}")
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise LLMError(f"bad JSON in the answer: {error}") from error
    if not isinstance(value, dict):
        raise LLMError("the answer is JSON but not an object")
    return value


def chat(
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict],
    json_mode: bool = False,
    temperature: float = 0.0,
    timeout: float = TIMEOUT,
) -> Reply:
    """Send one chat request and return the answer."""
    body = {"model": model, "messages": messages, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}", "User-Agent": "wx"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            reply = json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            detail = error.read()[:300].decode(errors="replace")
        except OSError:
            detail = ""
        # A provider could echo the key back in an error. Never pass it on.
        raise LLMError(f"chat: HTTP {error.code} {detail.replace(api_key, '***')}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise LLMError(f"chat failed: {str(error).replace(api_key, '***')}") from error
    seconds = time.monotonic() - started
    try:
        message = reply["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as error:
        raise LLMError(f"chat: unexpected reply {str(reply)[:200]}") from error
    text, thinking = strip_thinking(message.get("content") or "")
    return Reply(
        text=text,
        model=reply.get("model") or model,
        seconds=round(seconds, 2),
        reasoning=(message.get("reasoning_content") or thinking).strip(),
        usage=reply.get("usage") or {},
    )
