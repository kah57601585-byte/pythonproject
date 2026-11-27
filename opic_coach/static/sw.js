// Service worker: needed so the app can be installed on the home screen.
// It deliberately does NOT cache the app's pages or scripts: the app only works with the PC
// server running, and cached pages made it look like the server was on (and hid updates).
const CACHE = "opic-coach-v7";
const SHELL = ["/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];

const OFFLINE_HTML = `<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>OPIc Coach</title>
<style>body{font-family:system-ui,sans-serif;padding:32px 20px;line-height:1.6;color:#1f2330;background:#f5f6fa}
@media (prefers-color-scheme: dark){body{color:#e8eaf0;background:#12141a}}
button{padding:10px 16px;border-radius:10px;border:0;background:#4f46e5;color:#fff;font-size:16px}</style></head>
<body><h2>🔌 PC 서버가 꺼져 있어요</h2>
<p>PC에서 <b>run_windows.bat</b> 을 실행한 뒤 다시 시도해 주세요.<br>
폰에서 접속 중이라면 Tailscale이 켜져 있는지도 확인해 주세요.</p>
<button onclick="location.reload()">다시 시도</button></body></html>`;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  // Remove every older cache, including the pages cached by earlier versions.
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  if (e.request.mode === "navigate") {
    e.respondWith(
      fetch(e.request, { cache: "no-store" }).catch(() =>
        new Response(OFFLINE_HTML, { headers: { "Content-Type": "text/html; charset=utf-8" } })),
    );
    return;
  }
  if (SHELL.includes(url.pathname)) {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
  }
  // Everything else (app.js, style.css, /api/...) goes straight to the network.
});
