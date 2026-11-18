// Offline support. The app's own files are fetched network-first (so a new
// version shows up as soon as there is a connection) and fall back to the
// cache; Pyodide's files are versioned and never change, so they are cache-first.
// The build stamps __VERSION__ so each release gets a fresh cache.

const CACHE = "shuffle-solver-__VERSION__";
const SHELL = [
  "./", "index.html", "app.css", "app.js", "tracker.js", "worker.js", "manifest.webmanifest",
  "py/solver.zip", "icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png",
  "icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function cacheFirst(request) {
  const hit = await caches.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) (await caches.open(CACHE)).put(request, response.clone());
  return response;
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) (await caches.open(CACHE)).put(request, response.clone());
    return response;
  } catch (err) {
    const hit = await caches.match(request, { ignoreSearch: true });
    if (hit) return hit;
    throw err;
  }
}

const isPyodide = (url) => url.hostname === "cdn.jsdelivr.net" && url.pathname.startsWith("/pyodide/");

// The page passes on what the solver worker loaded; keep any of it not cached yet.
self.addEventListener("message", (event) => {
  if (event.data?.type !== "warm") return;
  const urls = event.data.urls.filter((u) => {
    const url = new URL(u);
    return isPyodide(url) || url.origin === self.location.origin;
  });
  event.waitUntil(Promise.all(urls.map((u) => cacheFirst(new Request(u)).catch(() => null))));
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (isPyodide(url)) {
    event.respondWith(cacheFirst(request));
  } else if (url.origin === self.location.origin) {
    event.respondWith(networkFirst(request));
  }
});
