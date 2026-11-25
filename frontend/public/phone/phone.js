const element = (id) => document.getElementById(id)
const bands = [
  [0, 0, 'No pain', ''],
  [1, 3, 'Mild', 'Easy to put out of mind'],
  [4, 6, 'Moderate', 'Keeps drawing my attention'],
  [7, 9, 'Severe', 'Hard to focus on anything else'],
  [10, 10, 'Worst imaginable', ''],
]
const responses = {
  gone: 'Gone',
  eased: 'Eased',
  same: 'About the same',
  worse: 'Worse',
  too_early: 'Too early to tell',
}

let db
let selection
let showingDay
let saving = false
let syncing = false
let syncAgain = false
let syncMessage = ''

function localDay(date) {
  const parts = [date.getFullYear(), date.getMonth() + 1, date.getDate()]
  return parts.map((part) => String(part).padStart(2, '0')).join('-')
}

function showError(message) {
  element('error').textContent = message
  element('error').hidden = !message
}

function openDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('going-bananas-phone-checkins', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('mornings', { keyPath: 'day' })
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

// Wait for transaction commit, including on a local save, before changing the receipt.
function withMorningStore(mode, operation) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('mornings', mode)
    const request = operation(tx.objectStore('mornings'))
    tx.oncomplete = () => resolve(request.result)
    tx.onabort = () => reject(tx.error || request.error)
  })
}

async function render() {
  const records = await withMorningStore('readonly', (store) => store.getAll())
  const now = new Date()
  const day = localDay(now)
  if (showingDay !== day) {
    selection = null
    element('walking').hidden = true
    element('date').textContent = now.toLocaleDateString(undefined, {
      weekday: 'long',
      month: 'long',
      day: 'numeric',
    })
    showingDay = day
  }
  const today = records.find((row) => row.day === day)
  element('form').hidden = Boolean(today)
  element('receipt').hidden = !today
  for (const button of element('scale').querySelectorAll('button')) {
    button.setAttribute('aria-pressed', String(selection?.pain === Number(button.value)))
  }
  if (today) {
    element('saved').textContent = today.synced ? 'Synced' : 'Saved on iPhone'
    const { pain, walking_response: response } = today.entry
    element('summary').textContent = [
      'First-step pain ' + pain + '/10',
      response ? 'After walking: ' + responses[response] : '',
    ]
      .filter(Boolean)
      .join(' · ')
  }
  const pending = records.filter((row) => !row.synced).length
  element('outbox').hidden = pending === 0
  element('retry').disabled = syncing
  element('pending').textContent = pending
    ? [
        pending === 1 ? '1 check-in waiting to sync.' : pending + ' check-ins waiting to sync.',
        syncMessage,
      ]
        .filter(Boolean)
        .join(' ')
    : ''
}

async function save(walkingResponse) {
  if (saving || !selection) return
  saving = true
  showError('')
  const { observed, pain } = selection
  try {
    await withMorningStore('readwrite', (store) =>
      store.add({
        id: crypto.randomUUID(),
        day: localDay(observed),
        entry: { observed_at: observed.toISOString(), pain, walking_response: walkingResponse },
        synced: false,
      }),
    )
    selection = null
    await render()
    element('saved').focus()
    void sync()
  } catch (error) {
    if (error?.name === 'ConstraintError') {
      await render()
    } else {
      showError('Couldn’t save on this iPhone. Check available storage and try again.')
    }
  } finally {
    saving = false
  }
}

function selectPain(pain) {
  if (saving) return
  selection = { pain, observed: new Date() }
  if (pain === 0) {
    void save(null)
    return
  }
  for (const button of element('scale').querySelectorAll('button')) {
    button.setAttribute('aria-pressed', String(Number(button.value) === pain))
  }
  element('walking').hidden = false
  element('walking-title').focus()
}

function setupForm() {
  for (const [min, max, label, description] of bands) {
    const row = document.createElement('div')
    row.className = 'band'
    const heading = document.createElement('div')
    const title = document.createElement('span')
    title.className = 'band-label'
    title.textContent = label
    const definition = document.createElement('span')
    definition.className = 'definition'
    definition.textContent = description
    heading.append(title, definition)
    const scores = document.createElement('div')
    scores.className = 'scores'
    for (let pain = min; pain <= max; pain++) {
      const button = document.createElement('button')
      button.type = 'button'
      button.value = String(pain)
      button.textContent = String(pain)
      button.setAttribute('aria-label', pain + ' · ' + label)
      button.addEventListener('click', () => selectPain(pain))
      scores.append(button)
    }
    row.append(heading, scores)
    element('scale').append(row)
  }
  for (const [value, label] of Object.entries(responses)) {
    const button = document.createElement('button')
    button.type = 'button'
    button.textContent = label
    button.addEventListener('click', () => void save(value))
    element('responses').append(button)
  }
}

async function upload(row) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 10000)
  try {
    const response = await fetch('/api/v1/phone/checkins/' + row.id, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-Local-Request': '1' },
      body: JSON.stringify(row.entry),
      signal: controller.signal,
      redirect: 'error',
    })
    if (!response.ok) {
      throw new Error(
        response.status >= 400 && response.status < 500
          ? 'Check the phone connection and workspace on your Mac, then retry (HTTP ' +
              response.status +
              ').'
          : 'Reopen when your Mac is reachable, or retry sync.',
      )
    }
    const receipt = await response.json()
    if (receipt?.data?.id !== row.id) throw new Error('Confirmation missing. Retry sync.')
  } finally {
    clearTimeout(timer)
  }
}

async function sync() {
  if (!db) return
  if (syncing) {
    syncAgain = true
    return
  }
  syncing = true
  syncMessage = ''
  try {
    const rows = await withMorningStore('readonly', (store) => store.getAll())
    for (const row of rows) {
      if (!row.synced) {
        try {
          await upload(row)
        } catch (error) {
          syncMessage =
            error.constructor === Error
              ? error.message
              : 'Reopen when your Mac is reachable, or retry sync.'
          break
        }
        row.synced = true
        await withMorningStore('readwrite', (store) => store.put(row))
      }
      if (row.day < localDay(new Date())) {
        await withMorningStore('readwrite', (store) => store.delete(row.day))
      }
    }
  } catch {
    showError('Couldn’t update local storage. Reopen to retry.')
  } finally {
    await render().catch(() => showError('Couldn’t read the saved check-ins. Reopen to retry.'))
    syncing = false
    element('retry').disabled = false
    if (syncAgain) {
      syncAgain = false
      void sync()
    }
  }
}

async function prepareOffline() {
  try {
    const registration = await navigator.serviceWorker.register('/phone/sw.js', {
      scope: '/phone/',
    })
    if (!registration.active && registration.installing) {
      await new Promise((resolve, reject) => {
        const worker = registration.installing
        function check() {
          if (worker.state === 'redundant') reject(new Error('Offline setup failed'))
          if (worker.state === 'activated') resolve()
        }
        worker.addEventListener('statechange', check)
        check()
      })
    }
    await navigator.serviceWorker.ready
    element('offline').textContent = 'Ready offline'
  } catch {
    element('offline').textContent = 'Reconnect and reopen to finish offline setup'
  }
}

async function start() {
  setupForm()
  try {
    db = await openDatabase()
    await render()
  } catch {
    element('offline').textContent = 'Storage unavailable'
    showError('Allow website storage and reopen to record a check-in.')
    return
  }
  void prepareOffline()
  element('retry').addEventListener('click', sync)
  window.addEventListener('online', sync)
  window.addEventListener('pageshow', sync)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      void render().catch(() => showError('Couldn’t read the saved check-ins. Reopen to retry.'))
      void sync()
    }
  })
  void sync()
}

void start()
