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
