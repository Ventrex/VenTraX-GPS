/* VenTrax service worker.
 * - Makes the site installable (home-screen app), which is what makes phones remember
 *   location/sound permissions instead of asking again.
 * - Caches theme sounds + static assets so game sounds also play on a bad connection.
 * Pages and API calls are never cached: the game always talks to the live server.
 */
const VERSION = 'vx-v3';
const ASSETS = VERSION + '-assets';
const SOUNDS = VERSION + '-sounds';

self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keep = [ASSETS, SOUNDS];
    for (const k of await caches.keys()) if (!keep.includes(k) && k.startsWith('vx-')) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // Uploaded theme sounds have unique file names -> cache forever.
  if (url.pathname.startsWith('/audio/themes/')) {
    e.respondWith(cacheFirst(req, SOUNDS));
    return;
  }
  // Shipped static files: serve from cache but refresh in the background.
  if (url.pathname.startsWith('/static/js/') || url.pathname.startsWith('/static/css/') || url.pathname.startsWith('/static/img/')) {
    e.respondWith(staleWhileRevalidate(req, ASSETS));
  }
});

async function cacheFirst(req, name) {
  const cache = await caches.open(name);
  const hit = await cache.match(req, {ignoreSearch: true});
  if (hit) return hit;
  const res = await fetch(req);
  // Range requests (audio seeking) return 206 which can't be cached; only store full responses.
  if (res.ok && res.status === 200) cache.put(req, res.clone());
  return res;
}
async function staleWhileRevalidate(req, name) {
  const cache = await caches.open(name);
  const hit = await cache.match(req);
  const net = fetch(req).then(res => { if (res.ok && res.status === 200) cache.put(req, res.clone()); return res; }).catch(() => null);
  return hit || (await net) || new Response('', {status: 504});
}
