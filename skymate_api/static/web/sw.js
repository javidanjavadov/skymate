/**
 * Keeps SkyMate usable without a connection: the page shell is served from the cache, weather always comes from
 * the network (the page itself falls back to the last forecast it saved).
 */
const SHELL = "skymate-shell-v1"

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll(["/", "/favicon.svg", "/manifest.webmanifest"])));
  self.skipWaiting()
})

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k)))))
  self.clients.claim()
})

self.addEventListener("fetch", (event) => {
  const { request } = event
  if (request.method !== "GET") return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return          // weather data and map lookups: never cached here
  if (url.pathname.startsWith("/site/") || url.pathname.startsWith("/v1/")) return

  // Built files carry a hash in the name, so they can be served from the cache and stored on first use
  if (url.pathname.startsWith("/app/")) {
    event.respondWith(caches.match(request).then((hit) => hit ?? fetch(request).then((res) => {
      const copy = res.clone()
      caches.open(SHELL).then((cache) => cache.put(request, copy))
      return res
    })))
    return
  }

  // Pages: fresh when online, last copy when not
  event.respondWith(fetch(request).then((res) => {
    const copy = res.clone()
    caches.open(SHELL).then((cache) => cache.put("/", copy))
    return res
  }).catch(() => caches.match("/").then((hit) => hit ?? Response.error())))
})
