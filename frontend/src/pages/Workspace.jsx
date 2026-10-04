import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { ErrorNote, Icon, Logo } from '../components/ui.jsx'
import { formatDate } from '../components/status.js'
import { EngineStatus } from '../components/EngineStatus.jsx'

export default function Workspace() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['investigations'], queryFn: api.investigations })
  const [title, setTitle] = useState('')
  const [showNew, setShowNew] = useState(false)

  const demo = useMutation({
    mutationFn: api.loadDemo,
    onSuccess: (inv) => {
      qc.invalidateQueries({ queryKey: ['investigations'] })
      navigate(`/app/i/${inv.id}`)
    },
  })
  const create = useMutation({
    mutationFn: () => api.createInvestigation(title, ''),
    onSuccess: (inv) => navigate(`/app/i/${inv.id}/documents`),
  })
  const remove = useMutation({
    mutationFn: (id) => api.deleteInvestigation(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['investigations'] }),
  })

  return (
    <div className="workspace">
      <header className="ws-top">
        <Link to="/"><Logo /></Link>
        <div className="ws-user">
          <span className="faint">{user?.name}{user?.guest ? ' · private guest workspace' : ''}</span>
          <button className="btn btn-ghost btn-sm" onClick={logout}><Icon name="logout" size={15} /> Sign out</button>
        </div>
      </header>

      <main className="ws-main">
        <div className="ws-head">
          <span className="eyebrow">Workspace</span>
          <h1 className="serif">Investigations</h1>
        </div>

        <div className="ws-grid">
          <button className="demo-card" onClick={() => demo.mutate()} disabled={demo.isPending}>
            <span className="eyebrow">Judge demo · one click</span>
            <h2 className="serif">Load the demo investigation</h2>
            <p className="muted">
              A scholarship case: 11 documents in 5 formats — two years of guidelines, a state rulebook, a government circular,
              two applicants, a scanned certificate and a document carrying a hidden prompt-injection attack.
            </p>
            <div className="demo-formats">
              {['PDF', 'DOCX', 'TXT', 'PNG scan', 'Scanned PDF'].map((f) => <span key={f} className="chip">{f}</span>)}
            </div>
            <span className="btn btn-primary">
              {demo.isPending ? <><span className="spinner" /> Creating…</> : <>Load demo <Icon name="arrow" size={16} /></>}
            </span>
            <span className="faint demo-note">Documents go through the real pipeline. Indexing takes about 30 seconds.</span>
          </button>

          <div className="card new-card">
            <span className="eyebrow">Your own documents</span>
            <h2 className="serif">New investigation</h2>
            {showNew ? (
              <form onSubmit={(e) => { e.preventDefault(); if (title.trim()) create.mutate() }} className="new-form">
                <input className="input" autoFocus placeholder="e.g. Vendor contract review" value={title}
                  onChange={(e) => setTitle(e.target.value)} maxLength={200} />
                <div className="row">
                  <button className="btn btn-primary" type="submit" disabled={!title.trim() || create.isPending}>Create</button>
                  <button className="btn btn-ghost" type="button" onClick={() => setShowNew(false)}>Cancel</button>
                </div>
              </form>
            ) : (
              <>
                <p className="muted">Upload PDFs, Word documents, text files or scans and start asking questions.</p>
                <button className="btn" onClick={() => setShowNew(true)}><Icon name="plus" size={16} /> New investigation</button>
              </>
            )}
            <ErrorNote error={create.error} />
          </div>
        </div>
        <ErrorNote error={demo.error} />

        <section className="ws-list">
          <h2 className="eyebrow">Recent</h2>
          {list.isLoading && <div className="row faint"><span className="spinner" /> Loading…</div>}
          <ErrorNote error={list.error} onRetry={list.refetch} />
          {list.data?.length === 0 && <p className="faint">No investigations yet. Load the demo to see VERITAS at work.</p>}
          <ul>
            {list.data?.map((inv) => (
              <li key={inv.id} className="ws-item">
                <Link to={`/app/i/${inv.id}`} className="ws-item-main">
                  <span className="ws-item-title">{inv.title}{inv.demo && <span className="chip">demo</span>}</span>
                  <span className="faint">
                    {inv.documentCount} documents · {inv.indexedCount} indexed · updated {formatDate(inv.updatedAt)}
                  </span>
                </Link>
                <button className="btn btn-ghost btn-sm btn-danger" aria-label={`Delete ${inv.title}`}
                  onClick={() => { if (confirm(`Delete “${inv.title}” and its documents?`)) remove.mutate(inv.id) }}>
                  <Icon name="trash" size={15} />
                </button>
              </li>
            ))}
          </ul>
        </section>

        <EngineStatus />
      </main>
    </div>
  )
}
