import io
import json
import urllib.error
import urllib.request

import pytest

from wx import cli
from wx.config import Settings
from wx.llm import LLMError, Tool, chat, chat_with_tools, parse_json, strip_thinking

KEY = "sk-secret-key-value"
URL = "https://ai.example.com/v1/"


def fake_reply(content, reasoning=None):
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    body = {"model": "m1", "choices": [{"message": message}], "usage": {"total_tokens": 42}}
    return io.BytesIO(json.dumps(body).encode())


def test_request_shape_and_key_in_header_only(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"], seen["auth"] = request.full_url, request.get_header("Authorization")
        seen["body"] = json.loads(request.data)
        return fake_reply('{"action": "HOLD"}', reasoning="thinking")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    reply = chat(URL, "m1", KEY, [{"role": "user", "content": "hi"}], json_mode=True)
    assert seen["url"] == "https://ai.example.com/v1/chat/completions"
    assert seen["auth"] == f"Bearer {KEY}"
    assert KEY not in seen["url"] and KEY not in json.dumps(seen["body"])
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["temperature"] == 0.0
    assert (reply.text, reply.reasoning) == ('{"action": "HOLD"}', "thinking")
    assert (reply.model, reply.usage) == ("m1", {"total_tokens": 42})


def test_think_tags_are_split_from_the_answer():
    assert strip_thinking("<think>\nhmm\n</think>\n\n{}") == ("{}", "hmm")
    assert strip_thinking("  {}  ") == ("{}", "")


def test_think_tags_inside_content_become_reasoning(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: fake_reply("<think>why</think>{}"))
    reply = chat(URL, "m1", KEY, [])
    assert (reply.text, reply.reasoning) == ("{}", "why")


def test_parse_json_allows_fences_and_words():
    assert parse_json('Here:\n```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(LLMError):
        parse_json("no json here")
    with pytest.raises(LLMError):
        parse_json("{not json}")


def test_key_echoed_in_an_error_is_hidden(monkeypatch):
    def fake_urlopen(request, timeout):
        body = io.BytesIO(f'{{"error": "bad key Received={KEY}"}}'.encode())
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(LLMError) as caught:
        chat(URL, "m1", KEY, [])
    assert "HTTP 401" in str(caught.value)
    assert KEY not in str(caught.value)


def test_network_error_becomes_llm_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(LLMError):
        chat(URL, "m1", KEY, [])


def test_wx_ai_needs_the_settings(monkeypatch, capsys):
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: cls({"LLM_MODEL": "m1"})))
    assert cli.main(["ai"]) == 1
    assert "LLM_BASE_URL, LLM_API_KEY" in capsys.readouterr().out


def test_wx_ai_prints_the_answer_but_not_the_key(monkeypatch, capsys):
    settings = {"LLM_BASE_URL": URL, "LLM_MODEL": "m1", "LLM_API_KEY": KEY}
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: cls(settings)))
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: fake_reply('{"action": "HOLD"}', "why"))
    assert cli.main(["ai"]) == 0
    out = capsys.readouterr().out
    assert '"action": "HOLD"' in out and "Tokens: 42" in out
    assert KEY not in out


def tool_call(name, arguments, id_="c1"):
    return {"id": id_, "type": "function", "function": {"name": name, "arguments": arguments}}


def scripted(monkeypatch, messages_out):
    """Fake provider: answers with each message in turn, and records every request body."""
    bodies = []

    def fake_urlopen(request, timeout):
        bodies.append(json.loads(request.data))
        message = messages_out[len(bodies) - 1]
        body = {"model": "m1", "choices": [{"message": message}], "usage": {"total_tokens": 10}}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return bodies


def test_tools_are_called_and_logged(monkeypatch):
    bodies = scripted(monkeypatch, [
        {"content": None, "tool_calls": [tool_call("double", '{"x": 21}')]},
        {"content": '{"answer": 42}', "reasoning_content": "used the tool"},
    ])
    tools = {"double": Tool("double a number", {"type": "object"}, lambda x: {"value": 2 * x})}
    reply = chat_with_tools(URL, "m1", KEY, [{"role": "user", "content": "go"}], tools)
    assert parse_json(reply.text) == {"answer": 42}
    assert reply.steps == [{"tool": "double", "args": {"x": 21}, "result": {"value": 42}}]
    assert reply.usage == {"total_tokens": 20} and reply.reasoning == "used the tool"
    assert bodies[0]["tools"][0]["function"]["name"] == "double"
    assert bodies[1]["messages"][-1] == {"role": "tool", "tool_call_id": "c1", "content": '{"value": 42}'}


def test_a_failing_tool_tells_the_ai_and_goes_on(monkeypatch):
    scripted(monkeypatch, [
        {"content": None, "tool_calls": [tool_call("nope", "{}"), tool_call("boom", "{}", "c2")]},
        {"content": "{}"},
    ])
    tools = {"boom": Tool("fails", {"type": "object"}, lambda: 1 / 0)}
    reply = chat_with_tools(URL, "m1", KEY, [], tools)
    assert [s["result"]["error"].split(":")[0] for s in reply.steps] == ["KeyError", "ZeroDivisionError"]


def test_tool_rounds_are_limited(monkeypatch):
    endless = {"content": None, "tool_calls": [tool_call("ping", "{}")]}
    bodies = scripted(monkeypatch, [endless, endless, {"content": "{}"}])
    reply = chat_with_tools(URL, "m1", KEY, [], {"ping": Tool("ping", {"type": "object"}, lambda: "pong")},
                            max_rounds=2)
    assert len(reply.steps) == 2 and len(bodies) == 3
    assert "tools" not in bodies[2] and bodies[2]["messages"][-1]["content"].startswith("No more tools")
