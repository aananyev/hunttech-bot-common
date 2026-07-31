"""AI module — OpenAI-compatible async HTTP client with retry logic."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

import httpx

from hunttech_bot_common.exceptions import (
    AIAuthenticationError,
    AIConnectionError,
    AIInvalidResponseError,
    AIRateLimitError,
    AISchemaValidationError,
    AITimeoutError,
)

T = TypeVar("T")


@dataclass
class AIResponse:
    """Response from an AI completion request."""

    content: str
    duration_ms: float
    usage: dict[str, int] = field(default_factory=dict)


def strip_json_markdown(text: str) -> str:
    """Extract JSON from markdown code blocks if present.

    Handles ```json ... ``` fences and ``` ... ``` blocks.
    Returns the cleaned JSON string.
    """
    text = text.strip()
    # Try ```json ... ```
    match = re.search(
        r"```(?:json)\s*\n?(.*?)```", text, re.DOTALL | re.IGNORECASE
    )
    if match:
        return match.group(1).strip()
    # Try ``` ... ``` (no language)
    match = re.search(r"```\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def parse_structured_response(
    raw_response: str,
    schema: type[T],
    allow_markdown_fence: bool = True,
) -> T:
    """Parse a structured JSON response from an LLM into a given schema type.

    Args:
        raw_response: The raw text response from the AI.
        schema: A dataclass type to parse into.
        allow_markdown_fence: If True, strip markdown code fences before parsing.

    Returns:
        An instance of the schema type.

    Raises:
        AISchemaValidationError: If parsing or validation fails.
    """
    try:
        text = raw_response
        if allow_markdown_fence:
            text = strip_json_markdown(raw_response)
        data = json.loads(text)
        # If schema is a dataclass, construct it from kwargs
        if hasattr(schema, "__dataclass_fields__"):
            return schema(**data)
        # Otherwise assume it's something like pydantic or just pass through
        return schema(data)  # type: ignore[call-arg]
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise AISchemaValidationError(
            f"Failed to parse response into {schema.__name__}: {exc}"
        ) from exc


class AIClient:
    """OpenAI-compatible async HTTP client for AI completions.

    Supports OpenRouter headers and retry logic with exponential backoff.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        provider: str = "openai",
        default_timeout: int = 120,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.default_timeout = default_timeout

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[T] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> AIResponse:
        """Send a completion request to the AI provider.

        Uses retry logic with exponential backoff for transient failures.

        Args:
            system_prompt: The system-level prompt.
            user_prompt: The user prompt/message.
            response_schema: Optional schema type to parse the response into.
            temperature: Optional temperature override.
            max_tokens: Optional max tokens override.
            timeout: Optional per-call timeout override (seconds).
                Falls back to default_timeout from constructor when None.

        Returns:
            An AIResponse with content, duration_ms, and usage.

        Raises:
            AIConnectionError: On connection failures.
            AIAuthenticationError: On auth failures.
            AIRateLimitError: On rate limiting.
            AITimeoutError: On timeout.
            AIInvalidResponseError: On invalid responses.
            AISchemaValidationError: On schema validation failures.
        """
        last_exception: Exception | None = None
        delay = 1.0
        max_attempts = 3

        for attempt in range(1, max_attempts + 1):
            try:
                return await self._do_complete(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
            except (AIConnectionError, AIRateLimitError, AITimeoutError) as exc:
                last_exception = exc
                if attempt < max_attempts:
                    await asyncio.sleep(delay)
                    delay *= 2  # exponential backoff
                else:
                    raise
            except (AIAuthenticationError, AIInvalidResponseError, AISchemaValidationError):
                # Non-retryable errors
                raise

    async def _do_complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> AIResponse:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        # OpenRouter headers
        if self.provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/hunttech"
            headers["X-Title"] = "HuntTech Bot"

        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        request_timeout = self.default_timeout if timeout is None else timeout
        start_time = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(request_timeout)) as client:
                response = await client.post(
                    self.endpoint,
                    headers=headers,
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise AITimeoutError(
                f"AI request timed out after {request_timeout}s"
            ) from exc
        except httpx.ConnectError as exc:
            raise AIConnectionError(
                f"Failed to connect to {self.endpoint}: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AIConnectionError(f"HTTP error during request: {exc}") from exc

        duration_ms = (time.monotonic() - start_time) * 1000

        if response.status_code == 401:
            raise AIAuthenticationError("Invalid API key or authentication failed")
        elif response.status_code == 429:
            raise AIRateLimitError("Rate limited by AI provider")
        elif response.status_code >= 500:
            raise AIConnectionError(
                f"AI provider returned {response.status_code}: {response.text[:200]}"
            )
        elif response.status_code != 200:
            raise AIInvalidResponseError(
                f"Unexpected status code {response.status_code}: {response.text[:200]}"
            )

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise AIInvalidResponseError(
                f"Invalid JSON in response: {exc}"
            ) from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise AIInvalidResponseError(
                f"Unexpected response structure: {exc}"
            ) from exc

        usage: dict[str, int] = data.get("usage", {})

        return AIResponse(content=content, duration_ms=duration_ms, usage=usage)


class MockAIClient:
    """Mock AI client for testing purposes.

    Returns a fixed response without making any HTTP calls.
    """

    def __init__(self, response_text: str = "mock response") -> None:
        self.response_text = response_text

    async def complete(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        response_schema: type[T] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> AIResponse:
        """Return a mock response immediately."""
        _ = system_prompt, user_prompt, temperature, max_tokens, timeout  # mark as used
        content = self.response_text
        if response_schema is not None:
            try:
                content = strip_json_markdown(self.response_text)
                data = json.loads(content)
                if hasattr(response_schema, "__dataclass_fields__"):
                    response_schema(**data)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                from hunttech_bot_common.exceptions import AISchemaValidationError
                raise AISchemaValidationError(
                    f"Mock response failed schema validation: {exc}"
                ) from exc
        return AIResponse(content=content, duration_ms=0.0, usage={})


__all__ = [
    "AIClient",
    "MockAIClient",
    "AIResponse",
    "parse_structured_response",
    "strip_json_markdown",
]
