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


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def load_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env loader (KEY=VALUE lines). Values in the file win over old system variables."""
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for line in _read_text(path).splitlines():
        line = line.strip()
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'").strip()
        if value:
            os.environ[key] = value
            loaded[key] = value
    return loaded


def find_env_file() -> Path | None:
    # Windows Notepad often saves ".env" as ".env.txt" with the extension hidden.
    for name in (".env", ".env.txt", "env.txt", "env"):
        if (BASE_DIR / name).exists():
            return BASE_DIR / name
    return None


ENV_FILE = find_env_file()
if ENV_FILE:
    load_dotenv(ENV_FILE)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("opic_coach")


def api_key_problem() -> str | None:
    """Return a Korean explanation if the OpenAI key is obviously missing or malformed."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        where = f"{ENV_FILE.name} 파일" if ENV_FILE else ".env 파일(없음)"
        return f"OPENAI_API_KEY가 없어요. opic_coach 폴더의 {where}에 OPENAI_API_KEY=sk-... 를 넣고 서버를 다시 켜 주세요."
    if "여기에" in key or not key.startswith("sk-"):
        return "OPENAI_API_KEY 값이 올바르지 않아요. sk- 로 시작하는 실제 키를 붙여넣었는지 확인해 주세요."
    return None


def mask(key: str) -> str:
    return f"{key[:7]}...{key[-4:]}" if len(key) > 12 else "(짧음)"


log.info("환경 파일: %s", ENV_FILE or "없음 (opic_coach 폴더에 .env 를 만들어 주세요)")
if ENV_FILE and ENV_FILE.name != ".env":
    log.warning("'%s' 파일을 읽었어요. 이름을 '.env' 로 바꾸는 것을 권장해요.", ENV_FILE.name)
_problem = api_key_problem()
if _problem:
    log.warning("!!! %s", _problem)
else:
    log.info("OpenAI 키 확인: %s", mask(os.environ["OPENAI_API_KEY"]))

import coach
from questions import (
    LEVEL_INFO,
    LEVEL_TYPES,
    QUESTION_TYPES,
    SURVEY,
    SURVEY_MIN_ACTIVITIES,
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
        "survey": [
            {"id": sec["id"], "title": sec["title"], "kind": sec["kind"],
             "options": [{"topic": t, "label": label} for t, label, _ in sec["options"]]}
            for sec in SURVEY
        ],
        "survey_min_activities": SURVEY_MIN_ACTIVITIES,
        "question_types": QUESTION_TYPES,
        "model": coach.MODEL,
    }


@app.get("/api/health")
def health(deep: bool = False):
    """Check the API key. With deep=true, also check model access and credits with one tiny request."""
    problem = api_key_problem()
    if problem:
        return {"ok": False, "step": "key", "message": problem}
    if not deep:
        return {"ok": True, "message": f"API 키 있음 ({mask(os.environ['OPENAI_API_KEY'])})"}
    try:
        coach.ping()
    except coach.CoachError as e:
        return {"ok": False, "step": "openai", "message": str(e)}
    return {"ok": True, "message": f"AI 연결 정상 (모델: {coach.MODEL}, 키: {mask(os.environ['OPENAI_API_KEY'])})"}


@app.post("/api/question")
def question(req: QuestionRequest):
    q = pick_question(req.level, req.topics, req.exclude_ids)
    if req.use_ai and not api_key_problem():
        # Keep the bank's topic/type mix, but let the AI write a fresh question.
        try:
            text = coach.generate_question(req.level, q.topic, q.qtype)
        except coach.CoachError as e:
            raise HTTPException(status_code=502, detail=str(e))
        q = Question(id=f"ai-{random.randrange(10**8)}", topic=q.topic, qtype=q.qtype, text=text)
    return q.to_dict()


@app.post("/api/feedback")
def feedback(req: FeedbackRequest):
    if problem := api_key_problem():
        raise HTTPException(status_code=503, detail=problem)
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
    if problem := api_key_problem():
        raise HTTPException(status_code=503, detail=problem)
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


def _audio_name(upload: UploadFile, index: int) -> tuple[str, str]:
    content_type = (upload.content_type or "audio/webm").split(";")[0]
    ext = {"audio/mp4": "mp4", "audio/ogg": "ogg", "audio/wav": "wav", "audio/mpeg": "mp3"}.get(content_type, "webm")
    return f"part{index}.{ext}", content_type


@app.post("/api/answer/mixed")
async def answer_mixed(
    audio: Annotated[list[UploadFile], File()],
    langs: str = Form(..., description="Comma-separated language of each audio part, e.g. en,ko,en"),
    question: str = Form(..., min_length=1, max_length=1000),
    level: int = Form(3, ge=1, le=6),
    qtype: str | None = Form(None),
    duration_sec: float | None = Form(None, ge=0, le=1800),
):
    """English answer with Korean parts where the learner got stuck -> translate the Korean, grade the English."""
    if problem := api_key_problem():
        raise HTTPException(status_code=503, detail=problem)
    lang_list = [x.strip() for x in langs.split(",")]
    if len(lang_list) != len(audio) or any(lang not in ("en", "ko") for lang in lang_list):
        raise HTTPException(status_code=400, detail="음성 구간 정보가 올바르지 않아요.")
    if len(audio) > 20:
        raise HTTPException(status_code=400, detail="언어 전환이 너무 많아요.")

    datas = [await a.read() for a in audio]
    if sum(len(d) for d in datas) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="녹음이 너무 길어요. 5분 이내로 답변해 주세요.")

    segments: list[dict] = []
    for i, (upload, data, lang) in enumerate(zip(audio, datas, lang_list)):
        if len(data) < 1000:  # accidental tap: too short to contain speech
            continue
        name, content_type = _audio_name(upload, i)
        try:
            text = await run_in_threadpool(coach.transcribe, data, name, content_type, lang)
        except coach.CoachError as e:
            raise HTTPException(status_code=502, detail=str(e))
        if text.strip():
            segments.append({"lang": lang, "text": text.strip()})

    if not any(seg["lang"] == "ko" and len(seg["text"].replace(" ", "")) >= 2 for seg in segments):
        raise HTTPException(status_code=422, detail="한국어로 말한 부분이 인식되지 않았어요. 마이크 가까이에서 다시 말해 주세요.")
    try:
        result = await run_in_threadpool(
            coach.coach_mixed, question, [(seg["lang"], seg["text"]) for seg in segments], level, qtype, duration_sec
        )
    except coach.CoachError as e:
        raise HTTPException(status_code=502, detail=str(e))
    transcript = "\n".join(("🇰🇷 " if seg["lang"] == "ko" else "🇺🇸 ") + seg["text"] for seg in segments)
    return {"mode": "mixed", "segments": segments, "transcript": transcript, "mixed": result.model_dump()}


# Service worker must be served from the root so it can control the whole app.
@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(BASE_DIR / "static" / "sw.js", media_type="application/javascript")


class NoCacheStatic(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", NoCacheStatic(directory=BASE_DIR / "static", html=True), name="static")
