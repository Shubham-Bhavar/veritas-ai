import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, NavLink, useNavigate, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { ErrorNote, Icon, Logo } from '../components/ui.jsx'
import { EngineStatus } from '../components/EngineStatus.jsx'
import { InvestigationContext } from './context.js'
import InvestigateTab from './InvestigateTab.jsx'
import DocumentsTab from './DocumentsTab.jsx'
import ConflictsTab from './ConflictsTab.jsx'
import GraphTab from './GraphTab.jsx'
import CompareTab from './CompareTab.jsx'
import SecurityTab from './SecurityTab.jsx'
import TimelineTab from './TimelineTab.jsx'
import Inspector from './Inspector.jsx'
import JudgeMode from './JudgeMode.jsx'

const TABS = [
  ['investigate', 'Investigate', 'investigate'],
  ['documents', 'Documents', 'documents'],
  ['conflicts', 'Conflict Radar', 'conflicts'],
  ['graph', 'Evidence Graph', 'graph'],
  ['compare', 'Compare', 'compare'],
  ['security', 'Security', 'security'],
  ['timeline', 'Timeline', 'timeline'],
]

/** Indexing progress from real document statuses only — no simulated steps. */
function IndexingStrip({ documents }) {
  const count = (s) => documents.filter((d) => d.status === s).length
  const queued = count('QUEUED')
  const working = documents.filter((d) => d.status === 'PROCESSING')
  const done = count('INDEXED')
  const failed = count('FAILED')
  const stages = [
    ['Uploaded', documents.length, 'validated and stored'],
    ['Waiting', queued, 'in the indexing queue'],
    ['Extracting', working.length, 'layout, OCR, facts, embeddings'],
    ['Indexed', done, 'searchable evidence'],
  ]
  return (
    <div className="indexing-bar" role="status" aria-live="polite">
      <div className="indexing-stages">
        {stages.map(([name, n, hint], i) => (
          <div key={name} className={`stage ${name === 'Extracting' && n ? 'active' : ''}`}>
            <span className="stage-n mono">{n}</span>
            <span><strong>{name}</strong><span className="faint"> · {hint}</span></span>
            {i < stages.length - 1 && <span className="stage-arrow faint">→</span>}
          </div>
        ))}
        <div className="stage pending">
          <span className="spinner" />
          <span><strong>Evidence map</strong><span className="faint"> · conflicts are scanned when the last document lands</span></span>
        </div>
      </div>
      {working.length > 0 && (
        <p className="faint indexing-now">Now: {working.map((d) => d.filename).join(', ')}</p>
      )}
      {failed > 0 && <p className="form-error">{failed} document(s) failed — see Documents for the reason and Retry.</p>}
      <div className="indexing-track"><span style={{ width: `${(done / Math.max(1, documents.length)) * 100}%` }} /></div>
    </div>
  )
}

export default function Investigation() {
  const { id, tab = 'investigate' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { user, logout } = useAuth()
  const [answer, setAnswer] = useState(null)
  const [source, setSource] = useState(null)
  const [judgeOpen, setJudgeOpen] = useState(false)
  const [compareRequest, setCompareRequest] = useState(null)
  const [draft, setDraft] = useState('')

  const inv = useQuery({
    queryKey: ['investigation', id],
    queryFn: () => api.investigation(id),
    refetchInterval: (q) => {
      const docs = q.state.data?.documents || []
      return docs.some((d) => d.status === 'QUEUED' || d.status === 'PROCESSING') ? 1500 : false
    },
  })
  const documents = useMemo(() => inv.data?.documents ?? [], [inv.data])
  const indexed = documents.filter((d) => d.status === 'INDEXED').length
  const busy = documents.some((d) => d.status === 'QUEUED' || d.status === 'PROCESSING')

  useEffect(() => {
    window.scrollTo(0, 0)
  }, [tab])

  const history = useQuery({ queryKey: ['history', id], queryFn: () => api.history(id) })

  const overview = useQuery({
    queryKey: ['overview', id, indexed],
    queryFn: () => api.overview(id),
    enabled: indexed > 0,
  })
  // When indexing finishes, everything derived from the collection is stale.
  useEffect(() => {
    if (!busy && indexed > 0) {
      qc.invalidateQueries({ queryKey: ['conflicts', id] })
      qc.invalidateQueries({ queryKey: ['security', id] })
      qc.invalidateQueries({ queryKey: ['timeline', id] })
    }
  }, [busy, indexed, id, qc])

  const ask = useMutation({
    mutationFn: (question) => api.ask(id, question),
    onSuccess: (data) => {
      setAnswer(data)
      qc.invalidateQueries({ queryKey: ['history', id] })
      qc.invalidateQueries({ queryKey: ['timeline', id] })
    },
    // An outage should show in the engine badge immediately, not at its next poll.
    onError: (e) => {
      if (e.status === 0 || e.status >= 500) qc.invalidateQueries({ queryKey: ['status'] })
    },
  })

  const runQuestion = useCallback((question) => {
    setDraft(question)
    navigate(`/app/i/${id}/investigate`)
    ask.mutate(question)
  }, [ask, id, navigate])

  const openAnswer = useCallback(async (qid) => {
    const data = await api.answer(id, qid)
    setAnswer(data)
    setDraft(data.question)
    navigate(`/app/i/${id}/investigate`)
  }, [id, navigate])

  const ctx = {
    id, investigation: inv.data?.investigation, documents, overview: overview.data, busy, indexed,
    answer, setAnswer, ask, runQuestion, openAnswer, draft, setDraft,
    openSource: setSource, source,
    goTab: (t) => navigate(`/app/i/${id}/${t}`),
    compareRequest, setCompareRequest,
  }

  if (inv.isError) {
    return (
      <div className="ws-main">
        <ErrorNote error={inv.error} />
        <Link to="/app" className="btn">Back to workspace</Link>
      </div>
    )
  }

  const o = overview.data
  const lastConfidence = answer ? answer.confidence.score : history.data?.[0]?.confidence
  return (
    <InvestigationContext.Provider value={ctx}>
      <div className={`station ${source ? 'with-inspector' : ''}`}>
        <aside className="sidebar">
          <Link to="/app" className="sidebar-logo"><Logo size={20} /></Link>
          <nav className="sidebar-nav">
            {TABS.map(([key, label, icon]) => (
              <NavLink key={key} to={`/app/i/${id}/${key}`} className={() => `nav-item ${tab === key ? 'active' : ''}`}>
                <Icon name={icon} size={17} />
                <span>{label}</span>
                {key === 'conflicts' && o?.conflicts_unresolved > 0 && <span className="nav-badge warn">{o.conflicts_unresolved}</span>}
                {key === 'security' && o?.security_flags > 0 && <span className="nav-badge danger">{o.security_flags}</span>}
                {key === 'documents' && busy && <span className="dot pulse" style={{ background: 'var(--uncertain)' }} />}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-foot">
            <button className="btn judge-btn" onClick={() => setJudgeOpen(true)}>
              <Icon name="judge" size={16} /> Judge mode
            </button>
            <EngineStatus compact />
            <div className="sidebar-user">
              <span className="faint">{user?.name}</span>
              <button className="btn btn-ghost btn-sm" onClick={logout} aria-label="Sign out"><Icon name="logout" size={15} /></button>
            </div>
          </div>
        </aside>

        <main className="station-main">
          <header className="station-top">
            <div className="station-title">
              <Link to="/app" className="faint crumb"><Icon name="back" size={14} /> Investigations</Link>
              <h1>{inv.data?.investigation.title || '…'}</h1>
            </div>
            <dl className="stats">
              <div><dt>Documents</dt><dd>{indexed}<span className="faint">/{documents.length}</span></dd></div>
              <div><dt>Evidence</dt><dd>{o?.chunks ?? '—'}<span className="faint"> passages</span></dd></div>
              <div><dt>Facts</dt><dd>{o?.facts ?? '—'}</dd></div>
              <div><dt>Conflicts</dt><dd style={{ color: o?.conflicts_unresolved ? 'var(--uncertain)' : undefined }}>
                {o?.conflicts_unresolved ?? '—'}<span className="faint"> open</span></dd></div>
              <div><dt>Last confidence</dt><dd>{lastConfidence != null ? `${Math.round(lastConfidence * 100)}%` : '—'}</dd></div>
            </dl>
          </header>
          {busy && <IndexingStrip documents={documents} />}
          <div className="station-body">
            {tab === 'investigate' && <InvestigateTab />}
            {tab === 'documents' && <DocumentsTab />}
            {tab === 'conflicts' && <ConflictsTab />}
            {tab === 'graph' && <GraphTab />}
            {tab === 'compare' && <CompareTab />}
            {tab === 'security' && <SecurityTab />}
            {tab === 'timeline' && <TimelineTab />}
          </div>
        </main>

        {source && <Inspector source={source} onClose={() => setSource(null)} />}
        {judgeOpen && <JudgeMode onClose={() => setJudgeOpen(false)} />}
      </div>
    </InvestigationContext.Provider>
  )
}
