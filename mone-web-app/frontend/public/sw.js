const CACHE = "mone-v13";
const STATIC = ["/manifest.json", "/brand/mone-logo-192.png", "/brand/mone-logo.png"];
const OFFLINE_FALLBACK = "/__offline";

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(STATIC).catch(() => {}))
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;

  const url = new URL(event.request.url);

  // API 요청은 캐시 우회 (항상 네트워크 직접)
  if (url.pathname.startsWith("/mone-api") || url.pathname.startsWith("/api")) {
    return;
  }

  if (url.pathname.startsWith("/_next/")) {
    event.respondWith(fetch(event.request));
    return;
  }

  // 페이지 네비게이션: 네트워크 우선, 실패 시 캐시 → 오프라인 안내
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() =>
          caches.match(event.request).then((cached) =>
            cached ||
            new Response(
              `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>오프라인 - MONE</title>
              <meta name="viewport" content="width=device-width,initial-scale=1">
              <style>body{background:#020817;color:#94a3b8;font-family:system-ui;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;flex-direction:column;gap:16px}h1{color:#e2e8f0;font-size:1.25rem}p{font-size:.875rem;text-align:center}</style></head>
              <body><h1>오프라인 상태</h1><p>네트워크 연결을 확인하고 다시 시도해 주세요.</p>
              <button onclick="location.reload()" style="background:#1d4ed8;color:#fff;border:none;border-radius:8px;padding:8px 20px;cursor:pointer;font-size:.875rem">다시 시도</button></body></html>`,
              { headers: { "Content-Type": "text/html; charset=utf-8" } }
            )
          )
        )
    );
    return;
  }

  // 정적 자원: 캐시 우선, 없으면 네트워크
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, clone));
        }
        return response;
      });
    })
  );
});
