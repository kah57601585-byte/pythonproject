"use strict";

// ---------- storage helpers (wrapped: storage can be unavailable) ----------
const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; }
    catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} },
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const settings = Object.assign(
  { level: 3, topics: ["home", "music", "movies", "cafe", "travel"], useAi: false, autoRec: true, rate: 1,
    micId: "", micLabel: "", survey: null },
  store.get("settings", {}),
);
let meta = null;
let current = null;          // current question object
let recentIds = store.get("recentIds", []);
const MAX_ANSWER_SEC = 300;  // auto-submit after 5 minutes

function saveSettings() { store.set("settings", settings); renderBadge(); }

function toast(msg, ms = 3500) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

async function api(path, body) {
  const isForm = body instanceof FormData;
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body && !isForm ? { "Content-Type": "application/json" } : {},
    body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : `서버 오류 (${res.status})`;
    throw new Error(detail);
  }
  return data;
}

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    if (tab.dataset.view !== "setup") stopMicTest();
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".view").forEach((v) =>
      v.classList.toggle("active", v.id === `view-${tab.dataset.view}`));
    window.scrollTo(0, 0);
    if (tab.dataset.view === "history") renderHistory();
    if (tab.dataset.view === "setup") refreshMics(false);
  });
});

// ======================================================================
// Microphone: device selection, level meter, recording
// ======================================================================
let audioCtx = null;

function ensureAudioCtx() {
  // Must be created/resumed during a user tap on Android.
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === "suspended") audioCtx.resume();
  return audioCtx;
}

function micSupported() {
  if (!window.isSecureContext) {
    toast("마이크는 HTTPS 주소에서만 동작해요. README의 Tailscale 설정을 확인하세요.", 6000);
    return false;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    toast("이 브라우저는 녹음을 지원하지 않아요. 최신 Chrome을 사용해 주세요.", 5000);
    return false;
  }
  return true;
}

async function openMic() {
  const base = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
  const wanted = settings.micId ? { ...base, deviceId: { exact: settings.micId } } : base;
  try {
    return await navigator.mediaDevices.getUserMedia({ audio: wanted });
  } catch (e) {
    if (settings.micId && (e.name === "OverconstrainedError" || e.name === "NotFoundError")) {
      toast("선택한 마이크를 찾을 수 없어서 기본 마이크를 사용해요.", 4000);
      settings.micId = ""; settings.micLabel = ""; saveSettings(); renderMicName();
      return navigator.mediaDevices.getUserMedia({ audio: base });
    }
    if (e.name === "NotAllowedError") {
      throw new Error("마이크 권한이 거부됐어요. 주소창의 자물쇠 → 권한 → 마이크를 허용해 주세요.");
    }
    if (e.name === "NotFoundError") throw new Error("연결된 마이크가 없어요.");
    if (e.name === "NotReadableError") throw new Error("다른 앱이 마이크를 사용 중이에요. 통화나 녹음 앱을 닫아 주세요.");
    throw e;
  }
}

function stopStream(stream) { stream?.getTracks().forEach((t) => t.stop()); }

/** Live level meter. Returns { stop(), stats } where stats.voiceMs counts time with voice. */
function startMeter(stream, fillEl, labelEl) {
  const ctx = ensureAudioCtx();
  const src = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  src.connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  const stats = { voiceMs: 0, peak: 0 };
  let raf = 0, last = performance.now(), hold = 0;

  const tick = (now) => {
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);
    const db = 20 * Math.log10(rms + 1e-8);
    const level = Math.max(0, Math.min(1, (db + 60) / 50)); // -60dB..-10dB -> 0..1
    const voice = level > 0.38;
    const dt = now - last; last = now;
    if (voice) { stats.voiceMs += dt; hold = 400; } else { hold = Math.max(0, hold - dt); }
    stats.peak = Math.max(stats.peak, level);
    fillEl.style.width = `${Math.round(level * 100)}%`;
    fillEl.classList.toggle("voice", hold > 0);
    labelEl.textContent = hold > 0 ? "🟢 목소리 감지" : "⚪ 조용함";
    labelEl.classList.toggle("on", hold > 0);
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);

  return {
    stats,
    stop() {
      cancelAnimationFrame(raf);
      try { src.disconnect(); } catch {}
      fillEl.style.width = "0%";
      fillEl.classList.remove("voice");
      labelEl.classList.remove("on");
    },
  };
}

function pickMimeType() {
  const types = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  return types.find((t) => MediaRecorder.isTypeSupported?.(t)) || "";
}

function renderMicName() {
  $("recMicName").textContent = `🎙️ 마이크: ${settings.micLabel || "기본 마이크"}`;
}

async function refreshMics(askPermission) {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  let devices = await navigator.mediaDevices.enumerateDevices();
  let inputs = devices.filter((d) => d.kind === "audioinput");
  // Device names stay hidden until mic permission is granted once.
  if (askPermission && inputs.every((d) => !d.label) && micSupported()) {
    try {
      stopStream(await navigator.mediaDevices.getUserMedia({ audio: true }));
      devices = await navigator.mediaDevices.enumerateDevices();
      inputs = devices.filter((d) => d.kind === "audioinput");
    } catch (e) {
      $("micStatus").textContent = e.name === "NotAllowedError"
        ? "마이크 권한이 거부됐어요. 주소창의 자물쇠 → 권한 → 마이크를 허용해 주세요." : `마이크 오류: ${e.message}`;
      return;
    }
  }
  const sel = $("micSelect");
  const options = [`<option value="">기본 마이크</option>`];
  inputs
    .filter((d) => d.deviceId && d.deviceId !== "default" && d.deviceId !== "communications")
    .forEach((d, i) => options.push(
      `<option value="${esc(d.deviceId)}">${esc(d.label || `마이크 ${i + 1}`)}</option>`));
  sel.innerHTML = options.join("");
  const exists = [...sel.options].some((o) => o.value === settings.micId);
  sel.value = exists ? settings.micId : "";
  if (!inputs.some((d) => d.label)) {
    $("micStatus").textContent = "마이크 이름을 보려면 '마이크 테스트'를 눌러 권한을 허용해 주세요.";
  }
}

$("micSelect").addEventListener("change", async (e) => {
  settings.micId = e.target.value;
  settings.micLabel = e.target.value ? e.target.selectedOptions[0].textContent : "";
  saveSettings(); renderMicName();
  if (micTest) { stopMicTest(); await startMicTest(); }
});
$("btnMicRefresh").addEventListener("click", () => refreshMics(true));
navigator.mediaDevices?.addEventListener?.("devicechange", () => refreshMics(false));

// ---- mic test (settings) ----
let micTest = null; // { stream, meter }

async function startMicTest() {
  if (!micSupported()) return;
  ensureAudioCtx();
  try {
    const stream = await openMic();
    micTest = { stream, meter: startMeter(stream, $("testMeter"), $("testVoice")) };
    $("btnMicTest").textContent = "테스트 정지";
    const label = stream.getAudioTracks()[0]?.label;
    $("micStatus").textContent = `사용 중: ${label || "기본 마이크"} — 말해 보세요. 초록불이 켜지면 정상이에요.`;
    refreshMics(false);
  } catch (e) {
    $("micStatus").textContent = e.message;
  }
}

function stopMicTest() {
  if (!micTest) return;
  micTest.meter.stop();
  stopStream(micTest.stream);
  micTest = null;
  $("btnMicTest").textContent = "마이크 테스트";
  $("testVoice").textContent = "⚪ 꺼짐";
}

$("btnMicTest").addEventListener("click", () => (micTest ? stopMicTest() : startMicTest()));

$("btnMicRecord").addEventListener("click", async () => {
  if (!micSupported()) return;
  stopMicTest();
  ensureAudioCtx();
  const btn = $("btnMicRecord");
  btn.disabled = true;
  let stream, meter;
  try {
    stream = await openMic();
    meter = startMeter(stream, $("testMeter"), $("testVoice"));
    const mime = pickMimeType();
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const chunks = [];
    rec.ondataavailable = (ev) => ev.data.size && chunks.push(ev.data);
    const done = new Promise((r) => (rec.onstop = r));
    rec.start();
    for (let s = 3; s > 0; s--) {
      btn.textContent = `녹음 중... ${s}`;
      await new Promise((r) => setTimeout(r, 1000));
    }
    rec.stop();
    await done;
    const audio = $("micPlayback");
    audio.src = URL.createObjectURL(new Blob(chunks, { type: rec.mimeType || "audio/webm" }));
    audio.classList.remove("hidden");
    audio.play().catch(() => {});
    $("micStatus").textContent = meter.stats.voiceMs > 300
      ? "✅ 목소리가 잘 들어왔어요. 재생해서 소리가 깨끗한지 확인해 보세요."
      : "⚠️ 목소리가 거의 감지되지 않았어요. 다른 마이크를 선택하거나 가까이에서 말해 보세요.";
  } catch (e) {
    $("micStatus").textContent = e.message;
  } finally {
    meter?.stop();
    stopStream(stream);
    $("testVoice").textContent = "⚪ 꺼짐";
    btn.disabled = false;
    btn.textContent = "3초 녹음 후 들어보기";
  }
});

// ======================================================================
// Setup view
// ======================================================================
function renderBadge() {
  const info = meta?.levels?.[settings.level];
  $("levelBadge").textContent = `Lv.${settings.level}${info ? " · " + info.target : ""}`;
}

function renderSetup() {
  $("levelList").innerHTML = Object.entries(meta.levels).map(([lv, info]) => `
    <div class="level-item ${+lv === settings.level ? "selected" : ""}" data-level="${lv}">
      <b>${lv}</b>
      <div><div>${esc(info.desc)}</div>
      <div class="muted small">목표 ${esc(info.target)} · ${info.types.map((t) => esc(meta.question_types[t])).join(", ")}</div></div>
    </div>`).join("");
  $("levelList").querySelectorAll(".level-item").forEach((el) =>
    el.addEventListener("click", () => {
      settings.level = +el.dataset.level; saveSettings(); renderSetup();
    }));

  renderSurvey();

  $("optAi").checked = settings.useAi;
  $("optAutoRec").checked = settings.autoRec;
  $("optRate").value = String(settings.rate);
}
$("optAi").addEventListener("change", (e) => { settings.useAi = e.target.checked; saveSettings(); });
$("optAutoRec").addEventListener("change", (e) => { settings.autoRec = e.target.checked; saveSettings(); });
$("optRate").addEventListener("change", (e) => { settings.rate = +e.target.value; saveSettings(); });

// ---------- Background Survey ----------
function defaultSurvey() {
  // single sections store the chosen option index; multi sections share one list of topic ids.
  const singles = { job: 0, student: 1, housing: 2 };
  const known = new Set(meta.survey.filter((s) => s.kind === "multi").flatMap((s) => s.options.map((o) => o.topic)));
  return { ...singles, picks: settings.topics.filter((t) => known.has(t)) };
}

function surveyTopics() {
  const sv = settings.survey;
  const topics = new Set();
  for (const sec of meta.survey) {
    if (sec.kind === "single") {
      const opt = sec.options[sv[sec.id]];
      if (opt?.topic) topics.add(opt.topic);
    }
  }
  sv.picks.forEach((t) => topics.add(t));
  return [...topics];
}

function renderSurvey() {
  if (!settings.survey) { settings.survey = defaultSurvey(); }
  const sv = settings.survey;
  $("surveyBox").innerHTML = meta.survey.map((sec) => {
    if (sec.kind === "single") {
      return `<div class="survey-sec"><h3>${esc(sec.title)}</h3><div class="opt-list">${sec.options.map((o, i) => `
        <label class="opt ${sv[sec.id] === i ? "on" : ""}">
          <input type="radio" name="sv-${sec.id}" data-sec="${sec.id}" value="${i}" ${sv[sec.id] === i ? "checked" : ""}>
          ${esc(o.label)}</label>`).join("")}</div></div>`;
    }
    return `<div class="survey-sec"><h3>${esc(sec.title)} <span class="muted small">(복수 선택)</span></h3>
      <div class="opt-grid">${sec.options.map((o) => {
        const key = o.topic || `none-${sec.id}`;
        const on = sv.picks.includes(key);
        return `<label class="opt ${on ? "on" : ""}"><input type="checkbox" value="${esc(key)}" ${on ? "checked" : ""}>${esc(o.label)}</label>`;
      }).join("")}</div></div>`;
  }).join("");

  $("surveyBox").querySelectorAll("input").forEach((inp) => inp.addEventListener("change", () => {
    if (inp.type === "radio") {
      sv[inp.dataset.sec] = +inp.value;
    } else {
      sv.picks = sv.picks.filter((t) => t !== inp.value);
      if (inp.checked) sv.picks.push(inp.value);
      // "운동을 전혀 하지 않음" excludes the sports in the same section, and vice versa.
      const sec = inp.closest(".survey-sec");
      if (inp.value.startsWith("none-") && inp.checked) {
        sec.querySelectorAll("input").forEach((o) => { if (o !== inp) sv.picks = sv.picks.filter((t) => t !== o.value); });
      } else if (inp.checked) {
        sec.querySelectorAll("input").forEach((o) => {
          if (o.value.startsWith("none-")) sv.picks = sv.picks.filter((t) => t !== o.value);
        });
      }
    }
    saveSurvey();
    renderSurvey();
  }));
  renderSurveyCount();
}

function renderSurveyCount() {
  const n = settings.survey.picks.filter((t) => !t.startsWith("none-")).length;
  const min = meta.survey_min_activities;
  const el = $("surveyCount");
  el.classList.toggle("warn", n < min);
  el.textContent = n < min
    ? `4~7번에서 ${n}개 선택 · 실제 시험은 ${min}개 이상 골라야 해요 (${min - n}개 더)`
    : `4~7번에서 ${n}개 선택 ✓ (실제 시험 기준 ${min}개 이상)`;
}

function saveSurvey() {
  settings.topics = surveyTopics().filter((t) => !t.startsWith("none-"));
  saveSettings();
}

// ---------- AI connection ----------
async function checkAi(deep) {
  try {
    return await api(`/api/health${deep ? "?deep=true" : ""}`);
  } catch (e) {
    return { ok: false, message: e.message };
  }
}

function showAiBanner(res) {
  const b = $("aiBanner");
  if (res.ok) { b.classList.add("hidden"); return; }
  b.innerHTML = `⚠️ <b>AI를 사용할 수 없어요</b><br>${esc(res.message)}<br>
    <span class="small">설정 → 🤖 AI 연결 확인으로 다시 확인할 수 있어요.</span>`;
  b.classList.remove("hidden");
}

$("btnAiCheck").addEventListener("click", async () => {
  const btn = $("btnAiCheck");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 확인 중...';
  const res = await checkAi(true);
  $("aiStatus").innerHTML = res.ok
    ? `<span class="ok-text">✅ ${esc(res.message)}</span>`
    : `<span class="bad-text">❌ ${esc(res.message)}</span>`;
  showAiBanner(res);
  btn.disabled = false;
  btn.textContent = "AI 연결 확인";
});

// ---------- text-to-speech ----------
function pickVoice() {
  const voices = speechSynthesis.getVoices().filter((v) => v.lang?.startsWith("en"));
  return voices.find((v) => v.lang === "en-US") || voices[0] || null;
}

function speak(text, onEnd) {
  if (!("speechSynthesis" in window)) { onEnd?.(); return; }
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "en-US";
  u.rate = settings.rate;
  const v = pickVoice();
  if (v) u.voice = v;
  u.onend = () => onEnd?.();
  u.onerror = () => onEnd?.();
  speechSynthesis.speak(u);
}

// ======================================================================
// Practice: question -> record -> submit on "답변 끝내기"
// ======================================================================
let session = null;   // active recording, see startRecording()
let submitting = false;

const LANG_STATUS = {
  en: "🔴 🇺🇸 영어로 답변 중 — 막히면 아래 한국어 버튼을 누르세요",
  ko: "🔴 🇰🇷 한국어로 말하는 중 — 막힌 부분을 한국어로 말하세요",
};

function fmt(sec) { return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`; }

function setRecButton(state) {
  const main = $("btnRec"), alt = $("btnRecKo");
  main.classList.remove("recording"); alt.classList.remove("recording", "ko-active");
  if (state === "idle") {
    main.disabled = alt.disabled = !current;
    alt.classList.remove("hidden");
    main.textContent = "🎤 영어로 답변 시작";
    alt.textContent = "🇰🇷 한국어로 말하기";
    $("segTrail").textContent = "";
    return;
  }
  if (state === "recording") {
    main.disabled = false;
    main.classList.add("recording");
    main.textContent = "⏹ 답변 끝내기 (제출)";
    alt.disabled = false;
    alt.classList.remove("hidden");
    const ko = session.lang === "ko";
    alt.classList.toggle("ko-active", ko);
    alt.textContent = ko ? "🇺🇸 다시 영어로 말하기" : "🇰🇷 막혔어요 · 한국어로 말하기";
    $("recStatus").textContent = LANG_STATUS[session.lang];
    renderTrail();
  }
  if (state === "submitting") {
    main.disabled = alt.disabled = true;
    alt.classList.add("hidden");
    main.innerHTML = '<span class="spinner"></span> 제출 중...';
  }
}

function renderTrail() {
  if (!session) return;
  const parts = session.segments.map((g) => ({ lang: g.lang, from: g.from, to: g.to }));
  parts.push({ lang: session.lang, from: session.segStart, to: session.seconds, live: true });
  if (parts.length < 2) { $("segTrail").textContent = ""; return; }
  $("segTrail").textContent = parts
    .map((p) => `${p.lang === "ko" ? "🇰🇷" : "🇺🇸"} ${fmt(p.from)}–${p.live ? "" : fmt(p.to)}`)
    .join("  →  ");
}

function renderTimer(sec) { $("timer").textContent = fmt(sec); }

function startSegment(lang) {
  const s = session;
  const mime = pickMimeType();
  const recorder = new MediaRecorder(s.stream, mime ? { mimeType: mime } : undefined);
  const chunks = [];
  recorder.ondataavailable = (ev) => ev.data.size && chunks.push(ev.data);
  recorder.start(1000);
  Object.assign(s, { recorder, chunks, lang, segStart: s.seconds });
}

async function endSegment() {
  const s = session;
  // Capture this segment's state first: a language switch replaces these fields right after.
  const { recorder, chunks, lang, segStart } = s;
  if (recorder.state === "inactive") return;  // already being stopped by another call
  const to = s.seconds;
  const done = new Promise((r) => recorder.addEventListener("stop", r, { once: true }));
  recorder.stop();
  await done;
  const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
  s.segments.push({ lang, blob, from: segStart, to });
}

async function startRecording(lang = "en") {
  if (session || submitting || !current) return;
  if (!micSupported()) return;
  speechSynthesis.cancel();
  stopMicTest();
  let stream;
  try {
    stream = await openMic();
  } catch (e) {
    toast(e.message, 6000);
    return;
  }
  session = { stream, segments: [], seconds: 0, switching: false,
              meter: startMeter(stream, $("recMeter"), $("recVoice")) };
  startSegment(lang);

  const label = stream.getAudioTracks()[0]?.label;
  if (label) $("recMicName").textContent = `🎙️ 마이크: ${label}`;
  setRecButton("recording");
  renderTimer(0);
  const s = session;
  s.timerId = setInterval(() => {
    s.seconds++;
    renderTimer(s.seconds);
    renderTrail();
    if (s.seconds >= MAX_ANSWER_SEC) { toast("5분이 지나서 자동으로 제출해요."); finishAnswer(); }
  }, 1000);
}

/** Switch between English and Korean in the middle of an answer. */
async function switchLanguage() {
  const s = session;
  if (!s || s.switching || submitting) return;
  s.switching = true;
  $("btnRecKo").disabled = true;
  await endSegment();
  if (session !== s) return;  // finished or cancelled meanwhile
  startSegment(s.lang === "en" ? "ko" : "en");
  s.switching = false;
  setRecButton("recording");
}

/** Stop recording. Returns { segments, seconds, voiceMs } or null if cancelled. */
async function stopRecording({ cancel = false } = {}) {
  const s = session;
  if (!s) return null;
  clearInterval(s.timerId);
  await endSegment();
  session = null;
  s.meter.stop();
  stopStream(s.stream);
  $("recVoice").textContent = "⚪ 대기";
  if (cancel) {
    $("recStatus").textContent = "녹음 대기";
    setRecButton("idle");
    return null;
  }
  // Drop near-empty segments from accidental double taps.
  const segs = s.segments.filter((x) => x.to - x.from >= 1 || x.blob.size > 4000);
  return { segments: segs.length ? segs : s.segments.slice(-1), seconds: s.seconds, voiceMs: s.meter.stats.voiceMs };
}

function blobName(blob, i) {
  const ext = blob.type.includes("mp4") ? "mp4" : blob.type.includes("ogg") ? "ogg" : "webm";
  return `part${i}.${ext}`;
}

async function finishAnswer() {
  if (!session || submitting || session.switching) return;
  submitting = true;
  setRecButton("submitting");
  $("recStatus").textContent = "답변 제출 중...";
  const rec = await stopRecording();
  if (!rec) { submitting = false; return; }

  if (rec.voiceMs < 500) {
    toast("목소리가 거의 감지되지 않았어요. 설정에서 마이크를 확인해 보세요.", 5000);
  }
  const langs = [...new Set(rec.segments.map((g) => g.lang))];
  const kind = langs.length > 1 ? "mixed" : langs[0] === "ko" ? "korean" : "english";
  const waiting = {
    english: "답변을 글로 옮기고 평가하고 있어요...",
    korean: "한국어를 듣고 영어 답변을 만들고 있어요...",
    mixed: "영어 부분은 평가하고, 한국어로 말한 부분은 영어로 바꾸고 있어요...",
  }[kind];
  $("feedback").innerHTML = `<div class="card"><span class="spinner"></span> ${waiting} (10~30초)</div>`;
  $("feedback").scrollIntoView({ behavior: "smooth" });

  const form = new FormData();
  form.append("question", current.text);
  form.append("level", String(settings.level));
  form.append("qtype", current.qtype);
  form.append("duration_sec", String(rec.seconds));
  let url = "/api/answer";
  if (kind === "mixed") {
    url = "/api/answer/mixed";
    rec.segments.forEach((g, i) => form.append("audio", g.blob, blobName(g.blob, i)));
    form.append("langs", rec.segments.map((g) => g.lang).join(","));
  } else {
    // Single language: one recording (segments of the same language can't happen without a switch).
    const g = rec.segments[0];
    form.append("audio", g.blob, blobName(g.blob, 0));
    form.append("mode", kind);
  }
  try {
    const res = await api(url, form);
    const entry = { at: Date.now(), mode: res.mode, question: current, answer: res.transcript,
                    seconds: rec.seconds, level: settings.level, fb: res.feedback, coaching: res.coaching,
                    mixed: res.mixed, segments: res.segments };
    $("feedback").innerHTML = renderResult(entry, true);
    $("recStatus").textContent = "제출 완료";
    saveHistory(entry);
  } catch (e) {
    $("feedback").innerHTML = `<div class="card">⚠️ ${esc(e.message)}
      <div class="row"><button class="btn primary" onclick="retrySameQuestion('en')">다시 말하기</button></div></div>`;
    $("recStatus").textContent = "제출 실패";
  } finally {
    submitting = false;
    setRecButton("idle");
  }
}

function retrySameQuestion(lang = "en") {
  $("feedback").innerHTML = "";
  window.scrollTo({ top: 0, behavior: "smooth" });
  startRecording(lang === "korean" ? "ko" : lang === "english" ? "en" : lang);
}

$("btnRec").addEventListener("click", () => {
  ensureAudioCtx();
  if (session) finishAnswer();
  else { $("feedback").innerHTML = ""; startRecording("en"); }
});
$("btnRecKo").addEventListener("click", () => {
  ensureAudioCtx();
  if (session) switchLanguage();
  else { $("feedback").innerHTML = ""; startRecording("ko"); }
});

$("btnNewQ").addEventListener("click", async () => {
  ensureAudioCtx();
  if (submitting) return;
  await stopRecording({ cancel: true });
  const btn = $("btnNewQ");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  try {
    current = await api("/api/question", {
      level: settings.level, topics: settings.topics, exclude_ids: recentIds, use_ai: settings.useAi,
    });
    recentIds = [current.id, ...recentIds.filter((id) => id !== current.id)].slice(0, 25);
    store.set("recentIds", recentIds);

    $("qType").textContent = current.qtype_label;
    $("qTopic").textContent = current.topic_label;
    $("qText").textContent = current.text;
    $("qText").classList.add("hidden");
    $("qPlaceholder").textContent = "질문을 듣고 답변하세요. 들리지 않으면 다시 듣기를 누르세요.";
    $("qPlaceholder").classList.remove("hidden");
    $("btnReplay").disabled = false;
    $("btnShowQ").disabled = false;
    $("feedback").innerHTML = "";
    $("recStatus").textContent = "🔊 질문을 듣는 중...";
    renderTimer(0);
    setRecButton("idle");

    speak(current.text, () => {
      if (settings.autoRec && !session && !submitting) startRecording();
      else if (!session) $("recStatus").textContent = "녹음 대기";
    });
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "새 질문";
  }
});
$("btnReplay").addEventListener("click", async () => {
  if (!current || submitting) return;
  // Re-listening restarts the answer, like the real test's replay before answering.
  await stopRecording({ cancel: true });
  speak(current.text, () => { if (settings.autoRec && !session && !submitting) startRecording(); });
});
$("btnShowQ").addEventListener("click", () => {
  $("qText").classList.toggle("hidden");
  $("qPlaceholder").classList.toggle("hidden", !$("qText").classList.contains("hidden"));
});

// ---------- results ----------
function speakButton(text, label) {
  return `<button class="btn" onclick="speak(${esc(JSON.stringify(text))})">${label}</button>
    <button class="btn ghost" onclick="speechSynthesis.cancel()">정지</button>`;
}

function renderResult(entry, live) {
  if (entry.mode === "mixed") return renderMixed(entry.mixed, entry.segments, live);
  if (entry.mode === "korean") return renderCoaching(entry.coaching, entry.answer, live);
  return renderFeedback(entry.fb, entry.answer, entry.seconds);
}

function renderCoaching(c, korean, live) {
  const pairs = c.sentence_pairs.map((p) => `
    <div class="pair"><div class="ko">${esc(p.korean)}</div><div class="en">${esc(p.english)}</div></div>`).join("");
  const exprs = c.key_expressions.map((k) => `
    <div class="corr"><div>${esc(k.korean)} → <span class="to">${esc(k.english)}</span></div>
    <div class="small muted">${esc(k.note_ko)}</div></div>`).join("");
  return `
  <div class="card">
    <span class="mode-chip">🇰🇷 → 🇺🇸 한국어 답변 코칭</span>
    <p>${esc(c.summary_ko)}</p>
    <div class="fb-section"><h3>🗣️ 내가 한국어로 한 말</h3><div class="transcript">${esc(korean)}</div></div>
    <div class="fb-section"><h3>🇺🇸 영어로 이렇게 말해 보세요</h3>
      <div class="model-answer">${esc(c.english_answer)}</div>
      <div class="row">${speakButton(c.english_answer, "🔊 영어 답변 듣기")}</div>
    </div>
    <div class="fb-section"><h3>🔁 문장별로 보기</h3>${pairs}</div>
    <div class="fb-section"><h3>💡 핵심 표현</h3>${exprs || '<p class="muted">없음</p>'}</div>
    <div class="fb-section"><h3>➕ 보충한 내용</h3><p>${esc(c.added_ideas_ko)}</p></div>
    <div class="fb-section"><h3>🎯 팁</h3><p>${esc(c.tip_ko)}</p></div>
    ${live ? `<div class="row"><button class="btn primary" onclick="retrySameQuestion('en')">🎤 이제 영어로 말해보기</button></div>` : ""}
  </div>`;
}

function renderMixed(m, segments, live) {
  const segHtml = (segments || []).map((g) => `
    <div class="seg ${g.lang}"><span class="seg-flag">${g.lang === "ko" ? "🇰🇷" : "🇺🇸"}</span>${esc(g.text)}</div>`).join("");
  const stuck = m.stuck_parts.map((p, i) => `
    <div class="pair"><div class="ko">🇰🇷 ${esc(p.korean)}</div>
      <div class="en">🇺🇸 ${esc(p.english)}</div>
      <div class="small muted">${esc(p.note_ko)}</div>
      <div class="row" style="margin-top:6px">${speakButton(p.english, "🔊 듣기")}</div></div>`).join("");
  const corrections = m.corrections.length
    ? m.corrections.map((c) => `
      <div class="corr"><div><span class="from">${esc(c.original)}</span> → <span class="to">${esc(c.corrected)}</span></div>
      <div class="small muted">${esc(c.explanation_ko)}</div></div>`).join("")
    : '<p class="muted">영어 부분에 큰 문법 오류가 없어요 👍</p>';
  const exprs = m.key_expressions.map((k) => `
    <div class="corr"><div>${esc(k.korean)} → <span class="to">${esc(k.english)}</span></div>
    <div class="small muted">${esc(k.note_ko)}</div></div>`).join("");
  return `
  <div class="card">
    <span class="mode-chip">🇺🇸 + 🇰🇷 막힌 부분 코칭</span>
    <div class="row" style="margin-top:8px"><span class="grade">${esc(m.estimated_grade)}</span>
      <span class="muted small">영어로 말한 부분 기준 예상 등급</span></div>
    <p>${esc(m.overall_comment_ko)}</p>
    <div class="fb-section"><h3>🗣️ 내가 말한 순서대로</h3>${segHtml}</div>
    <div class="fb-section"><h3>🧩 막힌 부분은 영어로 이렇게</h3>${stuck}</div>
    <div class="fb-section"><h3>🇺🇸 전체 답변을 영어로 이어 붙이면</h3>
      <div class="model-answer">${esc(m.full_answer_en)}</div>
      <div class="row">${speakButton(m.full_answer_en, "🔊 전체 답변 듣기")}</div></div>
    <div class="fb-section"><h3>✏️ 영어 부분 교정</h3>${corrections}</div>
    <div class="fb-section"><h3>💡 막히지 않게 도와줄 표현</h3>${exprs || '<p class="muted">없음</p>'}</div>
    <div class="fb-section"><h3>🎯 팁</h3><p>${esc(m.tip_ko)}</p></div>
    ${live ? `<div class="row"><button class="btn primary" onclick="retrySameQuestion('en')">🎤 처음부터 영어로 다시 말해보기</button></div>` : ""}
  </div>`;
}

// ---------- feedback ----------
function renderFeedback(fb, transcript, seconds) {
  const list = (items) => items.length ? `<ul>${items.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : '<p class="muted">없음</p>';
  const corrections = fb.corrections.length
    ? fb.corrections.map((c) => `
      <div class="corr"><div><span class="from">${esc(c.original)}</span> → <span class="to">${esc(c.corrected)}</span></div>
      <div class="small muted">${esc(c.explanation_ko)}</div></div>`).join("")
    : '<p class="muted">큰 문법 오류가 없어요 👍</p>';
  const better = fb.better_expressions.map((b) => `
      <div class="corr"><div>${esc(b.instead_of)} → <span class="to">${esc(b.try_this)}</span></div>
      <div class="small muted">${esc(b.note_ko)}</div></div>`).join("");
  const words = (transcript || "").trim().split(/\s+/).filter(Boolean).length;
  const mm = `${Math.floor((seconds || 0) / 60)}:${String((seconds || 0) % 60).padStart(2, "0")}`;
  return `
  <div class="card">
    <div class="row" style="margin-top:0"><span class="grade">${esc(fb.estimated_grade)}</span>
      <span class="muted small">예상 등급 (목표 ${esc(meta.levels[settings.level].target)})</span></div>
    <p>${esc(fb.overall_comment_ko)}</p>
    ${transcript ? `<div class="fb-section"><h3>🗣️ 인식된 내 답변 · ${words}단어 · ${mm}</h3>
      <div class="transcript">${esc(transcript)}</div></div>` : ""}
    <div class="fb-section"><h3>👍 잘한 점</h3>${list(fb.strengths_ko)}</div>
    <div class="fb-section"><h3>✏️ 문법 교정</h3>${corrections}</div>
    <div class="fb-section"><h3>💡 더 좋은 표현</h3>${better || '<p class="muted">없음</p>'}</div>
    <div class="fb-section"><h3>🧱 구성</h3><p>${esc(fb.structure_feedback_ko)}</p></div>
    <div class="fb-section"><h3>⏱️ 길이</h3><p>${esc(fb.length_feedback_ko)}</p></div>
    <div class="fb-section"><h3>📝 모범 답안</h3>
      <div class="model-answer">${esc(fb.model_answer)}</div>
      <div class="row">${speakButton(fb.model_answer, "🔊 모범 답안 듣기")}</div>
    </div>
    <div class="fb-section"><h3>🎯 다음 연습 포인트</h3><p>${esc(fb.next_tip_ko)}</p></div>
  </div>`;
}

// ---------- history ----------
function saveHistory(entry) {
  const hist = store.get("history", []);
  hist.unshift(entry);
  store.set("history", hist.slice(0, 50));
}

function renderHistory() {
  const hist = store.get("history", []);
  if (!hist.length) { $("historyList").innerHTML = '<p class="muted">아직 기록이 없어요.</p>'; return; }
  $("historyList").innerHTML = hist.map((h, i) => `
    <details class="hist-item">
      <summary><b>${h.mode === "korean" ? "🇰🇷→🇺🇸" : h.mode === "mixed" ? `${esc(h.mixed.estimated_grade)} 🇺🇸+🇰🇷` : esc(h.fb.estimated_grade)}</b> · ${esc(h.question.qtype_label)} · ${new Date(h.at).toLocaleString("ko-KR")}</summary>
      <p class="small"><b>Q.</b> ${esc(h.question.text)}</p>
      <div data-fb="${i}"></div>
    </details>`).join("");
  $("historyList").querySelectorAll("details").forEach((d, i) =>
    d.addEventListener("toggle", () => {
      const slot = d.querySelector("[data-fb]");
      if (d.open && !slot.innerHTML) slot.innerHTML = renderResult(hist[i], false);
    }));
}
$("btnClearHistory").addEventListener("click", () => {
  if (confirm("연습 기록을 모두 삭제할까요?")) { store.set("history", []); renderHistory(); }
});

// ---------- version / stale cache ----------
const PAGE_VERSION = document.querySelector('meta[name="app-version"]')?.content || "(구버전 페이지)";

/** If the browser shows an older page than the server runs, clear caches and reload once. */
async function reloadIfStale(serverVersion) {
  if (!serverVersion || serverVersion === PAGE_VERSION) return false;
  let tried = null;
  try { tried = sessionStorage.getItem("reloadedFor"); } catch {}
  if (tried === serverVersion) return false;  // already tried once; avoid a reload loop
  try { sessionStorage.setItem("reloadedFor", serverVersion); } catch {}
  try {
    const regs = await navigator.serviceWorker?.getRegistrations?.() || [];
    await Promise.all(regs.map((r) => r.unregister()));
    const keys = await caches?.keys?.() || [];
    await Promise.all(keys.map((k) => caches.delete(k)));
  } catch {}
  location.reload();
  return true;
}

function renderVersion() {
  $("verTag").textContent = `v${meta.release}`;
  const same = meta.version === PAGE_VERSION;
  $("appInfo").innerHTML = `서버 버전: <b>${esc(meta.version)}</b><br>화면 버전: <b>${esc(PAGE_VERSION)}</b> ${
    same ? '<span class="ok-text">✓ 최신</span>'
         : '<span class="bad-text">⚠️ 화면이 예전 버전이에요. Ctrl+Shift+R(PC) 또는 앱을 완전히 닫았다 열어 주세요.</span>'
  }<br>AI 모델: ${esc(meta.model)}`;
}

// ---------- init ----------
(async function init() {
  if ("speechSynthesis" in window) speechSynthesis.getVoices(); // warm up voice list
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  renderMicName();
  try {
    meta = await api("/api/meta");
    if (await reloadIfStale(meta.version)) return;
    renderVersion();
    renderSetup();
    saveSurvey();
    renderBadge();
    showAiBanner(await checkAi(false));
  } catch {
    toast("서버에 연결할 수 없어요. PC에서 서버가 켜져 있는지 확인하세요.", 6000);
  }
  refreshMics(false);
})();
