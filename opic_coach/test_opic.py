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
def client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-0000000000000000")
    return TestClient(server.app)


def test_missing_api_key_gives_clear_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    res = TestClient(server.app).post(
        "/api/answer", files={"audio": ("a.webm", b"\x1a" * 5000, "audio/webm")}, data={"question": "Q?"})
    assert res.status_code == 503
    assert "OPENAI_API_KEY" in res.json()["detail"]
    health = TestClient(server.app).get("/api/health").json()
    assert health["ok"] is False and health["step"] == "key"


def test_placeholder_key_is_rejected(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-여기에-키를-넣으세요")
    assert "올바르지" in server.api_key_problem()


def test_dotenv_handles_notepad_quirks(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-old-system-value")
    env = tmp_path / ".env"
    env.write_bytes("OPENAI_API_KEY = \"sk-from-file-1234\"\r\n# comment\r\n".encode("utf-16"))
    server.load_dotenv(env)
    assert server.os.environ["OPENAI_API_KEY"] == "sk-from-file-1234"


def test_health_reports_openai_errors(client, monkeypatch):
    def boom():
        raise coach.CoachError("OpenAI 크레딧이 없어요.")
    monkeypatch.setattr(coach, "ping", boom)
    res = client.get("/api/health?deep=true").json()
    assert client.get("/api/health").json()["ok"] is True
    assert res == {"ok": False, "step": "openai", "message": "OpenAI 크레딧이 없어요."}


def test_survey_topics_all_have_questions_at_every_level():
    from questions import SURVEY
    for sec in SURVEY:
        for topic, _label, _ in sec["options"]:
            if topic is None:
                continue
            for level in range(3, 7):
                assert any(q.topic == topic for q in candidates(level, [topic])), (topic, level)


def test_pick_covers_many_selected_topics():
    rng = random.Random(7)
    chosen = ["swimming", "pets", "golf", "museum", "cooking", "overseas_travel"]
    seen = {pick_question(4, chosen, rng=rng).topic for _ in range(300)}
    assert set(chosen) <= seen


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


def _fake_mixed():
    return coach.MixedCoaching(
        estimated_grade="IM1", overall_comment_ko="잘했어요",
        stuck_parts=[coach.StuckPart(korean="강아지랑 산책해요", english="I take a walk with my dog.", note_ko="take a walk")],
        full_answer_en="I usually go to the park. I take a walk with my dog.",
        corrections=[], key_expressions=[], tip_ko="-",
    )


def test_mixed_answer_transcribes_each_segment_in_its_language(client, monkeypatch):
    calls = []

    def fake_transcribe(audio, filename, content_type, language="en"):
        calls.append((filename, language))
        return {"en": "I usually go to the park", "ko": "강아지랑 산책해요"}[language]

    got = {}

    def fake_mixed(question, segments, level, qtype, duration):
        got.update(segments=segments, level=level, duration=duration)
        return _fake_mixed()

    monkeypatch.setattr(coach, "transcribe", fake_transcribe)
    monkeypatch.setattr(coach, "coach_mixed", fake_mixed)
    audio = b"\x1a" * 5000
    res = client.post(
        "/api/answer/mixed",
        files=[("audio", ("a.webm", audio, "audio/webm")), ("audio", ("b.webm", audio, "audio/webm")),
               ("audio", ("c.webm", b"x", "audio/webm"))],
        data={"langs": "en,ko,en", "question": "Tell me about a park.", "level": "4", "duration_sec": "50"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mode"] == "mixed"
    # the tiny third part (accidental tap) is skipped
    assert [c[1] for c in calls] == ["en", "ko"]
    assert got["segments"] == [("en", "I usually go to the park"), ("ko", "강아지랑 산책해요")]
    assert body["mixed"]["stuck_parts"][0]["english"] == "I take a walk with my dog."
    assert "🇰🇷 강아지랑 산책해요" in body["transcript"]


def test_mixed_answer_validates_langs(client):
    audio = b"\x1a" * 5000
    res = client.post("/api/answer/mixed", files=[("audio", ("a.webm", audio, "audio/webm"))],
                      data={"langs": "en,ko", "question": "Q?"})
    assert res.status_code == 400
    res = client.post("/api/answer/mixed", files=[("audio", ("a.webm", audio, "audio/webm"))],
                      data={"langs": "fr", "question": "Q?"})
    assert res.status_code == 400


def test_mixed_answer_needs_some_korean(client, monkeypatch):
    monkeypatch.setattr(coach, "transcribe", lambda a, f, c, language="en": "" if language == "ko" else "I like it")
    monkeypatch.setattr(coach, "coach_mixed", lambda *a: pytest.fail("should not coach"))
    audio = b"\x1a" * 5000
    res = client.post("/api/answer/mixed",
                      files=[("audio", ("a.webm", audio, "audio/webm")), ("audio", ("b.webm", audio, "audio/webm"))],
                      data={"langs": "en,ko", "question": "Q?"})
    assert res.status_code == 422


def test_index_page_carries_version_and_cache_busting(client):
    import version

    res = client.get("/")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    html = res.text
    assert f'<meta name="app-version" content="{version.APP_VERSION}">' in html
    assert f'src="app.js?v={version.BUILD}"' in html and f'href="style.css?v={version.BUILD}"' in html
    meta = client.get("/api/meta").json()
    assert meta["version"] == version.APP_VERSION


def test_version_hash_ignores_line_endings(tmp_path, monkeypatch):
    import version

    (tmp_path / "server.py").write_bytes(b"a\r\nb\r\n")
    monkeypatch.setattr(version, "_BASE", tmp_path)
    crlf = version._build_hash()
    (tmp_path / "server.py").write_bytes(b"a\nb\n")
    assert version._build_hash() == crlf


def test_windows_scripts_have_crlf_and_bom():
    from pathlib import Path

    base = Path(__file__).resolve().parent
    for name in ("run_windows.bat", "setup_windows.bat", "update_windows.bat", "update_windows.ps1"):
        data = (base / name).read_bytes()
        assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""), name
    assert (base / "update_windows.ps1").read_bytes().startswith(b"\xef\xbb\xbf")
