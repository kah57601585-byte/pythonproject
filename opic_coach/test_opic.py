import random

import pytest
from fastapi.testclient import TestClient

import coach
import server
from questions import BANK, LEVEL_TYPES, TOPICS, candidates, pick_question


def test_bank_uses_known_topics_and_types():
    ids = [q.id for q in BANK]
    assert len(ids) == len(set(ids))
    all_types = {t for types in LEVEL_TYPES.values() for t in types}
    for q in BANK:
        assert q.topic in TOPICS
        assert q.qtype in all_types


@pytest.mark.parametrize("level", range(1, 7))
def test_every_level_has_questions_for_every_allowed_type(level):
    pool = candidates(level)
    assert {q.qtype for q in pool} == set(LEVEL_TYPES[level])


def test_low_level_never_gets_roleplay_or_issue():
    rng = random.Random(0)
    for _ in range(200):
        q = pick_question(1, ["music"], rng=rng)
        assert q.qtype in {"self_intro", "description", "routine"}
        assert q.topic in {"music", "general"}


def test_exclude_ids_avoids_repeats_until_pool_exhausted():
    rng = random.Random(1)
    pool_ids = {q.id for q in candidates(3, ["cafe"])}
    seen = []
    for _ in range(len(pool_ids)):
        seen.append(pick_question(3, ["cafe"], exclude_ids=seen, rng=rng).id)
    assert set(seen) == pool_ids
    # Once everything was asked, it still returns a question.
    assert pick_question(3, ["cafe"], exclude_ids=seen, rng=rng).id in pool_ids


@pytest.fixture
def client():
    return TestClient(server.app)


def test_meta_and_static(client):
    meta = client.get("/api/meta").json()
    assert set(meta["levels"]) == {"1", "2", "3", "4", "5", "6"}
    assert client.get("/").status_code == 200
    assert client.get("/sw.js").headers["content-type"].startswith("application/javascript")
    assert client.get("/manifest.webmanifest").status_code == 200


def test_question_endpoint(client):
    q = client.post("/api/question", json={"level": 5, "topics": ["travel"]}).json()
    assert q["qtype"] in LEVEL_TYPES[5]
    assert q["text"] and q["qtype_label"] and q["topic_label"]


def test_feedback_endpoint_uses_coach(client, monkeypatch):
    fake = coach.Feedback(
        estimated_grade="IM2", overall_comment_ko="좋아요", strengths_ko=["유창함"],
        corrections=[coach.Correction(original="I go yesterday", corrected="I went yesterday", explanation_ko="과거시제")],
        better_expressions=[], structure_feedback_ko="-", length_feedback_ko="-",
        model_answer="Well, ...", next_tip_ko="-",
    )
    calls = {}

    def fake_feedback(question, answer, level, qtype, duration):
        calls.update(question=question, answer=answer, level=level, qtype=qtype, duration=duration)
        return fake

    monkeypatch.setattr(coach, "get_feedback", fake_feedback)
    res = client.post("/api/feedback", json={
        "question": "Tell me about your home.", "answer": "I live in an apartment with my family.",
        "level": 4, "qtype": "description", "duration_sec": 42,
    })
    assert res.status_code == 200
    assert res.json()["estimated_grade"] == "IM2"
    assert calls["level"] == 4 and calls["duration"] == 42


def test_feedback_rejects_too_short_answer(client):
    res = client.post("/api/feedback", json={"question": "Q?", "answer": "yes", "level": 3})
    assert res.status_code == 400


def test_feedback_reports_coach_errors(client, monkeypatch):
    def boom(*a, **k):
        raise coach.CoachError("API 키가 올바르지 않아요.")

    monkeypatch.setattr(coach, "get_feedback", boom)
    res = client.post("/api/feedback", json={"question": "Q?", "answer": "I like music a lot.", "level": 3})
    assert res.status_code == 502
    assert "API 키" in res.json()["detail"]


def _fake_feedback():
    return coach.Feedback(
        estimated_grade="IH", overall_comment_ko="좋아요", strengths_ko=[], corrections=[],
        better_expressions=[], structure_feedback_ko="-", length_feedback_ko="-",
        model_answer="Well, ...", next_tip_ko="-",
    )


def test_answer_endpoint_transcribes_then_grades(client, monkeypatch):
    seen = {}

    def fake_transcribe(audio, filename, content_type, language="en"):
        seen.update(size=len(audio), filename=filename, content_type=content_type, language=language)
        return "I usually go to the park on weekends with my dog."

    def fake_feedback(question, answer, level, qtype, duration):
        seen.update(answer=answer, level=level, duration=duration)
        return _fake_feedback()

    monkeypatch.setattr(coach, "transcribe", fake_transcribe)
    monkeypatch.setattr(coach, "get_feedback", fake_feedback)
    res = client.post(
        "/api/answer",
        files={"audio": ("answer.webm", b"\x1a" * 5000, "audio/webm;codecs=opus")},
        data={"question": "Tell me about a park.", "level": "5", "qtype": "routine", "duration_sec": "61"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["transcript"].startswith("I usually go")
    assert body["feedback"]["estimated_grade"] == "IH"
    assert seen["filename"] == "answer.webm" and seen["content_type"] == "audio/webm"
    assert seen["language"] == "en" and body["mode"] == "english"
    assert seen["answer"] == body["transcript"] and seen["level"] == 5 and seen["duration"] == 61


def test_answer_rejects_empty_audio(client):
    res = client.post("/api/answer", files={"audio": ("a.webm", b"x", "audio/webm")}, data={"question": "Q?"})
    assert res.status_code == 400


def test_answer_rejects_when_nothing_recognized(client, monkeypatch):
    monkeypatch.setattr(coach, "transcribe", lambda *a: "um")
    called = []
    monkeypatch.setattr(coach, "get_feedback", lambda *a: called.append(1))
    res = client.post("/api/answer", files={"audio": ("a.webm", b"\x1a" * 5000, "audio/webm")}, data={"question": "Q?"})
    assert res.status_code == 422
    assert not called


def test_korean_mode_transcribes_korean_and_coaches(client, monkeypatch):
    seen = {}

    def fake_transcribe(audio, filename, content_type, language="en"):
        seen["language"] = language
        return "음 저는 주말에 보통 집 근처 공원에 가서 강아지랑 산책해요"

    def fake_coach(question, korean, level, qtype):
        seen.update(korean=korean, level=level)
        return coach.KoreanCoaching(
            summary_ko="주말 공원 산책", english_answer="Well, on weekends I usually go to a park near my house...",
            sentence_pairs=[coach.SentencePair(korean="주말에 공원에 가요", english="On weekends, I go to the park.")],
            key_expressions=[coach.KeyExpression(korean="~하는 편이에요", english="I tend to ~", note_ko="습관")],
            added_ideas_ko="-", tip_ko="-",
        )

    monkeypatch.setattr(coach, "transcribe", fake_transcribe)
    monkeypatch.setattr(coach, "coach_korean", fake_coach)
    monkeypatch.setattr(coach, "get_feedback", lambda *a: pytest.fail("should not grade Korean"))
    res = client.post(
        "/api/answer",
        files={"audio": ("a.webm", b"\x1a" * 5000, "audio/webm")},
        data={"question": "Tell me about a park.", "level": "4", "mode": "korean"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mode"] == "korean" and seen["language"] == "ko" and seen["level"] == 4
    assert body["coaching"]["english_answer"].startswith("Well")
    assert body["transcript"] == seen["korean"]


def test_korean_mode_rejects_empty_transcript(client, monkeypatch):
    monkeypatch.setattr(coach, "transcribe", lambda *a: "음")
    res = client.post("/api/answer", files={"audio": ("a.webm", b"\x1a" * 5000, "audio/webm")},
                      data={"question": "Q?", "mode": "korean"})
    assert res.status_code == 422


def test_rate_limit_messages_distinguish_quota_from_throttling():
    import httpx2
    import openai

    def err(code, msg):
        req = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
        resp = httpx2.Response(429, request=req)
        return openai.RateLimitError(msg, response=resp, body={"code": code, "message": msg})

    quota = coach._rate_limit_error(err("insufficient_quota", "You exceeded your current quota"))
    assert "크레딧" in str(quota) and "Billing" in str(quota)
    busy = coach._rate_limit_error(err("rate_limit_exceeded", "Rate limit reached"))
    assert "크레딧" not in str(busy)
