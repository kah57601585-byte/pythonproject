"""FastAPI server for the OPIc practice PWA.

Run:  uvicorn server:app --host 0.0.0.0 --port 8000   (from the opic_coach folder)
"""

from __future__ import annotations

import logging
import os
import random
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines) so no extra dependency is needed."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv(BASE_DIR / ".env")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

import coach
from questions import (
    LEVEL_INFO,
    LEVEL_TYPES,
    QUESTION_TYPES,
    TOPICS,
    Question,
    pick_question,
)

app = FastAPI(title="OPIc Coach")


class QuestionRequest(BaseModel):
    level: int = Field(3, ge=1, le=6)
    topics: list[str] = []
    exclude_ids: list[str] = []
    use_ai: bool = False


class FeedbackRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=6000)
    level: int = Field(3, ge=1, le=6)
    qtype: str | None = None
    duration_sec: float | None = Field(None, ge=0, le=1800)


@app.get("/api/meta")
def meta():
    return {
        "levels": {str(k): v | {"types": LEVEL_TYPES[k]} for k, v in LEVEL_INFO.items()},
        "topics": TOPICS,
        "question_types": QUESTION_TYPES,
        "model": coach.MODEL,
    }


@app.post("/api/question")
def question(req: QuestionRequest):
    q = pick_question(req.level, req.topics, req.exclude_ids)
    if req.use_ai:
        # Keep the bank's topic/type mix, but let the AI write a fresh question.
        try:
            text = coach.generate_question(req.level, q.topic, q.qtype)
        except coach.CoachError as e:
            raise HTTPException(status_code=502, detail=str(e))
        q = Question(id=f"ai-{random.randrange(10**8)}", topic=q.topic, qtype=q.qtype, text=text)
    return q.to_dict()


@app.post("/api/feedback")
def feedback(req: FeedbackRequest):
    if len(req.answer.split()) < 3:
        raise HTTPException(status_code=400, detail="답변이 너무 짧아요. 조금 더 길게 말해 주세요.")
    try:
        fb = coach.get_feedback(req.question, req.answer, req.level, req.qtype, req.duration_sec)
    except coach.CoachError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return fb.model_dump()


MAX_AUDIO_BYTES = 20 * 1024 * 1024  # OpenAI's upload limit is 25 MB


@app.post("/api/answer")
async def answer(
    audio: Annotated[UploadFile, File()],
    question: str = Form(..., min_length=1, max_length=1000),
    level: int = Form(3, ge=1, le=6),
    qtype: str | None = Form(None),
    duration_sec: float | None = Form(None, ge=0, le=1800),
    mode: Literal["english", "korean"] = Form("english"),
):
    """Recorded answer -> transcript -> feedback, in one request.

    mode="english": grade the English answer.
    mode="korean": the learner answered in Korean; show how to say it in English.
    """
    data = await audio.read()
    if len(data) < 1000:
        raise HTTPException(status_code=400, detail="녹음된 소리가 없어요. 마이크를 확인해 주세요.")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="녹음이 너무 길어요. 5분 이내로 답변해 주세요.")
    content_type = (audio.content_type or "audio/webm").split(";")[0]
    ext = {"audio/mp4": "mp4", "audio/ogg": "ogg", "audio/wav": "wav", "audio/mpeg": "mp3"}.get(content_type, "webm")
    try:
        transcript = await run_in_threadpool(
            coach.transcribe, data, f"answer.{ext}", content_type, "ko" if mode == "korean" else "en"
        )
    except coach.CoachError as e:
        raise HTTPException(status_code=502, detail=str(e))

    if mode == "korean":
        if len(transcript.replace(" ", "")) < 5:
            raise HTTPException(
                status_code=422,
                detail=f"한국어 답변이 거의 인식되지 않았어요. 마이크 가까이에서 다시 말해 주세요. (인식: \"{transcript}\")",
            )
        try:
            coaching = await run_in_threadpool(coach.coach_korean, question, transcript, level, qtype)
        except coach.CoachError as e:
            raise HTTPException(status_code=502, detail=str(e))
        return {"mode": "korean", "transcript": transcript, "coaching": coaching.model_dump()}

    if len(transcript.split()) < 3:
        raise HTTPException(
            status_code=422,
            detail=f"영어 답변이 거의 인식되지 않았어요. 마이크 가까이에서 다시 말해 주세요. (인식: \"{transcript}\")",
        )
    try:
        fb = await run_in_threadpool(coach.get_feedback, question, transcript, level, qtype, duration_sec)
    except coach.CoachError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"mode": "english", "transcript": transcript, "feedback": fb.model_dump()}


# Service worker must be served from the root so it can control the whole app.
@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(BASE_DIR / "static" / "sw.js", media_type="application/javascript")


app.mount("/", StaticFiles(directory=BASE_DIR / "static", html=True), name="static")
