"""OpenAI-powered OPIc coach: generates questions and gives feedback on answers."""

from __future__ import annotations

import logging
import os
from typing import Literal

import openai
from pydantic import BaseModel, Field

from questions import LEVEL_INFO, QUESTION_TYPES, TOPICS, clamp_level

MODEL = os.environ.get("OPIC_MODEL", "gpt-5.4-mini")
# Reasoning effort for reasoning models: "low" answers fastest; "medium"/"high" give deeper feedback.
# Leave empty for models that don't support it (it is retried without it automatically anyway).
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


class SentencePair(BaseModel):
    korean: str = Field(description="A chunk of what the learner said in Korean (cleaned up)")
    english: str = Field(description="How to say that chunk naturally in spoken English")


class KeyExpression(BaseModel):
    korean: str
    english: str
    note_ko: str = Field(description="Usage note in Korean")


class KoreanCoaching(BaseModel):
    summary_ko: str = Field(description="One-sentence summary in Korean of what the learner wanted to say")
    english_answer: str = Field(description="Full natural spoken English answer built from the learner's content")
    sentence_pairs: list[SentencePair]
    key_expressions: list[KeyExpression]
    added_ideas_ko: str = Field(description="What was added to make it a full OPIc answer, in Korean")
    tip_ko: str


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

SYSTEM_KOREAN = """You are an OPIc (Oral Proficiency Interview - computer) English speaking coach for Korean learners.
The learner heard an OPIc question but answered in KOREAN because they did not know how to say it in English.
Your job: show them how to say THEIR OWN ideas in natural spoken English so they can practice it.

Rules:
- The Korean comes from speech recognition: ignore recognition glitches, fillers (음, 어, 그러니까) and false starts.
- english_answer: a natural spoken-style answer to the question (with fillers like "Well," "You know," "I mean,") at the learner's TARGET level. Keep the learner's content and personal details; do not invent a different story. If their content is too short for a good OPIc answer, extend it with natural, plausible details that fit their story, and use an intro and a short wrap-up. About 100-160 words for IM targets, 150-220 for IH/AL. Use vocabulary and grammar a learner at that level can actually say.
- sentence_pairs: split what the learner said into 3-8 meaningful chunks, in order. korean = their chunk (cleaned up), english = how to say that chunk in spoken English (it should match the wording in english_answer).
- key_expressions: 3-6 useful expressions from the answer that Korean learners often can't produce (e.g. "~하는 편이에요" -> "I tend to ~"), with a short Korean note.
- added_ideas_ko: in Korean, briefly say what you added or changed to make it a complete OPIc answer (or say nothing was added).
- summary_ko and tip_ko in natural, friendly Korean. tip_ko: one concrete tip for saying this answer in English."""

SYSTEM_QUESTION = """You write OPIc-style English interview questions. Return only the question text the examiner would read aloud, in English, 1-3 sentences, in the style of the real OPIc test (e.g. "You indicated that you ... Tell me ..."). Combine multiple sub-questions where natural."""


class CoachError(RuntimeError):
    pass


log = logging.getLogger("opic_coach")


def _rate_limit_error(e: openai.RateLimitError) -> CoachError:
    """OpenAI uses HTTP 429 for both 'out of credits' and 'too many requests'; tell them apart."""
    log.warning("OpenAI 429: %s", e.message)
    body = e.body if isinstance(e.body, dict) else {}
    code = body.get("code") or (body.get("error") or {}).get("code") or getattr(e, "code", None)
    text = f"{code} {e.message}".lower()
    if "insufficient_quota" in text or "quota" in text or "billing" in text:
        return CoachError(
            "OpenAI 크레딧이 없어요. platform.openai.com → Settings → Billing 에서 크레딧을 충전해 주세요. "
            "(ChatGPT 구독과는 별개예요. 충전 후 몇 분 뒤에 적용돼요.)"
        )
    return CoachError("요청이 너무 많아요. 1분쯤 뒤에 다시 시도해 주세요.")


_client: openai.OpenAI | None = None


def get_client() -> openai.OpenAI:
    global _client
    if _client is None:
        _client = openai.OpenAI()  # reads OPENAI_API_KEY
    return _client


def _call(system: str, user: str, output_format: type[BaseModel], max_tokens: int, effort: str | None):
    kwargs = {}
    if effort:
        kwargs["reasoning_effort"] = effort
    return get_client().chat.completions.parse(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=output_format,
        max_completion_tokens=max_tokens,
        **kwargs,
    )


def _parse(system: str, user: str, output_format: type[BaseModel], max_tokens: int):
    try:
        try:
            completion = _call(system, user, output_format, max_tokens, EFFORT)
        except openai.BadRequestError as e:
            # Non-reasoning models reject reasoning_effort; retry without it.
            if not EFFORT or "reasoning" not in str(e).lower():
                raise
            completion = _call(system, user, output_format, max_tokens, None)
    except openai.AuthenticationError as e:
        raise CoachError("API 키가 올바르지 않아요. .env 파일의 OPENAI_API_KEY를 확인해 주세요.") from e
    except openai.NotFoundError as e:
        raise CoachError(f"모델 '{MODEL}'을 찾을 수 없어요. .env 의 OPIC_MODEL 을 확인해 주세요.") from e
    except openai.RateLimitError as e:
        raise _rate_limit_error(e) from e
    except openai.APIConnectionError as e:
        raise CoachError("AI 서버에 연결할 수 없어요. PC의 인터넷 연결을 확인해 주세요.") from e
    except openai.LengthFinishReasonError as e:
        raise CoachError("AI 응답이 잘렸어요. 다시 시도해 주세요.") from e
    except openai.APIStatusError as e:
        log.warning("OpenAI error %s: %s", e.status_code, e.message)
        raise CoachError(f"AI 서버 오류 ({e.status_code}): {e.message}") from e

    message = completion.choices[0].message
    if message.refusal:
        raise CoachError("AI가 이 요청에 답하지 않았어요. 다른 답변으로 다시 시도해 주세요.")
    if message.parsed is None:
        raise CoachError("AI 응답을 읽을 수 없어요. 다시 시도해 주세요.")
    return message.parsed


STT_MODEL = os.environ.get("OPIC_STT_MODEL", "gpt-4o-mini-transcribe")
STT_FALLBACK_MODEL = "whisper-1"
# Ask for a verbatim transcript: grading needs the learner's real mistakes and fillers.
STT_PROMPTS = {
    "en": (
        "Transcribe exactly what the speaker says, word for word, including grammar mistakes, "
        "repetitions and filler words like um, uh, you know. Do not correct the English."
    ),
    "ko": "음, 그러니까, 저는 주말에 보통 집 근처 공원에 가요. 말한 그대로 받아 적어 주세요.",
}


def transcribe(audio: bytes, filename: str, content_type: str, language: str = "en") -> str:
    """Speech-to-text for a recorded answer. Falls back to whisper-1 if the configured model is unavailable."""
    models = [STT_MODEL] + ([STT_FALLBACK_MODEL] if STT_MODEL != STT_FALLBACK_MODEL else [])
    for i, model in enumerate(models):
        try:
            result = get_client().audio.transcriptions.create(
                model=model,
                file=(filename, audio, content_type),
                language=language,
                prompt=STT_PROMPTS.get(language, STT_PROMPTS["en"]),
            )
            return (result.text or "").strip()
        except (openai.NotFoundError, openai.BadRequestError) as e:
            model_problem = isinstance(e, openai.NotFoundError) or "model" in str(e).lower()
            if model_problem and i + 1 < len(models):
                continue
            raise CoachError(f"음성 인식에 실패했어요: {getattr(e, 'message', e)}") from e
        except openai.AuthenticationError as e:
            raise CoachError("API 키가 올바르지 않아요. .env 파일의 OPENAI_API_KEY를 확인해 주세요.") from e
        except openai.RateLimitError as e:
            raise _rate_limit_error(e) from e
        except openai.APIConnectionError as e:
            raise CoachError("AI 서버에 연결할 수 없어요. PC의 인터넷 연결을 확인해 주세요.") from e
        except openai.APIStatusError as e:
            raise CoachError(f"음성 인식 서버 오류 ({e.status_code}): {e.message}") from e
    raise CoachError("음성 인식 모델을 찾을 수 없어요.")


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


def coach_korean(question: str, korean: str, level: int, qtype: str | None = None) -> KoreanCoaching:
    level = clamp_level(level)
    info = LEVEL_INFO[level]
    user = "\n".join([
        f"Self-assessment level: {level} (target grade {info['target']})",
        f"Question type: {QUESTION_TYPES.get(qtype or '', 'unknown')}",
        f"Question: {question}",
        f"Learner's answer in Korean (speech-to-text):\n<answer>\n{korean}\n</answer>",
    ])
    return _parse(SYSTEM_KOREAN, user, KoreanCoaching, max_tokens=8000)


def generate_question(level: int, topic: str, qtype: str) -> str:
    level = clamp_level(level)
    user = (
        f"Topic: {TOPICS.get(topic, topic)} ({topic})\n"
        f"Question type: {QUESTION_TYPES.get(qtype, qtype)} ({qtype})\n"
        f"Learner level: {level} of 6 (target {LEVEL_INFO[level]['target']})\n"
        "Write one new question."
    )
    return _parse(SYSTEM_QUESTION, user, GeneratedQuestion, max_tokens=2000).text.strip()
