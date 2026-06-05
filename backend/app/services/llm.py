from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from groq import AsyncGroq, GroqError

from app.core.config import settings

if TYPE_CHECKING:
    from app.services.vector_store import Match

logger = logging.getLogger(__name__)

_MAX_CONTEXT_MATCHES = 10

_CONTEXT_DELIMITER = "---"


class LLMServiceError(Exception):
    pass


class LLMService:
    def __init__(self) -> None:
        if not settings.GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY is missing from environment — cannot initialize LLMService."
            )

        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self.model = "llama-3.1-8b-instant"

    async def generate_rag_response(self, query: str, context_matches: list[Match]) -> str:
        query = query.strip()
        if not query:
            raise ValueError("Inference engine requires a non-empty user prompt string.")

        context_blocks: list[str] = []

        capped_matches = context_matches[:_MAX_CONTEXT_MATCHES]

        for i, match in enumerate(capped_matches):
            metadata = match.get("metadata", {})
            title = metadata.get("title", "Untitled Context File")
            text = metadata.get("text", "").strip()
            if text:
                sanitised_text = text.replace(_CONTEXT_DELIMITER, "")
                context_blocks.append(
                    f"{_CONTEXT_DELIMITER} Document Record [{i + 1}]: {title} {_CONTEXT_DELIMITER}\n"
                    f"{sanitised_text}"
                )

        if not context_blocks:
            return (
                "I cannot find sufficient documentation in the workspace "
                "knowledge base to answer your request."
            )

        context_str = "\n\n".join(context_blocks)

        system_prompt = (
            "You are a multi-tenant corporate AI knowledge assistant. Your directive "
            "is to answer the user's query accurately using ONLY the context blocks provided below.\n\n"
            "OPERATIONAL RULES:\n"
            "1. Ground your entire output within the provided context. Do not extrapolate "
            "or bring in outside knowledge.\n"
            "2. If the context does not contain sufficient facts to answer the query, state: "
            "'I cannot find sufficient documentation in the workspace knowledge base to answer your request.'\n"
            "3. Cite document titles when referencing facts or source materials.\n\n"
            f"Workspace Context:\n{context_str}"
        )

        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                temperature=0.1,
                max_tokens=1024,
            )

            if not completion.choices:
                raise LLMServiceError("Upstream returned no completion choices.")

            answer = completion.choices[0].message.content
            if not answer:
                raise LLMServiceError("Upstream response choice payload arrived empty.")

            return answer.strip()

        except GroqError as exc:
            logger.error("Groq API error during generation for model '%s'", self.model, exc_info=True)
            raise LLMServiceError("Upstream inference provider failed.") from exc
        except LLMServiceError:
            raise
        except Exception as exc:
            logger.error("Unexpected error inside LLMService.generate_rag_response", exc_info=True)
            raise LLMServiceError("An unexpected error occurred while generating the response.") from exc