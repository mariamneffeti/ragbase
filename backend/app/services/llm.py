from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import tiktoken
from groq import AsyncGroq, APIStatusError, APIConnectionError, GroqError

from app.core.config import settings

if TYPE_CHECKING:
    from app.services.vector_store import Match

logger = logging.getLogger(__name__)

_MAX_CONTEXT_MATCHES = 10

_CONTEXT_DELIMITER = "<<<CONTEXT_SEP>>>"

_FALLBACK_MESSAGE = (
    "I cannot find sufficient documentation in the workspace "
    "knowledge base to answer your request."
)

_MAX_CHUNK_TEXT_LENGTH = 2000  

_TOKENIZER = tiktoken.get_encoding("cl100k_base") # TODO: document this choice
_TOKEN_SAFETY_BUFFER = 2_000
_MODEL_MAX_TOKENS = 128_000

_SYSTEM_PROMPT_TEMPLATE = (
    "You are a multi-tenant corporate AI knowledge assistant. Be precise and concise.\n"
    "If the context does not contain sufficient facts to answer, state: '{fallback}'\n\n"
    "Workspace Context:\n{{context_str}}" 
)

_MAX_RETRIES = 3
_RETRY_BACKOFF = 1.5

_TRANSIENT_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


def _build_system_prompt_template() -> str:
    return _SYSTEM_PROMPT_TEMPLATE.replace("{fallback}", _FALLBACK_MESSAGE)

_COMPILED_TEMPLATE = _build_system_prompt_template()

class LLMServiceError(Exception):
    pass

class LLMService:
    def __init__(self) -> None:
        if not settings.GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY is missing from environment — cannot initialize LLMService."
            )
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY.get_secret_value())
        self.model = "llama-3.1-8b-instant"

    async def generate_rag_response(self, query: str, context_matches: list[Match]) -> str:
        query = query.strip()
        if not query:
            raise ValueError("Inference engine requires a non-empty user prompt string.")

        context_blocks = self._build_context_blocks(context_matches)

        if not context_blocks:
            if context_matches:
                logger.warning(
                    "All %d context match(es) had empty text — returning fallback.",
                    len(context_matches),
                )
            return _FALLBACK_MESSAGE

        selected_blocks = self._select_blocks_within_budget(context_blocks, query)
        context_str = "\n\n".join(selected_blocks)
        system_prompt = _COMPILED_TEMPLATE.replace("{context_str}", context_str)

        try:
            completion = await self._generate_with_retry(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                model=self.model,
                temperature=0.1,
                max_tokens=self._max_completion_tokens(),
            )
        except GroqError as exc:
            logger.error("Groq API error after retries: %s", exc)
            raise LLMServiceError("Upstream inference provider failed.") from exc
        except Exception as exc:
            logger.error("Unexpected error during response generation: %s", exc)
            raise LLMServiceError("An unexpected error occurred.") from exc

        if not completion.choices:
            raise LLMServiceError("Upstream returned no completion choices.")

        answer = completion.choices[0].message.content
        if not answer:
            raise LLMServiceError("Upstream response choice payload arrived empty.")

        return answer.strip()

    def _build_context_blocks(self, context_matches: list[Match]) -> list[str]:
        blocks: list[str] = []
        for i, match in enumerate(context_matches[:_MAX_CONTEXT_MATCHES]):
            metadata = match.get("metadata", {})
            title = metadata.get("title", "Untitled Context File")
            text = metadata.get("text", "").strip()

            if not text:
                continue
            sanitised = text.replace(_CONTEXT_DELIMITER, "")
            if len(sanitised) > _MAX_CHUNK_TEXT_LENGTH:
                sanitised = sanitised[:_MAX_CHUNK_TEXT_LENGTH] + "..."

            blocks.append(
                f"{_CONTEXT_DELIMITER} Document Record [{i + 1}]: {title} {_CONTEXT_DELIMITER}\n"
                f"{sanitised}"
            )
        return blocks

    def _select_blocks_within_budget(
        self, context_blocks: list[str], query: str
    ) -> list[str]:
        base_tokens = (
            self._count_tokens(_COMPILED_TEMPLATE.format(context_str=""))
            + self._count_tokens(query)
            + _TOKEN_SAFETY_BUFFER
        )
        max_context_tokens = _MODEL_MAX_TOKENS - base_tokens - self._max_completion_tokens()

        if max_context_tokens <= 0:
            raise LLMServiceError(
                "Token budget exhausted before any context could be added; "
                "the query or system prompt is too large."
            )

        selected: list[str] = []
        used_tokens = 0
        for block in context_blocks:
            block_tokens = self._count_tokens(block)
            if used_tokens + block_tokens > max_context_tokens:
                break
            selected.append(block)
            used_tokens += block_tokens

        return selected

    async def _generate_with_retry(
        self, messages: list[dict], **kwargs
    ) -> object:  
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return await self.client.chat.completions.create(
                    messages=messages, **kwargs
                )
            except (APIStatusError, APIConnectionError) as exc:
                status_code: int | None = (
                    exc.status_code if isinstance(exc, APIStatusError) else None
                )
                is_transient = (
                    status_code in _TRANSIENT_STATUS_CODES or status_code is None
                )

                if not is_transient or attempt == _MAX_RETRIES - 1:
                    raise

                last_exc = exc
                delay = _RETRY_BACKOFF ** attempt
                logger.warning(
                    "Transient Groq API error (attempt %d/%d, status %s, retry in %.1fs): %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    status_code,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

        raise LLMServiceError("Retry loop exited unexpectedly.") from last_exc

    def _count_tokens(self, text: str) -> int:
        return len(_TOKENIZER.encode(text))

    def _max_completion_tokens(self) -> int:
        return getattr(settings, "LLM_MAX_TOKENS", None) or 2048