const CACHE = 'p2p-sos-v3';
const PAGES = ['/static/login.html', '/static/index.html'];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PAGES)));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) {
    return;
  }
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok && PAGES.includes(url.pathname)) {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req))
  );
});

// Thông báo đẩy: không hiện nếu người dùng đang mở và nhìn thấy app (app đã tự cập nhật qua WebSocket).
self.addEventListener('push', (e) => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch (err) {}
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      if (windows.some((w) => w.visibilityState === 'visible' && w.focused)) return;
      return self.registration.showNotification(data.title || 'P2P SOS', {
        body: data.body || '',
        tag: data.tag || undefined,
        renotify: !!data.tag,
        vibrate: [200, 100, 200],
        data: { url: data.url || '/static/index.html' },
      });
    })
  );
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const target = (e.notification.data && e.notification.data.url) || '/static/index.html';
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      for (const w of windows) {
        if (w.url.includes('/static/') && 'focus' in w) return w.focus();
      }
      return self.clients.openWindow(target);
    })
  );
});
