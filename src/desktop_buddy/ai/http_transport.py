import httpx2

from desktop_buddy.ai.config import MAX_RESPONSE_BYTES
from desktop_buddy.models.online import OnlineError


class BoundedStream(httpx2.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        size = 0
        async for part in self.stream:
            size += len(part)
            if size > MAX_RESPONSE_BYTES:
                raise OnlineError("response")
            yield part

    async def aclose(self):
        await self.stream.aclose()


class OpenAITransport(httpx2.AsyncBaseTransport):
    def __init__(self, inner=None):
        self.inner = (
            inner
            if inner is not None
            else httpx2.AsyncHTTPTransport(verify=True, trust_env=False, retries=0)
        )

    async def handle_async_request(self, request):
        url = request.url
        if (
            url.scheme != "https"
            or url.host != "api.openai.com"
            or url.port not in (None, 443)
            or url.path != "/v1/responses"
            or url.query
            or request.method != "POST"
        ):
            raise OnlineError("network")
        for header in ("OpenAI-Organization", "OpenAI-Project"):
            request.headers.pop(header, None)
        request.headers["Accept-Encoding"] = "identity"
        response = await self.inner.handle_async_request(request)
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            await response.aclose()
            raise OnlineError("response")
        response.stream = BoundedStream(response.stream)
        return response

    async def aclose(self):
        await self.inner.aclose()
