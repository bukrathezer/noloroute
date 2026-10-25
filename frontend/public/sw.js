// NoloRoute's service worker: makes the site installable as an app, and shows a page of its own
// when it is opened without a connection. Nothing else is cached: plans need the server anyway,
// and the app's files must always be the latest deploy (the server already sets their caching).
// Change the version whenever offline.html changes: it is only fetched again when this file does.
const CACHE = "noloroute-offline-v2";
const OFFLINE_PAGE = "/offline.html"; // self-contained: no other file needed

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.add(OFFLINE_PAGE)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Pages are requested while this worker starts up, rather than after: no delay for having one.
      await self.registration.navigationPreload?.enable();
      // Remove the caches of earlier versions of this file.
      const keys = await caches.keys();
      await Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)));
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  // Pages: from the network, or the offline page when there is none. Everything else is left
  // to the browser.
  if (request.mode === "navigate") {
    event.respondWith(
      (async () => {
        try {
          return (await event.preloadResponse) || (await fetch(request));
        } catch {
          // The browser may have cleared the cache: then its own offline error.
          return (await caches.match(OFFLINE_PAGE)) || Response.error();
        }
      })(),
    );
  }
});
