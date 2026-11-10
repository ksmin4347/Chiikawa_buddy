import asyncio
import logging

from desktop_buddy.ai.config import API_BASE, DEFAULT_MODEL, MAX_REPLY_CHARACTERS
from desktop_buddy.characters.ai_persona import instructions
from desktop_buddy.chat.parser import looks_secret
from desktop_buddy.models.online import OnlineError, OnlineRequest, OnlineResult
from desktop_buddy.security.credentials import CredentialError, validate_key


def quiet_network_logs() -> None:
    for name in ("openai", "httpx2", "httpcore2", "httpx", "httpcore"):
        logger = logging.getLogger(name)
        if not any(isinstance(handler, logging.NullHandler) for handler in logger.handlers):
            logger.addHandler(logging.NullHandler())
        logger.propagate = False


def token_count(value) -> int | None:
    return value if type(value) is int and 0 <= value <= 10**9 else None


class ResponsesClient:
    def __init__(self, transport_factory=None):
        self.transport_factory = transport_factory

    async def run(
        self, vault, request: OnlineRequest, cancelled, *, before_send=None
    ) -> OnlineResult:
        quiet_network_logs()
        try:
            import httpx2
            import openai

            from desktop_buddy.ai.http_transport import OpenAITransport
        except ImportError:
            raise OnlineError("setup") from None
        secret = None
        client = None
        http = None
        try:
            try:
                secret = vault.read()
                if secret is None:
                    raise OnlineError("key_missing")
                validate_key(secret)
            except CredentialError:
                raise OnlineError("key_store") from None
            if cancelled.is_set():
                raise asyncio.CancelledError
            if secret in request.text or secret in request.model:
                raise OnlineError("sensitive")
            if before_send is not None:
                await before_send()
            if cancelled.is_set():
                raise asyncio.CancelledError
            transport = OpenAITransport(
                self.transport_factory() if self.transport_factory is not None else None
            )
            http = httpx2.AsyncClient(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx2.Timeout(60, connect=10),
            )
            client = openai.AsyncOpenAI(
                api_key=secret,
                base_url=API_BASE,
                max_retries=0,
                http_client=http,
                admin_api_key="",
                organization="",
                project="",
                webhook_secret="",
            )
            if cancelled.is_set():
                raise asyncio.CancelledError
            options = {"reasoning": {"effort": "none"}} if request.model == DEFAULT_MODEL else {}
            response = await client.responses.create(
                model=request.model,
                input=request.text,
                instructions="Reply with OK only."
                if request.kind == "test"
                else instructions(request.character_id),
                max_output_tokens=128 if request.kind == "test" else 2048,
                store=False,
                background=False,
                stream=False,
                tools=[],
                tool_choice="none",
                **options,
            )
            if response.status != "completed":
                raise OnlineError("incomplete")
            if any(item.type not in ("message", "reasoning") for item in response.output):
                raise OnlineError("response")
            if any(
                part.type == "refusal"
                for item in response.output
                if item.type == "message"
                for part in item.content
            ):
                raise OnlineError("refused")
            text = response.output_text
            if not isinstance(text, str) or not text.strip() or len(text) > MAX_REPLY_CHARACTERS:
                raise OnlineError("response")
            if secret in text or looks_secret(text, assignments=False):
                raise OnlineError("sensitive")
            usage = response.usage
            return OnlineResult(
                text=text,
                input_tokens=token_count(getattr(usage, "input_tokens", None)),
                output_tokens=token_count(getattr(usage, "output_tokens", None)),
            )
        except openai.APITimeoutError:
            raise OnlineError("timeout") from None
        except openai.APIStatusError as error:
            code = {401: "auth", 403: "permission", 404: "model", 429: "rate_limit"}.get(
                error.status_code, "server" if error.status_code >= 500 else "request"
            )
            raise OnlineError(code) from None
        except openai.APIConnectionError:
            raise OnlineError("network") from None
        finally:
            if client is not None:
                client.api_key = ""
                await client.close()
            elif http is not None:
                await http.aclose()
            secret = None
