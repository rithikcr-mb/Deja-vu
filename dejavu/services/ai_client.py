"""Gemini provider boundary and deterministic local fake client."""

from __future__ import annotations

import logging
from typing import Any

from dejavu.services.ai_schemas import LessonGenerationResult

logger = logging.getLogger(__name__)


class LessonProviderError(RuntimeError):
    """The generation provider could not return a response."""


class LiveGenerationDisabled(LessonProviderError):
    """Live calls are intentionally disabled pending the learner's decision."""


class MissingApiKey(LessonProviderError):
    """No server-side Gemini API key is configured."""


class GeminiLessonClient:
    """Thin Google GenAI SDK adapter; it makes calls only when invoked."""

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def generate_lesson(self, topic: str) -> str:
        # Imported lazily so the local app shell and fake-client tests do not
        # initialize a network client or require provider credentials.
        from google import genai
        from google.genai import types

        prompt = f"""Teach this topic to a student in a short, accurate lesson: {topic!r}

Return the requested structured result. Use outcome=lesson and exactly three
cards with roles core_idea, how_it_works, and practical_example for any topic
that can reasonably be taught. A narrow, advanced, or unfamiliar topic is not
by itself unlearnable; explain uncertainty in the lesson when needed. Use
outcome=unlearnable_topic only if the input is nonsensical or no teachable
subject can reasonably be identified. Do not include HTML."""
        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=LessonGenerationResult.model_json_schema(),
                    temperature=0.4,
                ),
            )
        except Exception as error:  # provider SDK errors vary by release
            logger.warning(
                "Gemini lesson request failed (%s).", type(error).__name__
            )
            raise LessonProviderError("Gemini could not generate the lesson.") from error
        if not response.text:
            raise LessonProviderError("Gemini returned no lesson content.")
        return response.text


class FakeGeminiClient:
    """Deterministic fixture source; never makes network requests."""

    def __init__(self, result: Any | None = None) -> None:
        self.result = result
        self.calls: list[str] = []

    def generate_lesson(self, topic: str) -> Any:
        self.calls.append(topic)
        if self.result is not None:
            if isinstance(self.result, Exception):
                raise self.result
            return self.result
        return {
            "outcome": "lesson",
            "title": f"A short introduction to {topic}",
            "reason_code": None,
            "cards": [
                {
                    "role": "core_idea",
                    "heading": "The central idea",
                    "body": f"Start by identifying the main purpose of {topic}.",
                    "concept_label": f"{topic} fundamentals",
                    "concept_explanation": f"The basic idea behind {topic}.",
                },
                {
                    "role": "how_it_works",
                    "heading": "How it works",
                    "body": f"Break {topic} into its main steps and examine how they connect.",
                    "concept_label": f"{topic} process",
                    "concept_explanation": f"The main steps used in {topic}.",
                },
                {
                    "role": "practical_example",
                    "heading": "A practical example",
                    "body": f"Use a small example to see how an idea from {topic} applies.",
                    "concept_label": f"{topic} application",
                    "concept_explanation": f"Applying a basic idea from {topic}.",
                },
            ],
        }
