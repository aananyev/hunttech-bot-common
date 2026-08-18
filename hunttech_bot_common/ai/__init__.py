"""AI module — OpenAI-compatible async HTTP client with retry logic."""

from __future__ import annotations

import asyncio
import json
import logging
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

from hunttech_bot_common.ai.usage import (
    UsageRecord,
    UsageTracker,
    estimate_cost,
    format_usage_report,
    usage_period_from_args,
)

logger = logging.getLogger(__name__)

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
        *,
        user_id: int | None = None,
        username: str | None = None,
        bot_name: str = "",
        usage_tracker: UsageTracker | None = None,
        ai_source: str = "",
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.default_timeout = default_timeout
        # ── Учёт обращений к нейросети (08.2026) ────────────────────
        # user_id/username — владелец активного ключа (чьи креды
        # использованы); usage_tracker — общий реестр всех ботов
        # (ai/usage.py); ai_source — «личные» | «админ (.env)».
        self.user_id = user_id
        self.username = username or ""
        self.bot_name = bot_name
        self.usage_tracker = usage_tracker
        self.ai_source = ai_source

    def _track_usage(
        self,
        status: str,
        response: AIResponse | None = None,
        task: str | None = None,
    ) -> None:
        """Записать обращение в UsageTracker (ok/error). Не роняет запрос."""
        if self.usage_tracker is None:
            return
        usage = (response.usage if response is not None else {}) or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or 0)
        record = UsageRecord(
            bot_name=self.bot_name,
            user_id=self.user_id,
            username=self.username or "",
            provider=self.provider,
            model=self.model,
            task=task or "unknown",
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_ms=(response.duration_ms if response is not None else 0.0),
            cost_usd=estimate_cost(self.model, prompt_tokens, completion_tokens),
            source=self.ai_source,
        )
        try:
            self.usage_tracker.append(record)
        except Exception as e:  # noqa: BLE001 — учёт не должен ронять запрос
            logger.warning("ai usage track failed: %s", e)

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[T] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        extra_body: dict[str, Any] | None = None,
        task: str | None = None,
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
            extra_body: Optional extra JSON body fields merged into the request
                (e.g. {"thinking": {"type": "disabled"}} for DeepSeek reasoning
                models, 08.2026).
            task: Бизнес-задача для учёта токенов (08.2026) — имя AI-функции
                (detect_intent, build_vacancy_description, …). Попадает в
                отчёт /usage в разрез «По задачам».

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
                response = await self._do_complete(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    extra_body=extra_body,
                )
                self._track_usage(status="ok", response=response, task=task)
                return response
            except (AIConnectionError, AIRateLimitError, AITimeoutError) as exc:
                last_exception = exc
                if attempt < max_attempts:
                    await asyncio.sleep(delay)
                    delay *= 2  # exponential backoff
                else:
                    self._track_usage(status="error", task=task)
                    raise
            except (AIAuthenticationError, AIInvalidResponseError, AISchemaValidationError):
                # Non-retryable errors
                self._track_usage(status="error", task=task)
                raise

    async def _do_complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        extra_body: dict[str, Any] | None = None,
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
        if extra_body:
            body.update(extra_body)

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
        extra_body: dict[str, Any] | None = None,
    ) -> AIResponse:
        """Return a mock response immediately."""
        _ = system_prompt, user_prompt, temperature, max_tokens, timeout, extra_body  # mark as used
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
    # ── Учёт обращений к нейросети (08.2026) ────────────────────────
    "UsageRecord",
    "UsageTracker",
    "estimate_cost",
    "format_usage_report",
    "usage_period_from_args",
]
