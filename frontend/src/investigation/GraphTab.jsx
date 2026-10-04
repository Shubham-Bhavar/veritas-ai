import { useMemo, useState } from 'react'
import { Empty } from '../components/ui.jsx'
import { statusMeta, SEVERITY } from '../components/status.js'
import { useInvestigation } from './context.js'
import { evidenceSource } from './AnswerView.jsx'

const COLS = { document: 30, evidence: 300, conflict: 470, claim: 620, verdict: 930 }
const SIZE = {
  document: [210, 44], evidence: [118, 30], conflict: [128, 46], claim: [270, 58], verdict: [190, 96],
}
const EDGE = {
  contains: ['var(--line-strong)', ''],
  supports: ['var(--supported)', ''],
  contradicts: ['var(--contradicted)', ''],
  context: ['var(--paper-4)', '4 4'],
  conflict: ['var(--contradicted)', '3 3'],
  undermines: ['var(--uncertain)', '6 3'],
  informs: ['var(--paper-3)', ''],
}

function wrap(text, width) {
  const words = text.split(/\s+/)
  const lines = []
  let cur = ''
  for (const w of words) {
    if ((cur + ' ' + w).trim().length > width) {
      lines.push(cur.trim())
      cur = w
    } else cur += ' ' + w
  }
  if (cur.trim()) lines.push(cur.trim())
  return lines
}

function layout(graph) {
  const byType = { document: [], evidence: [], conflict: [], claim: [], verdict: [] }
  graph.nodes.forEach((n) => byType[n.type]?.push(n))
  // Order evidence by the first claim that cites it, documents by their first evidence: fewer crossings.
  const claimOrder = Object.fromEntries(byType.claim.map((c, i) => [c.id, i]))
  const evRank = {}
  graph.edges.forEach((e) => {
    if (e.target.startsWith('cl:') && e.source.startsWith('ev:')) {
      evRank[e.source] = Math.min(evRank[e.source] ?? 1e9, claimOrder[e.target] ?? 1e9)
    }
  })
  byType.evidence.sort((a, b) => (evRank[a.id] ?? 1e9) - (evRank[b.id] ?? 1e9))
  const docRank = {}
  byType.evidence.forEach((ev, i) => { docRank[`doc:${ev.document_id}`] = Math.min(docRank[`doc:${ev.document_id}`] ?? 1e9, i) })
  byType.document.sort((a, b) => (docRank[a.id] ?? 1e9) - (docRank[b.id] ?? 1e9))

  const gap = { document: 14, evidence: 8, conflict: 40, claim: 16, verdict: 0 }
  const heights = Object.entries(byType).map(([t, list]) => list.reduce((h, n) => h + SIZE[t][1] + gap[t], 0))
  const H = Math.max(420, ...heights) + 60
  const pos = {}
  for (const [t, list] of Object.entries(byType)) {
    const total = list.reduce((h) => h + SIZE[t][1] + gap[t], 0)
    let y = (H - total) / 2
    for (const n of list) {
      pos[n.id] = { x: COLS[t], y, w: SIZE[t][0], h: SIZE[t][1] }
      y += SIZE[t][1] + gap[t]
    }
  }
  return { pos, H, byType }
}

export default function GraphTab() {
  const { answer, openSource, goTab, documents } = useInvestigation()
  const [hover, setHover] = useState(null)
  const [pinned, setPinned] = useState(null)
  const graph = answer?.graph
  const lay = useMemo(() => (graph ? layout(graph) : null), [graph])

  const focus = pinned || hover
  const connected = useMemo(() => {
    if (!graph || !focus) return null
    const out = new Set([focus])
    const walk = (dir) => {
      const queue = [focus]
      while (queue.length) {
        const cur = queue.shift()
        for (const e of graph.edges) {
          const [from, to] = dir === 'down' ? [e.source, e.target] : [e.target, e.source]
          if (from === cur && !out.has(to)) {
            out.add(to)
            queue.push(to)
          }
        }
      }
    }
    walk('down')
    walk('up')
    return out
  }, [graph, focus])

  if (!answer) {
    return (
      <Empty title="The graph follows an answer"
        action={<button className="btn" onClick={() => goTab('investigate')}>Ask a question</button>}>
        Ask a question first. The graph then shows exactly which documents, passages and conflicts produced each claim and the verdict.
      </Empty>
    )
  }
  const { pos, H } = lay
  const nodeById = Object.fromEntries(graph.nodes.map((n) => [n.id, n]))
  const detail = focus ? nodeById[focus] : null
  const evidence = Object.fromEntries(answer.evidence.map((e) => [e.id, e]))

  const click = (n) => {
    if (n.type === 'evidence') openSource(evidenceSource(evidence[n.evidence_id]))
    else if (n.type === 'document') {
      const d = documents.find((x) => x.id === n.document_id)
      openSource({ kind: 'document', documentId: n.document_id, filename: n.label, page: d?.pages ? 1 : null, chunkId: `${n.document_id}#c0`, docKind: d?.kind })
    } else if (n.type === 'conflict') goTab('conflicts')
    else setPinned((p) => (p === n.id ? null : n.id))
  }

  return (
    <div className="graph-tab">
      <header className="graph-head">
        <div>
          <span className="eyebrow">Evidence graph</span>
          <h2 className="serif">How “{answer.verdict.headline}” was reached.</h2>
          <p className="faint">Hover to trace a path. Click a passage to inspect its source, a claim to pin its path.</p>
        </div>
        <ul className="legend">
          <li><i style={{ background: 'var(--supported)' }} />supports</li>
          <li><i style={{ background: 'var(--contradicted)' }} />contradicts</li>
          <li><i className="dashed" style={{ borderColor: 'var(--contradicted)' }} />conflict</li>
          <li><i className="dashed" style={{ borderColor: 'var(--uncertain)' }} />undermines</li>
          <li><i className="dashed" style={{ borderColor: 'var(--paper-4)' }} />context</li>
        </ul>
      </header>
      <div className="graph-canvas panel">
        <div className="graph-cols mono faint">
          <span style={{ left: `${(COLS.document / 1160) * 100}%` }}>DOCUMENTS</span>
          <span style={{ left: `${(COLS.evidence / 1160) * 100}%` }}>EVIDENCE</span>
          <span style={{ left: `${(COLS.conflict / 1160) * 100}%` }}>CONFLICTS</span>
          <span style={{ left: `${(COLS.claim / 1160) * 100}%` }}>CLAIMS</span>
          <span style={{ left: `${(COLS.verdict / 1160) * 100}%` }}>VERDICT</span>
        </div>
        <svg viewBox={`0 0 1160 ${H}`} role="img" aria-label="Evidence graph">
          {graph.edges.map((e, i) => {
            const a = pos[e.source]
            const b = pos[e.target]
            if (!a || !b) return null
            const [color, dash] = EDGE[e.type] || EDGE.informs
            const x1 = a.x + a.w
            const y1 = a.y + a.h / 2
            const x2 = b.x
            const y2 = b.y + b.h / 2
            const mx = (x1 + x2) / 2
            const dim = connected && !(connected.has(e.source) && connected.has(e.target))
            return (
              <path key={i} d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} fill="none" stroke={color}
                strokeWidth={dim ? 1 : 1.6} strokeDasharray={dash} opacity={dim ? 0.12 : 0.85} />
            )
          })}
          {graph.nodes.map((n) => {
            const p = pos[n.id]
            if (!p) return null
            const dim = connected && !connected.has(n.id)
            return (
              <g key={n.id} transform={`translate(${p.x},${p.y})`} opacity={dim ? 0.25 : 1} className="g-node"
                onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} onClick={() => click(n)}
                tabIndex={0} role="button" aria-label={`${n.type}: ${n.label}`}
                onKeyDown={(ev) => ev.key === 'Enter' && click(n)}>
                <NodeShape n={n} w={p.w} h={p.h} pinned={pinned === n.id} />
              </g>
            )
          })}
        </svg>
      </div>
      <div className="graph-detail card">
        {detail ? (
          <>
            <span className="eyebrow">{detail.type}</span>
            <p>{detail.type === 'evidence' ? `“${evidence[detail.evidence_id]?.quote}”` : detail.label}</p>
            {detail.type === 'evidence' && <p className="faint">{evidence[detail.evidence_id]?.why}</p>}
          </>
        ) : (
          <p className="faint">{graph.nodes.length} nodes · {graph.edges.length} relationships. Every node is a real document, passage, claim or conflict from this answer.</p>
        )}
      </div>
    </div>
  )
}

function NodeShape({ n, w, h, pinned }) {
  if (n.type === 'document') {
    return (
      <>
        <rect width={w} height={h} rx="8" fill="var(--ink-2)" stroke={pinned ? 'var(--paper)' : 'var(--line-strong)'} />
        <path d={`M12 11h10l5 5v17H12z`} fill="none" stroke="var(--paper-3)" />
        <text x="36" y="20" className="g-title">{n.label.length > 24 ? `${n.label.slice(0, 23)}…` : n.label}</text>
        <text x="36" y="34" className="g-sub">{n.role}{n.superseded ? ' · superseded' : ''}</text>
      </>
    )
  }
  if (n.type === 'evidence') {
    const color = n.stance === 'contradicts' ? 'var(--contradicted)' : n.stance === 'context' ? 'var(--paper-4)' : 'var(--supported)'
    return (
      <>
        <rect width={w} height={h} rx={h / 2} fill="var(--ink-1)" stroke={pinned ? 'var(--paper)' : color} strokeOpacity="0.8" />
        <circle cx="15" cy={h / 2} r="4" fill={color} />
        <text x="26" y={h / 2 + 4} className="g-title mono-svg">{n.label}{n.page ? ` · p.${n.page}` : ''}</text>
      </>
    )
  }
  if (n.type === 'conflict') {
    const s = SEVERITY[n.severity] || SEVERITY.LOW
    return (
      <>
        <rect width={w} height={h} rx="6" fill={s.bg} stroke={s.color} strokeDasharray={n.status === 'RESOLVED' ? '4 3' : ''} />
        <text x="10" y="18" className="g-sub" fill={s.color}>⇄ {n.status === 'RESOLVED' ? 'RESOLVED' : n.severity}</text>
        <text x="10" y="34" className="g-title">{n.label.length > 19 ? `${n.label.slice(0, 18)}…` : n.label}</text>
      </>
    )
  }
  if (n.type === 'claim') {
    const m = statusMeta(n.status)
    const lines = wrap(n.label, 40).slice(0, 2)
    return (
      <>
        <rect width={w} height={h} rx="8" fill="var(--ink-2)" stroke={pinned ? 'var(--paper)' : 'var(--line-strong)'} />
        <rect width="4" height={h} rx="2" fill={m.color} />
        <text x="14" y="17" className="g-sub" fill={m.color}>{m.mark} {m.short.toUpperCase()}</text>
        {lines.map((l, i) => <text key={i} x="14" y={33 + i * 14} className="g-title">{l}{i === 1 && n.label.length > 80 ? '…' : ''}</text>)}
      </>
    )
  }
  const m = statusMeta(n.status)
  const lines = wrap(n.label, 18).slice(0, 2)
  return (
    <>
      <rect width={w} height={h} rx="12" fill={m.bg} stroke={m.color} strokeWidth="1.5" />
      <text x="16" y="24" className="g-sub" fill={m.color}>VERDICT</text>
      {lines.map((l, i) => <text key={i} x="16" y={52 + i * 22} className="g-verdict">{l}</text>)}
    </>
  )
}
