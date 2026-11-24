"""FastAPI server for the OPIc practice PWA.

Run:  uvicorn server:app --host 0.0.0.0 --port 8000   (from the opic_coach folder)
"""

from __future__ import annotations

import os
import random
from pathlib import Path

from fastapi import FastAPI, HTTPException
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


# Service worker must be served from the root so it can control the whole app.
@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(BASE_DIR / "static" / "sw.js", media_type="application/javascript")


app.mount("/", StaticFiles(directory=BASE_DIR / "static", html=True), name="static")
