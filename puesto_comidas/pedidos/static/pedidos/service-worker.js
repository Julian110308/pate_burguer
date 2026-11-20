const CACHE_NAME = 'pateburguer-v1';
const urlsToCache = [
    '/',
    '/login/',
    '/static/pedidos/manifest.json',
    '/static/pedidos/icon-192x192.png',
    '/static/pedidos/icon-512x512.png',
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
    );
});

self.addEventListener('fetch', event => {
    if (event.request.method !== 'GET') return;
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});