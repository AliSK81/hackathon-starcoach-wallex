"""A thin client for any OpenAI-compatible chat API.

Uses only the standard library. Proxy settings come from the environment.
The API key goes only into the request header. It is never in a URL, an
error message, or a log.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

TIMEOUT = 120
RETRY_PAUSE = 5  # seconds before the one retry of a failed AI call


class LLMError(Exception):
    """The AI did not answer, or answered with something we can't read."""


@dataclass
class Reply:
    text: str  # the answer, without any <think> part
    model: str  # the model name the provider reports
    seconds: float
    reasoning: str = ""  # the model's own thinking, if the provider sends it
    usage: dict = field(default_factory=dict)  # token counts, as the provider sends them
    tool_calls: list = field(default_factory=list)  # tools the AI asks to call, as the provider sends them
    steps: list = field(default_factory=list)  # tools called before this answer: {tool, args, result}


@dataclass(frozen=True)
class Tool:
    """A function the AI may call. parameters is a JSON schema for its arguments."""
    description: str
    parameters: dict
    run: Callable[..., object]


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


def post(url: str, body: dict, api_key: str, timeout: float) -> dict:
    """POST a chat request and return the JSON reply.

    A server error (5xx), a lost connection or a timeout is tried once more after
    RETRY_PAUSE seconds: asking the AI again has no side effects. Other errors are not.
    """
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}", "User-Agent": "wx"},
    )
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                detail = error.read()[:300].decode(errors="replace")
            except OSError:
                detail = ""
            # A provider could echo the key back in an error. Never pass it on.
            failure = LLMError(f"chat: HTTP {error.code} {detail.replace(api_key, '***')}")
            if error.code < 500 or attempt == 2:
                raise failure from error
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == 2:
                raise LLMError(f"chat failed: {str(error).replace(api_key, '***')}") from error
        except json.JSONDecodeError as error:
            raise LLMError(f"chat: the reply is not JSON: {error}") from error
        time.sleep(RETRY_PAUSE)
    raise AssertionError("unreachable")


def chat(
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict],
    json_mode: bool = False,
    temperature: float = 0.0,
    timeout: float = TIMEOUT,
    tools: list[dict] | None = None,
) -> Reply:
    """Send one chat request and return the answer."""
    body = {"model": model, "messages": messages, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if tools:
        body["tools"] = tools
    started = time.monotonic()
    reply = post(base_url.rstrip("/") + "/chat/completions", body, api_key, timeout)
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
        tool_calls=message.get("tool_calls") or [],
    )


def chat_with_tools(base_url: str, model: str, api_key: str, messages: list[dict], tools: dict[str, Tool],
                    max_rounds: int = 4, timeout: float = TIMEOUT) -> Reply:
    """Let the AI call tools until it answers, at most max_rounds times.

    Each call and its result are kept in Reply.steps, so the log shows how the
    AI got to its answer. A tool that fails returns {"error": ...} to the AI.
    Time and tokens are added up over all rounds.
    """
    specs = [{"type": "function", "function": {"name": name, "description": t.description, "parameters": t.parameters}}
             for name, t in tools.items()]
    messages, steps, seconds, tokens, reasoning = list(messages), [], 0.0, 0, []
    for round_ in range(max_rounds + 1):
        last = round_ == max_rounds
        if last:
            messages.append({"role": "user", "content": "No more tools. Give your final answer now."})
        reply = chat(base_url, model, api_key, messages, timeout=timeout, tools=None if last else specs)
        seconds += reply.seconds
        tokens += reply.usage.get("total_tokens", 0)
        reasoning.append(reply.reasoning)
        if not reply.tool_calls or last:
            break
        messages.append({"role": "assistant", "content": reply.text, "tool_calls": reply.tool_calls})
        for call in reply.tool_calls:
            name = call.get("function", {}).get("name", "")
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
                result = tools[name].run(**args)
            except Exception as error:  # a bad call must not end the decision
                args, result = call.get("function", {}).get("arguments"), {"error": f"{type(error).__name__}: {error}"}
            steps.append({"tool": name, "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(result)})
    reply.seconds, reply.usage, reply.steps = round(seconds, 2), {"total_tokens": tokens}, steps
    reply.reasoning = "\n\n".join(r for r in reasoning if r)
    return reply
