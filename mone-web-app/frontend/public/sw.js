const CACHE = "mone-v1";
const STATIC = ["/", "/manifest.json", "/brand/mone-logo-192.png", "/brand/mone-logo.png"];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(STATIC).catch(() => {}))
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // API 요청은 항상 네트워크 우선 (캐시 안 함)
  if (url.pathname.startsWith("/mone-api") || url.pathname.startsWith("/api")) {
    return;
  }

  // 정적 자산 — 캐시 우선, 없으면 네트워크
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        if (response.ok && event.request.method === "GET") {
          const clone = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => cached || new Response("오프라인 상태입니다.", { status: 503 }));
    })
  );
});
