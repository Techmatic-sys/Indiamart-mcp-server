/**
 * LeadFlow CRM — Service Worker
 * Caches static assets, provides offline fallback, background sync for activities/notes
 */

const CACHE_VERSION = 'leadflow-v1';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const API_CACHE = `${CACHE_VERSION}-api`;

const STATIC_ASSETS = [
    '/static/shared.css',
    '/static/shared.js',
    '/static/icon-192.svg',
    '/static/icon-512.svg',
    '/manifest.json',
    'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css',
];

const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LeadFlow — Offline</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', system-ui, sans-serif; background: #1a1a2e; color: #fff; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: 20px; }
  .icon { font-size: 64px; margin-bottom: 24px; }
  h1 { font-size: 28px; font-weight: 700; margin-bottom: 12px; }
  p { color: rgba(255,255,255,0.6); font-size: 16px; max-width: 400px; line-height: 1.6; }
  .bolt { color: #e94560; font-size: 80px; margin-bottom: 24px; display: block; }
  .retry { margin-top: 32px; padding: 12px 28px; background: #e94560; border: none; color: #fff; border-radius: 10px; font-size: 15px; font-weight: 600; cursor: pointer; font-family: inherit; }
  .retry:hover { background: #d63851; }
</style>
</head>
<body>
  <span class="bolt">⚡</span>
  <h1>You're Offline</h1>
  <p>LeadFlow needs an internet connection to sync your leads. Your cached data is still available.</p>
  <button class="retry" onclick="window.location.reload()">Try Again</button>
</body>
</html>`;

// ── Install ──────────────────────────────────────────────────────────────────
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(STATIC_CACHE).then(cache => {
            // Cache what we can, ignore failures for external resources
            return Promise.allSettled(
                STATIC_ASSETS.map(url => cache.add(url).catch(() => {}))
            );
        }).then(() => self.skipWaiting())
    );
});

// ── Activate ─────────────────────────────────────────────────────────────────
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(k => k !== STATIC_CACHE && k !== API_CACHE)
                    .map(k => caches.delete(k))
            )
        ).then(() => self.clients.claim())
    );
});

// ── Fetch ────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
    const { request } = event;
    const url = new URL(request.url);

    // Skip non-GET requests (POST, PUT, DELETE go to network directly)
    if (request.method !== 'GET') return;

    // Static assets → cache first, fallback to network
    if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.json') {
        event.respondWith(cacheFirst(request));
        return;
    }

    // API calls → network first, cache fallback for reads
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(networkFirstApi(request));
        return;
    }

    // App pages → network first, offline fallback
    if (url.pathname.startsWith('/app/') || url.pathname === '/') {
        event.respondWith(networkFirstPage(request));
        return;
    }

    // External resources (fonts, CDN) → cache first
    if (url.origin !== self.location.origin) {
        event.respondWith(cacheFirst(request));
        return;
    }
});

// ── Background Sync ──────────────────────────────────────────────────────────
self.addEventListener('sync', event => {
    if (event.tag === 'sync-activities') {
        event.waitUntil(syncPendingActivities());
    }
    if (event.tag === 'sync-notes') {
        event.waitUntil(syncPendingNotes());
    }
});

async function syncPendingActivities() {
    try {
        const db = await openIDB();
        const pending = await getAllFromStore(db, 'pending-activities');
        for (const item of pending) {
            try {
                const res = await fetch(`/api/activities`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${item.token}` },
                    body: JSON.stringify(item.data)
                });
                if (res.ok) await deleteFromStore(db, 'pending-activities', item.id);
            } catch (e) { /* retry next sync */ }
        }
    } catch (e) { /* IDB not available */ }
}

async function syncPendingNotes() {
    try {
        const db = await openIDB();
        const pending = await getAllFromStore(db, 'pending-notes');
        for (const item of pending) {
            try {
                const res = await fetch(`/api/leads/${item.data.lead_id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${item.token}` },
                    body: JSON.stringify({ notes: item.data.notes })
                });
                if (res.ok) await deleteFromStore(db, 'pending-notes', item.id);
            } catch (e) { /* retry next sync */ }
        }
    } catch (e) { /* IDB not available */ }
}

// ── Cache Strategies ─────────────────────────────────────────────────────────
async function cacheFirst(request) {
    const cached = await caches.match(request);
    if (cached) return cached;
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(STATIC_CACHE);
            cache.put(request, response.clone());
        }
        return response;
    } catch (e) {
        return new Response('', { status: 503 });
    }
}

async function networkFirstApi(request) {
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(API_CACHE);
            cache.put(request, response.clone());
        }
        return response;
    } catch (e) {
        const cached = await caches.match(request);
        if (cached) return cached;
        return new Response(JSON.stringify({ error: 'offline', cached: false }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
        });
    }
}

async function networkFirstPage(request) {
    try {
        return await fetch(request);
    } catch (e) {
        const cached = await caches.match(request);
        if (cached) return cached;
        return new Response(OFFLINE_HTML, {
            headers: { 'Content-Type': 'text/html' }
        });
    }
}

// ── IndexedDB Helpers ────────────────────────────────────────────────────────
function openIDB() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open('leadflow-offline', 1);
        req.onupgradeneeded = e => {
            const db = e.target.result;
            if (!db.objectStoreNames.contains('pending-activities')) {
                db.createObjectStore('pending-activities', { keyPath: 'id', autoIncrement: true });
            }
            if (!db.objectStoreNames.contains('pending-notes')) {
                db.createObjectStore('pending-notes', { keyPath: 'id', autoIncrement: true });
            }
        };
        req.onsuccess = e => resolve(e.target.result);
        req.onerror = () => reject(req.error);
    });
}

function getAllFromStore(db, storeName) {
    return new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, 'readonly');
        const req = tx.objectStore(storeName).getAll();
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

function deleteFromStore(db, storeName, id) {
    return new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, 'readwrite');
        const req = tx.objectStore(storeName).delete(id);
        req.onsuccess = () => resolve();
        req.onerror = () => reject(req.error);
    });
}
