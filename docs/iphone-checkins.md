# iPhone morning check-ins

## Product specification

An athlete who notices ankle pain on their first steps can record the observation from bed, including on a rest day while the Mac sleeps. The iPhone Home Screen app opens directly to the check-in. The Mac continues to host the training history and coaching review.

- While the Mac is reachable, install the web app from its private HTTPS address and open it once from the Home Screen. The app indicates when its check-in screen is available offline.
- The phone accepts one check-in per device-local calendar day. The athlete selects first-step pain from 0 to 10 using visible, consistent intensity labels. Zero records a pain-free morning in one tap. For positive pain, one additional tap records whether it disappeared, eased, stayed the same, worsened, or is too early to judge. Routine entry requires no typing.
- The phone stores the observation before confirming **Saved on iPhone**. Closing the screen or losing connectivity preserves pending entries in the app's local storage. Removing the web app or clearing its data can discard entries that have yet to sync.
- Reopening the app with the Mac reachable retries pending entries. **Synced** means the server has acknowledged that particular observation. Each retry carries the original timestamp and submission ID, including after an interrupted acknowledgment.
- A morning observation can reach coach review without a linked run. The coach can distinguish an explicit zero, reported pain and its walking response, and an unanswered morning. The entry records what the athlete noticed and leaves its cause open.

## Access and verification

Use the [private setup guide](iphone-setup.md) to connect the iPhone. The phone gateway serves the check-in and its write endpoint. The desktop dashboard, imports and coaching tools stay on the Mac.

Acceptance on a physical iPhone starts with a synthetic workspace. Install the app, wait for offline readiness, let the Mac sleep, then open the app fresh and record a check-in. Close and reopen while offline. Confirm that the entry is still pending. Wake the Mac, reopen the app, and verify that it syncs once with the original observation time. Repeat for a pain-free morning. A browser test exercises the same flow during development.

With the synthetic demo server running, the same automated journey can be repeated in mobile Chrome and WebKit. It checks the actual API before making a synthetic write and retries after an acknowledgment is dropped.

```sh
./scripts/run bash -c 'cd frontend && npx playwright install webkit'
PLAYWRIGHT_BASE_URL=http://127.0.0.1:18000 ./scripts/run bash -c 'cd frontend && npx playwright test --config playwright.iphone.config.ts'
```

## Later hosting

An always-on home device or private hosted deployment can eventually serve live calendar and history views. Offline capture stays useful when connectivity is poor. Before moving the app to a different address, sync pending phone entries with the existing host. Compare the cost of continuous compute, durable PostgreSQL storage, backups and the sync worker when selecting a host.
