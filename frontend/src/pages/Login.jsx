import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'
import { useAuth } from '../auth.jsx'
import { Logo } from '../components/ui.jsx'

export default function Login() {
  const { user, guest, login, register, expired } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [mode, setMode] = useState('signin')
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const next = location.state?.from || '/app'

  if (user) return <Navigate to={next} replace />

  const run = async (kind, fn) => {
    setBusy(kind)
    setError(null)
    try {
      await fn()
      navigate(next, { replace: true })
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  const submit = (e) => {
    e.preventDefault()
    run(mode, () => (mode === 'signin' ? login(form.email, form.password) : register(form.name, form.email, form.password)))
  }
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  return (
    <div className="auth-page">
      <Link to="/" className="auth-logo"><Logo /></Link>
      <div className="auth-card panel rise">
        <h1 className="serif">Open your workspace</h1>
        <p className="muted">Investigations are private to your account.</p>
        {(expired || location.state?.expired) && <p className="form-error" role="status">Your session ended. Please sign in again.</p>}

        <button className="btn btn-primary btn-lg auth-guest" disabled={!!busy} onClick={() => run('guest', guest)}>
          {busy === 'guest' ? <span className="spinner" /> : null}
          Continue as guest
        </button>
        <p className="faint auth-hint">A private, temporary workspace. Best for trying the demo.</p>

        <div className="auth-sep"><span>or</span></div>

        <div className="tabs-inline" role="tablist">
          <button role="tab" aria-selected={mode === 'signin'} className={mode === 'signin' ? 'active' : ''} onClick={() => setMode('signin')}>Sign in</button>
          <button role="tab" aria-selected={mode === 'register'} className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>Create account</button>
        </div>
        <form onSubmit={submit} className="auth-form" noValidate>
          {mode === 'register' && (
            <div className="field">
              <label htmlFor="name">Name</label>
              <input id="name" className="input" value={form.name} onChange={set('name')} autoComplete="name" required />
            </div>
          )}
          <div className="field">
            <label htmlFor="email">Email</label>
            <input id="email" type="email" className="input" value={form.email} onChange={set('email')} autoComplete="email" required />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input id="password" type="password" className="input" value={form.password} onChange={set('password')}
              autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} required minLength={mode === 'register' ? 10 : undefined} />
            {mode === 'register' && <span className="faint" style={{ fontSize: 12 }}>At least 10 characters.</span>}
          </div>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="btn" type="submit" disabled={!!busy}>
            {busy === mode ? <span className="spinner" /> : null}
            {mode === 'signin' ? 'Sign in' : 'Create account'}
          </button>
        </form>
      </div>
    </div>
  )
}
