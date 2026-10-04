import { useEffect } from 'react'
import { Icon } from '../components/ui.jsx'
import { useInvestigation } from './context.js'

// `expect` describes what the live engine returns on the bundled demo set (asserted by the test suite).
export const JUDGE_CASES = [
  {
    n: 0, label: 'Start here', title: 'The complex question', expect: 'Likely eligible · age unverifiable',
    question: 'Is Priya Sharma eligible for the scholarship, and what evidence supports the conclusion?',
    talk: 'Every criterion is checked against cited rules and records — income is corroborated by an OCR-read certificate.',
  },
  {
    n: 1, label: 'Supported', title: 'Strong evidence → high confidence', expect: 'Supported · three agreeing sources',
    question: 'What minimum aggregate marks are required to qualify?',
    talk: 'Three independent documents agree, so confidence is high — and the breakdown shows why.',
  },
  {
    n: 2, label: 'Conflict', title: 'The documents disagree', expect: 'Uncertain · ₹2,50,000 vs ₹2,00,000',
    question: 'What is the annual family income limit for eligibility?',
    talk: '“What if the documents disagree?” — VERITAS won’t choose one blindly. Here is the conflict.',
  },
  {
    n: 3, label: 'Insufficient evidence', title: 'The documents are silent', expect: 'Insufficient evidence · nothing mentions hostels',
    question: 'Does the scholarship cover hostel accommodation fees?',
    talk: 'A chatbot would guess from “does not cover examination fees”. VERITAS refuses and shows the closest passages.',
  },
  {
    n: 4, label: 'Prompt injection', title: 'A document tries to give orders', expect: 'Undetermined · hidden attack neutralised',
    question: 'Is Rahul Verma eligible for the scholarship?',
    talk: 'His statement of purpose hides white text ordering the AI to approve him at 100% confidence. It is flagged and ignored.',
  },
  {
    n: 5, label: 'Comparison', title: '2025 guidelines → 2026 guidelines', expect: 'Changed limit, deadline, benefits; new rules',
    compare: ['Scholarship_Guidelines_2025.pdf', 'Scholarship_Guidelines_2026.pdf'],
    talk: 'Not a text diff: changed values, added requirements, and the supersession clause cited.',
  },
]

export default function JudgeMode({ onClose }) {
  const { runQuestion, documents, setCompareRequest, goTab, indexed } = useInvestigation()

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const run = (c) => {
    if (c.compare) {
      const ids = c.compare.map((name) => documents.find((d) => d.filename === name)?.id)
      setCompareRequest(ids.every(Boolean) ? ids : null)
      goTab('compare')
    } else {
      runQuestion(c.question)
    }
    onClose()
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal judge panel rise" role="dialog" aria-label="Judge mode" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <div>
            <span className="eyebrow">Judge mode</span>
            <h2 className="serif">Five behaviours, one click each.</h2>
            <p className="faint">Each case runs live against the demo investigation. Nothing is pre-computed or cached.</p>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close"><Icon name="close" size={16} /></button>
        </header>
        {indexed === 0 && <p className="form-error">Load the demo investigation (or wait for indexing) before running the cases.</p>}
        <ol className="cases">
          {JUDGE_CASES.map((c) => (
            <li key={c.n}>
              <button className="case" onClick={() => run(c)} disabled={indexed === 0}>
                <span className="case-n mono">{c.n === 0 ? '★' : `0${c.n}`}</span>
                <span className="case-body">
                  <span className="case-label mono">{c.n === 0 ? c.label : `Case ${c.n} · ${c.label}`}</span>
                  <strong>{c.title}</strong>
                  <span className="muted">{c.question ? `“${c.question}”` : `${c.compare[0]} → ${c.compare[1]}`}</span>
                  <span className="faint case-talk">{c.talk}</span>
                </span>
                <span className="case-expect mono">{c.expect}</span>
              </button>
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}
