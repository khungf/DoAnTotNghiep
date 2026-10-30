self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open('p2p-sos-v1').then((cache) => {
      return cache.addAll([
        '/static/login.html',
        '/static/index.html'
      ]);
    })
  );
});

self.addEventListener('fetch', (e) => {
  e.respondWith(
    caches.match(e.request).then((response) => {
      return response || fetch(e.request);
    })
  );
});