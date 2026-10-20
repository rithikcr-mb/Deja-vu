"""Gemini provider boundary and deterministic local fake client."""

from __future__ import annotations

import logging
from typing import Any

from dejavu.services.ai_schemas import BattleSet, LessonGenerationResult

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
                    response_json_schema=LessonGenerationResult.model_json_schema(),
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

    def generate_battle(self, topic: str, lesson_cards: list[dict[str, str]]) -> str:
        from google import genai
        from google.genai import types

        card_text = "\n".join(
            f"{card['heading']}: {card['body']} (concept: {card['concept_label']}; "
            f"{card['concept_explanation']})"
            for card in lesson_cards
        )
        prompt = f"""Create a quiz battle for the topic {topic!r}, using this approved lesson:
{card_text}

Return exactly three rounds in order, with four multiple-choice questions per round.
Make round 1 introductory, round 2 applied, and round 3 more challenging. Every
question must have four distinct options, one correct answer index from 0 to 3,
an accurate concise explanation, and a weak-concept label and explanation grounded
in the lesson. Do not include HTML or information about the player's history."""
        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=BattleSet.model_json_schema(),
                    temperature=0.4,
                ),
            )
        except Exception as error:
            logger.warning("Gemini battle request failed (%s).", type(error).__name__)
            raise LessonProviderError("Gemini could not generate battle questions.") from error
        if not response.text:
            raise LessonProviderError("Gemini returned no battle questions.")
        return response.text


class FakeGeminiClient:
    """Deterministic fixture source; never makes network requests."""

    def __init__(self, result: Any | None = None, battle_result: Any | None = None) -> None:
        self.result = result
        self.battle_result = battle_result
        self.calls: list[str] = []
        self.battle_calls: list[str] = []

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

    def generate_battle(self, topic: str, lesson_cards: list[dict[str, str]]) -> Any:
        self.battle_calls.append(topic)
        if isinstance(self.battle_result, Exception):
            raise self.battle_result
        if self.battle_result is not None:
            return self.battle_result

        cards = lesson_cards or [
            {
                "concept_label": f"{topic} fundamentals",
                "concept_explanation": f"A core idea in {topic}.",
            }
        ]
        rounds = []
        for round_number in range(1, 4):
            questions = []
            for question_number in range(1, 5):
                card = cards[(round_number + question_number - 2) % len(cards)]
                correct_index = (round_number + question_number - 2) % 4
                options = [
                    f"Start by identifying the main purpose of {topic}.",
                    f"Break the process into steps and see how they connect.",
                    f"{card['concept_explanation']}",
                    f"Try a small example to see how the idea applies.",
                ]
                options[correct_index], options[2] = options[2], options[correct_index]
                questions.append(
                    {
                        "question": (
                            f"Round {round_number}, check {question_number}: "
                            f"which choice best explains {card['concept_label']}?"
                        ),
                        "options": options,
                        "correct_option_index": correct_index,
                        "explanation": card["concept_explanation"],
                        "concept_label": card["concept_label"],
                        "concept_explanation": card["concept_explanation"],
                    }
                )
            rounds.append({"round_number": round_number, "questions": questions})
        return {"rounds": rounds}
