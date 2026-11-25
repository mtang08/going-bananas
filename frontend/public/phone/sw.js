// Bump this version when changing any phone shell asset.
const cacheName = 'going-bananas-phone-shell-v1'
const shell = [
  '/phone/index.html',
  '/phone/phone.js',
  '/phone/phone.css',
  '/phone/manifest.webmanifest',
  '/phone/icon-192.png',
  '/phone/icon-512.png',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(cacheName)
      await cache.addAll(shell.map((path) => new Request(path, { cache: 'reload' })))
      await self.skipWaiting()
    })(),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      for (const name of await caches.keys()) {
        if (name.startsWith('going-bananas-phone-shell-') && name !== cacheName)
          await caches.delete(name)
      }
      await self.clients.claim()
    })(),
  )
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return
  const path = url.pathname === '/phone/' ? '/phone/index.html' : url.pathname
  if (!shell.includes(path)) return
  event.respondWith(
    (async () => {
      const hit = await (await caches.open(cacheName)).match(path)
      return hit || fetch(event.request)
    })(),
  )
})
