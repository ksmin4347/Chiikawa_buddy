import asyncio
import io
import json
import logging
import threading
from uuid import uuid4

import httpx2
import pytest
from test_credentials import MemoryVault

from desktop_buddy.ai.client import ResponsesClient
from desktop_buddy.ai.config import DEFAULT_MODEL, MAX_RESPONSE_BYTES, validate_model
from desktop_buddy.ai.http_transport import OpenAITransport
from desktop_buddy.characters.ai_persona import format_reply, instructions
from desktop_buddy.models.online import OnlineError, OnlineRequest


def reply(text="테스트 답변", **changes):
    result = {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "model": DEFAULT_MODEL,
        "status": "completed",
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": {"input_tokens": 12, "output_tokens": 9, "total_tokens": 21},
    }
    return dict(result, **changes)


def run_client(handler, request=None, vault=None):
    vault = vault or MemoryVault()
    if vault.value is None:
        vault.value = "not-a-real-key-" + uuid4().hex
    client = ResponsesClient(lambda: httpx2.MockTransport(handler))
    request = request or OnlineRequest("qa", "chat", DEFAULT_MODEL, "질문 원문", "hachiware")
    return asyncio.run(client.run(vault, request, threading.Event()))


def test_request_is_stateless_minimal_and_ignores_environment_routing(monkeypatch, caplog):
    vault = MemoryVault()
    vault.value = "not-a-real-key-" + uuid4().hex
    monkeypatch.setenv("OPENAI_BASE_URL", "https://invalid.example")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-use-environment-key")
    monkeypatch.setenv("OPENAI_ORG_ID", "private-org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "private-project")
    observed = []

    def handler(request):
        observed.append(request)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer " + vault.value
        assert "openai-organization" not in request.headers
        assert "openai-project" not in request.headers
        body = json.loads(request.content)
        assert body["input"] == "질문 원문" and body["instructions"] == instructions("hachiware")
        assert body["store"] is False and body["background"] is False
        assert body["tools"] == [] and body["tool_choice"] == "none"
        assert not {"conversation", "previous_response_id", "metadata", "user"} & body.keys()
        return httpx2.Response(200, json=reply())

    with caplog.at_level(logging.DEBUG, logger="openai._base_client"):
        child = logging.getLogger("openai._base_client")
        direct = io.StringIO()
        direct_handler = logging.StreamHandler(direct)
        child.addHandler(direct_handler)
        child.disabled = False
        try:
            result = run_client(handler, vault=vault)
            child.debug(vault.value)
        finally:
            child.removeHandler(direct_handler)
    assert result.text == "테스트 답변" and result.input_tokens == 12
    assert result.output_tokens == 9 and len(observed) == 1
    assert vault.value not in caplog.text
    assert not direct.getvalue()


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "request"),
        (401, "auth"),
        (403, "permission"),
        (404, "model"),
        (429, "rate_limit"),
        (503, "server"),
    ],
)
def test_http_failure_has_no_retry_or_error_body_leak(status, code, caplog):
    canary = "not-a-real-error-secret-" + uuid4().hex
    calls = []

    def handler(request):
        calls.append(True)
        return httpx2.Response(status, json={"error": {"message": canary}})

    with pytest.raises(OnlineError) as caught:
        run_client(handler)
    assert caught.value.code == code and calls == [True]
    assert canary not in str(caught.value) and canary not in caplog.text


@pytest.mark.parametrize(
    "error,code", [(httpx2.ReadTimeout, "timeout"), (httpx2.ConnectError, "network")]
)
def test_connection_errors_are_sanitized(error, code):
    def handler(request):
        raise error("must not leak transport detail", request=request)

    with pytest.raises(OnlineError) as caught:
        run_client(handler)
    assert caught.value.code == code


@pytest.mark.parametrize(
    "change",
    [
        {"status": "incomplete"},
        {"output": []},
        {
            "output": [
                {"type": "function_call", "name": "delete_all", "arguments": "{}", "call_id": "x"}
            ]
        },
        {
            "output": [
                {
                    "type": "message",
                    "id": "r",
                    "role": "assistant",
                    "content": [{"type": "refusal", "refusal": "no"}],
                }
            ]
        },
    ],
)
def test_incomplete_empty_tool_and_refusal_outputs_are_not_accepted(change):
    with pytest.raises(OnlineError):
        run_client(lambda _: httpx2.Response(200, json=reply(**change)))


def test_exact_credential_echo_is_blocked_even_without_recognized_key_prefix():
    vault = MemoryVault()
    vault.value = "opaque-secret-" + uuid4().hex
    with pytest.raises(OnlineError, match="sensitive"):
        run_client(lambda _: httpx2.Response(200, json=reply(vault.value)), vault=vault)


def test_own_credential_in_input_is_blocked_before_http():
    vault = MemoryVault()
    vault.value = "opaque-secret-" + uuid4().hex
    calls = []
    request = OnlineRequest("qa", "chat", DEFAULT_MODEL, vault.value, "moru")
    with pytest.raises(OnlineError, match="sensitive"):
        run_client(lambda r: calls.append(r), request, vault)
    assert not calls


def test_technical_code_and_missing_usage_are_preserved():
    body = "api_key = os.environ['OPENAI_API_KEY']\nC:\\work\\print(x).py\n2026-11-10 08:00"
    result = run_client(lambda _: httpx2.Response(200, json=reply(body, usage=None)))
    assert result.text == body and result.input_tokens is None and result.output_tokens is None
    assert format_reply(body, "usagi", 0) == "야하!! (" + body + ")"
    assert format_reply("하아?!\n" + body, "usagi", 0) == "하아?! (" + body + ")"


def test_fixed_connection_probe_uses_no_persona_or_user_data():
    def handler(request):
        body = json.loads(request.content)
        assert body["input"] == "Connection test. Reply with OK only."
        assert body["instructions"] == "Reply with OK only." and body["max_output_tokens"] == 128
        return httpx2.Response(200, json=reply("OK"))

    request = OnlineRequest(
        "qa", "test", DEFAULT_MODEL, "Connection test. Reply with OK only.", "usagi"
    )
    assert run_client(handler, request).text == "OK"


def test_redirect_is_not_followed():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx2.Response(302, headers={"Location": "https://invalid.example"})

    with pytest.raises(OnlineError):
        run_client(handler)
    assert calls == ["https://api.openai.com/v1/responses"]


@pytest.mark.parametrize(
    "url",
    [
        "http://api.openai.com/v1/responses",
        "https://invalid.example/v1/responses",
        "https://api.openai.com:444/v1/responses",
        "https://api.openai.com/v1/files",
    ],
)
def test_transport_refuses_other_destinations_before_io(url):
    calls = []

    async def check():
        async with httpx2.AsyncClient(
            transport=OpenAITransport(httpx2.MockTransport(lambda request: calls.append(request)))
        ) as client:
            await client.post(url)

    with pytest.raises(OnlineError):
        asyncio.run(check())
    assert not calls


class HugeBody(httpx2.AsyncByteStream):
    async def __aiter__(self):
        yield b"x" * (MAX_RESPONSE_BYTES + 1)


def test_response_stream_is_bounded_before_json_parse():
    with pytest.raises(OnlineError):
        run_client(lambda _: httpx2.Response(200, stream=HugeBody()))


@pytest.mark.parametrize(
    "value", ["", "sk-" + "a" * 30, "https://evil.example", "bad model", "x" * 129]
)
def test_invalid_or_secret_like_model_id_is_rejected(value):
    with pytest.raises(ValueError):
        validate_model(value)
