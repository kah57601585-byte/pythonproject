"""Claude-powered OPIc coach: generates questions and gives feedback on answers."""

from __future__ import annotations

import os
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from questions import LEVEL_INFO, QUESTION_TYPES, TOPICS, clamp_level

MODEL = os.environ.get("OPIC_MODEL", "claude-opus-5-5")
# Feedback quality vs. speed. "low" answers fastest; raise to "medium"/"high" for deeper feedback.
EFFORT = os.environ.get("OPIC_EFFORT", "low")

Grade = Literal["NL", "NM", "NH", "IL", "IM1", "IM2", "IM3", "IH", "AL"]


class Correction(BaseModel):
    original: str = Field(description="The learner's exact phrase that has an error")
    corrected: str = Field(description="The corrected English phrase")
    explanation_ko: str = Field(description="Short explanation in Korean")


class BetterExpression(BaseModel):
    instead_of: str = Field(description="A phrase the learner used that is correct but plain")
    try_this: str = Field(description="A more natural or advanced alternative")
    note_ko: str = Field(description="When/why to use it, in Korean")


class Feedback(BaseModel):
    estimated_grade: Grade
    overall_comment_ko: str
    strengths_ko: list[str]
    corrections: list[Correction]
    better_expressions: list[BetterExpression]
    structure_feedback_ko: str
    length_feedback_ko: str
    model_answer: str = Field(description="A model answer in English at the learner's target level")
    next_tip_ko: str


class GeneratedQuestion(BaseModel):
    text: str


SYSTEM_FEEDBACK = """You are an experienced OPIc (Oral Proficiency Interview - computer) English rater and coach for Korean learners.

Grade the learner's spoken answer (it comes from speech recognition, so ignore missing punctuation, capitalization and obvious recognition glitches; do not count those as grammar errors).

Grading guide (ACTFL/OPIc):
- NL/NM/NH: isolated words or memorized phrases.
- IL: simple sentences, little connection between them.
- IM1-IM3: creates with language on familiar topics, strings sentences together; IM3 is fluent with some errors.
- IH: paragraph-length answers, handles past/present/future and comparisons mostly well, occasional breakdowns.
- AL: well-organized paragraphs, consistent control of time frames, detailed narration and description, handles complications in role-plays.
Also consider whether the answer actually addresses every part of the question, and the answer length relative to the speaking time.

Feedback rules:
- Write every *_ko field in natural, friendly Korean. Keep English phrases in English.
- corrections: up to 5 of the most important real errors (grammar, word choice, tense). Empty list if none.
- better_expressions: 2-4 upgrades that would raise the grade (fillers, connectors, vivid vocabulary, idioms).
- structure_feedback_ko: comment on intro-body-conclusion, use of examples/details, and time-frame control.
- length_feedback_ko: comment on length and speaking time. Typical good answers are 1.5-2 minutes.
- model_answer: a natural spoken-style answer (with fillers like "Well," "You know,") at the learner's TARGET level, about 120-200 words for IM, 180-260 words for IH/AL. Base it on the learner's own content where possible.
- next_tip_ko: one concrete thing to practice next."""

SYSTEM_QUESTION = """You write OPIc-style English interview questions. Return only the question text the examiner would read aloud, in English, 1-3 sentences, in the style of the real OPIc test (e.g. "You indicated that you ... Tell me ..."). Combine multiple sub-questions where natural."""


class CoachError(RuntimeError):
    pass


_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _parse(system: str, user: str, output_format: type[BaseModel], max_tokens: int):
    try:
        response = get_client().beta.messages.parse(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": EFFORT},
            output_format=output_format,
            # Re-run on another model if the request is declined by a safety classifier.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise CoachError("API 키가 올바르지 않아요. .env 파일의 ANTHROPIC_API_KEY를 확인해 주세요.") from e
    except anthropic.RateLimitError as e:
        raise CoachError("요청이 너무 많아요. 잠시 후 다시 시도해 주세요.") from e
    except anthropic.APIConnectionError as e:
        raise CoachError("AI 서버에 연결할 수 없어요. PC의 인터넷 연결을 확인해 주세요.") from e
    except anthropic.APIStatusError as e:
        raise CoachError(f"AI 서버 오류 ({e.status_code}): {e.message}") from e

    if response.stop_reason == "refusal":
        raise CoachError("AI가 이 요청에 답하지 않았어요. 다른 답변으로 다시 시도해 주세요.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise CoachError("AI 응답이 잘렸어요. 다시 시도해 주세요.")
    return response.parsed_output


def get_feedback(question: str, answer: str, level: int, qtype: str | None = None,
                 duration_sec: float | None = None) -> Feedback:
    level = clamp_level(level)
    info = LEVEL_INFO[level]
    word_count = len(answer.split())
    parts = [
        f"Self-assessment level: {level} (target grade {info['target']})",
        f"Question type: {QUESTION_TYPES.get(qtype or '', 'unknown')}",
        f"Question: {question}",
        f"Answer word count: {word_count}",
    ]
    if duration_sec:
        parts.append(f"Speaking time: {int(duration_sec)} seconds")
    parts.append(f"Learner's answer (speech-to-text):\n<answer>\n{answer}\n</answer>")
    return _parse(SYSTEM_FEEDBACK, "\n".join(parts), Feedback, max_tokens=8000)


def generate_question(level: int, topic: str, qtype: str) -> str:
    level = clamp_level(level)
    user = (
        f"Topic: {TOPICS.get(topic, topic)} ({topic})\n"
        f"Question type: {QUESTION_TYPES.get(qtype, qtype)} ({qtype})\n"
        f"Learner level: {level} of 6 (target {LEVEL_INFO[level]['target']})\n"
        "Write one new question."
    )
    return _parse(SYSTEM_QUESTION, user, GeneratedQuestion, max_tokens=2000).text.strip()
