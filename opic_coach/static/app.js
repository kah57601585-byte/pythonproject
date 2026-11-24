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
  { level: 3, topics: ["home", "music", "movies", "cafe", "travel"], useAi: false, autoRec: true, rate: 1 },
  store.get("settings", {}),
);
let meta = null;
let current = null;          // current question object
let recentIds = store.get("recentIds", []);

function saveSettings() { store.set("settings", settings); renderBadge(); }

function toast(msg, ms = 3000) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
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
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".view").forEach((v) =>
      v.classList.toggle("active", v.id === `view-${tab.dataset.view}`));
    window.scrollTo(0, 0);
    if (tab.dataset.view === "history") renderHistory();
  });
});

// ---------- setup view ----------
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

  $("topicList").innerHTML = Object.entries(meta.topics)
    .filter(([k]) => k !== "general")
    .map(([k, label]) => `
      <label class="topic-item"><input type="checkbox" value="${k}" ${settings.topics.includes(k) ? "checked" : ""}> ${esc(label)}</label>`)
    .join("");
  $("topicList").querySelectorAll("input").forEach((cb) =>
    cb.addEventListener("change", () => {
      settings.topics = [...$("topicList").querySelectorAll("input:checked")].map((c) => c.value);
      saveSettings();
    }));

  $("optAi").checked = settings.useAi;
  $("optAutoRec").checked = settings.autoRec;
  $("optRate").value = String(settings.rate);
}
$("optAi").addEventListener("change", (e) => { settings.useAi = e.target.checked; saveSettings(); });
$("optAutoRec").addEventListener("change", (e) => { settings.autoRec = e.target.checked; saveSettings(); });
$("optRate").addEventListener("change", (e) => { settings.rate = +e.target.value; saveSettings(); });

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

// ---------- question ----------
$("btnNewQ").addEventListener("click", async () => {
  stopRecording();
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
    $("btnRec").disabled = false;
    $("answer").value = "";
    $("feedback").innerHTML = "";
    seconds = 0; renderTimer(); updateWordCount();

    speak(current.text, () => { if (settings.autoRec && !recording) startRecording(); });
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "새 질문";
  }
});
$("btnReplay").addEventListener("click", () => { if (current) { stopRecording(); speak(current.text); } });
$("btnShowQ").addEventListener("click", () => {
  $("qText").classList.toggle("hidden");
  $("qPlaceholder").classList.toggle("hidden", !$("qText").classList.contains("hidden"));
});

// ---------- speech recognition ----------
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recog = null;
let recording = false;
let committed = "";      // text from previous recognition sessions
let sessionFinals = [];  // final chunks of the current session
let seconds = 0;
let timerId = null;

function renderTimer() {
  $("timer").textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
function updateWordCount() {
  const n = $("answer").value.trim().split(/\s+/).filter(Boolean).length;
  $("wordCount").textContent = `${n} 단어`;
  $("btnFeedback").disabled = n < 3 || !current;
}
$("answer").addEventListener("input", updateWordCount);

function joinText(...parts) { return parts.map((p) => p.trim()).filter(Boolean).join(" "); }

function setupRecognition() {
  if (!SR) return null;
  const r = new SR();
  r.lang = "en-US";
  r.continuous = true;
  r.interimResults = true;
  r.onresult = (ev) => {
    let interim = "";
    sessionFinals = [];
    for (let i = 0; i < ev.results.length; i++) {
      const res = ev.results[i];
      const t = res[0].transcript.trim();
      if (!res.isFinal) { interim += " " + t; continue; }
      // Android Chrome sometimes repeats earlier text in later final results.
      const last = sessionFinals[sessionFinals.length - 1];
      if (last && t.toLowerCase().startsWith(last.toLowerCase())) sessionFinals[sessionFinals.length - 1] = t;
      else sessionFinals.push(t);
    }
    $("answer").value = joinText(committed, sessionFinals.join(" "), interim);
    updateWordCount();
  };
  r.onerror = (ev) => {
    if (ev.error === "not-allowed" || ev.error === "service-not-allowed") {
      toast("마이크 권한이 필요해요. 주소창의 자물쇠 아이콘에서 마이크를 허용해 주세요. (HTTPS 주소여야 해요)", 6000);
      stopRecording();
    }
  };
  r.onend = () => {
    // Recognition stops on its own after silence; keep going until the user stops.
    committed = joinText(committed, sessionFinals.join(" "));
    sessionFinals = [];
    if (recording) { try { r.start(); } catch {} }
  };
  return r;
}

function startRecording() {
  if (!SR) { toast("이 브라우저는 음성 인식을 지원하지 않아요. 안드로이드 Chrome을 사용해 주세요.", 5000); return; }
  if (!window.isSecureContext) { toast("음성 인식은 HTTPS 주소에서만 동작해요. README의 Tailscale 설정을 확인하세요.", 6000); return; }
  speechSynthesis.cancel();
  recog = recog || setupRecognition();
  committed = $("answer").value;
  sessionFinals = [];
  recording = true;
  try { recog.start(); } catch {}
  $("btnRec").classList.add("recording");
  $("btnRec").textContent = "⏹ 답변 끝내기";
  $("recStatus").textContent = "듣는 중... 영어로 말하세요";
  clearInterval(timerId);
  timerId = setInterval(() => { seconds++; renderTimer(); }, 1000);
}

function stopRecording() {
  if (!recording) return;
  recording = false;
  try { recog?.stop(); } catch {}
  clearInterval(timerId);
  $("btnRec").classList.remove("recording");
  $("btnRec").textContent = "🎤 이어서 답변";
  $("recStatus").textContent = "녹음 멈춤";
}

$("btnRec").addEventListener("click", () => (recording ? stopRecording() : startRecording()));
$("btnClear").addEventListener("click", () => {
  stopRecording();
  $("answer").value = ""; committed = ""; seconds = 0; renderTimer(); updateWordCount();
  $("btnRec").textContent = "🎤 답변 시작";
});

// ---------- feedback ----------
$("btnFeedback").addEventListener("click", async () => {
  stopRecording();
  // Give the recognizer a moment to deliver its last result.
  await new Promise((r) => setTimeout(r, 400));
  const answer = $("answer").value.trim();
  if (!current || !answer) return;
  const btn = $("btnFeedback");
  btn.disabled = true;
  $("feedback").innerHTML = '<div class="card"><span class="spinner"></span> AI가 답변을 평가하고 있어요...</div>';
  try {
    const fb = await api("/api/feedback", {
      question: current.text, answer, level: settings.level, qtype: current.qtype, duration_sec: seconds,
    });
    $("feedback").innerHTML = renderFeedback(fb);
    $("feedback").scrollIntoView({ behavior: "smooth" });
    saveHistory({ at: Date.now(), question: current, answer, seconds, level: settings.level, fb });
  } catch (e) {
    $("feedback").innerHTML = "";
    toast(e.message, 5000);
  } finally {
    updateWordCount();
  }
});

function renderFeedback(fb) {
  const list = (items) => items.length ? `<ul>${items.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : '<p class="muted">없음</p>';
  const corrections = fb.corrections.length
    ? fb.corrections.map((c) => `
      <div class="corr"><div><span class="from">${esc(c.original)}</span> → <span class="to">${esc(c.corrected)}</span></div>
      <div class="small muted">${esc(c.explanation_ko)}</div></div>`).join("")
    : '<p class="muted">큰 문법 오류가 없어요 👍</p>';
  const better = fb.better_expressions.map((b) => `
      <div class="corr"><div>${esc(b.instead_of)} → <span class="to">${esc(b.try_this)}</span></div>
      <div class="small muted">${esc(b.note_ko)}</div></div>`).join("");
  return `
  <div class="card">
    <div class="row" style="margin-top:0"><span class="grade">${esc(fb.estimated_grade)}</span>
      <span class="muted small">예상 등급 (목표 ${esc(meta.levels[settings.level].target)})</span></div>
    <p>${esc(fb.overall_comment_ko)}</p>
    <div class="fb-section"><h3>👍 잘한 점</h3>${list(fb.strengths_ko)}</div>
    <div class="fb-section"><h3>✏️ 문법 교정</h3>${corrections}</div>
    <div class="fb-section"><h3>💡 더 좋은 표현</h3>${better || '<p class="muted">없음</p>'}</div>
    <div class="fb-section"><h3>🧱 구성</h3><p>${esc(fb.structure_feedback_ko)}</p></div>
    <div class="fb-section"><h3>⏱️ 길이</h3><p>${esc(fb.length_feedback_ko)}</p></div>
    <div class="fb-section"><h3>📝 모범 답안</h3>
      <div class="model-answer">${esc(fb.model_answer)}</div>
      <div class="row"><button class="btn" onclick="speak(${esc(JSON.stringify(fb.model_answer))})">🔊 모범 답안 듣기</button>
      <button class="btn ghost" onclick="speechSynthesis.cancel()">정지</button></div>
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
      <summary><b>${esc(h.fb.estimated_grade)}</b> · ${esc(h.question.qtype_label)} · ${new Date(h.at).toLocaleString("ko-KR")}</summary>
      <p class="small"><b>Q.</b> ${esc(h.question.text)}</p>
      <p class="small"><b>내 답변</b> (${h.seconds}초): ${esc(h.answer)}</p>
      <div data-fb="${i}"></div>
    </details>`).join("");
  $("historyList").querySelectorAll("details").forEach((d, i) =>
    d.addEventListener("toggle", () => {
      const slot = d.querySelector("[data-fb]");
      if (d.open && !slot.innerHTML) slot.innerHTML = renderFeedback(hist[i].fb);
    }));
}
$("btnClearHistory").addEventListener("click", () => {
  if (confirm("연습 기록을 모두 삭제할까요?")) { store.set("history", []); renderHistory(); }
});

// ---------- init ----------
(async function init() {
  if ("speechSynthesis" in window) speechSynthesis.getVoices(); // warm up voice list
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  try {
    meta = await api("/api/meta");
    renderSetup();
    renderBadge();
  } catch (e) {
    toast("서버에 연결할 수 없어요. PC에서 서버가 켜져 있는지 확인하세요.", 6000);
  }
  if (!SR) toast("이 브라우저는 음성 인식을 지원하지 않아요. 안드로이드 Chrome을 사용해 주세요.", 6000);
})();
