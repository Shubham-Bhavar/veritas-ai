// Thin API client: bearer token from session storage, RFC 7807 errors turned into ApiError.

const TOKEN_KEY = 'veritas.token'
const USER_KEY = 'veritas.user'

export class ApiError extends Error {
  constructor(status, message, code, errors) {
    super(message)
    this.status = status
    this.code = code
    this.errors = errors
  }
}

function read(key) {
  try {
    return sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key, value) {
  try {
    if (value == null) sessionStorage.removeItem(key)
    else sessionStorage.setItem(key, value)
  } catch {
    // storage unavailable (private mode): the session lasts until reload
  }
}

let memoryToken = read(TOKEN_KEY)
let onUnauthorized = () => {}

export const session = {
  token: () => memoryToken,
  user: () => {
    const raw = read(USER_KEY)
    try {
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  },
  set(token, user) {
    memoryToken = token
    write(TOKEN_KEY, token)
    write(USER_KEY, JSON.stringify(user))
  },
  clear() {
    memoryToken = null
    write(TOKEN_KEY, null)
    write(USER_KEY, null)
  },
  onUnauthorized(fn) {
    onUnauthorized = fn
  },
}

async function request(path, { method = 'GET', body, form, raw } = {}) {
  const headers = {}
  if (memoryToken) headers.Authorization = `Bearer ${memoryToken}`
  let payload
  if (form) payload = form
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  let res
  try {
    res = await fetch(`/api${path}`, { method, headers, body: payload })
  } catch {
    throw new ApiError(0, 'Cannot reach the VERITAS server. Check your connection.', 'NETWORK')
  }
  if (res.status === 401 && memoryToken) {
    session.clear()
    onUnauthorized()
  }
  if (!res.ok) {
    let problem = {}
    try {
      problem = await res.json()
    } catch {
      // not JSON
    }
    const fallback = [502, 503, 504].includes(res.status)
      ? 'The VERITAS server is unavailable right now. Try again in a moment.'
      : res.status === 413 ? 'The upload is too large.' : `Request failed (${res.status}).`
    throw new ApiError(res.status, problem.detail || fallback, problem.code, problem.errors)
  }
  if (raw) return res
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  status: () => request('/system/status'),
  me: () => request('/auth/me'),
  guest: () => request('/auth/guest', { method: 'POST' }),
  login: (email, password) => request('/auth/login', { method: 'POST', body: { email, password } }),
  register: (name, email, password) => request('/auth/register', { method: 'POST', body: { name, email, password } }),

  investigations: () => request('/investigations'),
  createInvestigation: (title, description) => request('/investigations', { method: 'POST', body: { title, description } }),
  loadDemo: () => request('/investigations/demo', { method: 'POST' }),
  investigation: (id) => request(`/investigations/${id}`),
  deleteInvestigation: (id) => request(`/investigations/${id}`, { method: 'DELETE' }),

  upload: (id, files) => {
    const form = new FormData()
    for (const f of files) form.append('files', f)
    return request(`/investigations/${id}/documents`, { method: 'POST', form })
  },
  retryDocument: (id, docId) => request(`/investigations/${id}/documents/${docId}/retry`, { method: 'POST' }),
  deleteDocument: (id, docId) => request(`/investigations/${id}/documents/${docId}`, { method: 'DELETE' }),
  documentContent: (id, docId) => request(`/investigations/${id}/documents/${docId}/content`),
  chunk: (id, chunkId) => request(`/investigations/${id}/chunks/${encodeURIComponent(chunkId)}`),

  ask: (id, question) => request(`/investigations/${id}/questions`, { method: 'POST', body: { question } }),
  history: (id) => request(`/investigations/${id}/questions`),
  answer: (id, qid) => request(`/investigations/${id}/questions/${qid}`),
  conflicts: (id) => request(`/investigations/${id}/conflicts`),
  security: (id) => request(`/investigations/${id}/security`),
  overview: (id) => request(`/investigations/${id}/overview`),
  compare: (id, documentA, documentB) => request(`/investigations/${id}/compare`, { method: 'POST', body: { documentA, documentB } }),
  timeline: (id) => request(`/investigations/${id}/timeline`),

  async pageImage(id, docId, page, { chunk, sentence, flags } = {}) {
    const q = new URLSearchParams()
    if (chunk) q.set('chunk', chunk)
    if (sentence) q.set('sentence', sentence.slice(0, 300))
    if (flags) q.set('flags', 'true')
    const res = await request(`/investigations/${id}/documents/${docId}/pages/${page}?${q}`, { raw: true })
    return URL.createObjectURL(await res.blob())
  },
}
