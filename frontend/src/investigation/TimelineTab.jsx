import { useQuery } from '@tanstack/react-query'
import { api } from '../api.js'
import { ErrorNote } from '../components/ui.jsx'
import { formatTime } from '../components/status.js'
import { useInvestigation } from './context.js'

const TONE = {
  'security.flagged': 'var(--security)',
  'document.failed': 'var(--contradicted)',
  'collection.analysed': 'var(--uncertain)',
  'question.answered': 'var(--supported)',
}

export default function TimelineTab() {
  const { id, busy } = useInvestigation()
  const q = useQuery({ queryKey: ['timeline', id], queryFn: () => api.timeline(id), refetchInterval: busy ? 2000 : false })
  return (
    <div className="timeline-tab">
      <header>
        <span className="eyebrow">Investigation timeline</span>
        <h2 className="serif">Everything the system did, in order.</h2>
        <p className="muted">Recorded as it happens — uploads, extraction, indexing, security findings, questions and conclusions.</p>
      </header>
      <ErrorNote error={q.error} onRetry={q.refetch} />
      <ol className="timeline">
        {q.data?.map((e) => (
          <li key={e.id} style={{ '--tone': TONE[e.type] || 'var(--paper-3)' }}>
            <span className="tl-time mono">{formatTime(e.at)}</span>
            <span className="tl-dot" />
            <div className="tl-body">
              <p>{e.message}</p>
              {e.detail && <p className="faint mono tl-detail">{e.detail}</p>}
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}
