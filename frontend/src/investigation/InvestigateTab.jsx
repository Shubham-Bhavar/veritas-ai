import { useQuery } from '@tanstack/react-query'
import { api } from '../api.js'
import { Empty, ErrorNote, Icon, StatusPill } from '../components/ui.jsx'
import { formatTime } from '../components/status.js'
import { useInvestigation } from './context.js'
import AnswerView from './AnswerView.jsx'
import { JUDGE_CASES } from './JudgeMode.jsx'

export default function InvestigateTab() {
  const { id, investigation, ask, runQuestion, answer, draft, setDraft, indexed, busy, openAnswer, goTab } = useInvestigation()
  const history = useQuery({ queryKey: ['history', id], queryFn: () => api.history(id) })
  const suggestions = investigation?.demo
    ? JUDGE_CASES.filter((c) => c.question).map((c) => c.question)
    : ['What are the key requirements in these documents?', 'Which deadlines are stated, and do the documents agree?']

  const submit = (e) => {
    e.preventDefault()
    const q = draft.trim()
    if (q.length >= 3 && !ask.isPending) runQuestion(q)
  }

  return (
    <div className="investigate">
      <div className="investigate-main">
        <form className="composer panel" onSubmit={submit}>
          <label htmlFor="question" className="eyebrow">Ask the collection</label>
          <textarea
            id="question" className="composer-input" rows={2} maxLength={1000} value={draft}
            placeholder="e.g. Is Priya Sharma eligible for the scholarship, and what evidence supports the conclusion?"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) submit(e) }}
          />
          <div className="composer-foot">
            <div className="suggestions">
              {answer && !ask.isPending ? (
                <span className="faint suggestions-hint">Ask a follow-up, or open <strong>Judge mode</strong> for the guided cases.</span>
              ) : suggestions.map((s) => (
                <button type="button" key={s} className="suggestion" onClick={() => runQuestion(s)} disabled={ask.isPending || indexed === 0}>
                  {s}
                </button>
              ))}
            </div>
            <button className="btn btn-primary" type="submit" disabled={ask.isPending || draft.trim().length < 3 || indexed === 0}>
              {ask.isPending ? <span className="spinner" /> : <Icon name="investigate" size={16} />} Investigate
            </button>
          </div>
          {indexed === 0 && (
            <p className="faint composer-hint">
              {busy ? 'Documents are being indexed — you can ask as soon as the first one is ready.' : <>No indexed documents yet. <button type="button" className="link-btn" onClick={() => goTab('documents')}>Upload documents</button></>}
            </p>
          )}
        </form>

        <ErrorNote error={ask.error} />

        {ask.isPending && (
          <div className="working panel" role="status" aria-live="polite">
            <div className="working-head"><span className="spinner" /> Investigating “{ask.variables}”</div>
            <p className="faint working-note">
              The engine is retrieving passages, checking facts against every document, evaluating conflicts and computing
              confidence. Usually 1–4 seconds; the measured time of each step is shown with the answer.
            </p>
          </div>
        )}

        {!ask.isPending && answer && <AnswerView answer={answer} key={answer.question_id} />}

        {!ask.isPending && !answer && (
          <Empty title="Ask a question to start the investigation">
            VERITAS answers with a verdict, the claims behind it, the exact sources, any conflicts between documents,
            and a confidence you can audit. Try a suggestion above, or open <strong>Judge mode</strong> for the guided cases.
          </Empty>
        )}
      </div>

      <aside className="history">
        <h2 className="eyebrow">Question log</h2>
        {history.data?.length === 0 && <p className="faint">Questions you ask are kept here with their verdicts.</p>}
        <ul>
          {history.data?.map((h) => (
            <li key={h.id}>
              <button className={`history-item ${answer?.question_id === h.id ? 'active' : ''}`} onClick={() => openAnswer(h.id)}>
                <span className="history-q">{h.question}</span>
                <span className="history-meta">
                  <StatusPill status={h.status} size="xs" />
                  <span className="mono faint">{Math.round(h.confidence * 100)}% · {formatTime(h.askedAt)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  )
}
