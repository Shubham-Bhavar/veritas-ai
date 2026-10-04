import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api.js'
import { Empty, ErrorNote, Icon } from '../components/ui.jsx'
import { formatDate } from '../components/status.js'
import { useInvestigation } from './context.js'

const ACCEPT = '.pdf,.docx,.txt,.md,.csv,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp'
const ROLE = { policy: 'Policy / rules', record: 'Record', reference: 'Reference' }
const KIND = { pdf: 'PDF', docx: 'DOCX', text: 'Text', image: 'Image' }

function StatusCell({ d, onRetry }) {
  if (d.status === 'INDEXED') return <span className="doc-status ok">Indexed</span>
  if (d.status === 'FAILED') {
    return (
      <span className="doc-status failed">
        Failed <span className="faint">— {d.errorMessage}</span>
        <button className="link-btn" onClick={onRetry}>Retry</button>
      </span>
    )
  }
  return <span className="doc-status busy"><span className="spinner" /> {d.status === 'QUEUED' ? 'Queued' : 'Indexing'}</span>
}

export default function DocumentsTab() {
  const { id, documents, overview, openSource } = useInvestigation()
  const qc = useQueryClient()
  const input = useRef(null)
  const [drag, setDrag] = useState(false)
  const [results, setResults] = useState(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['investigation', id] })

  const upload = useMutation({
    mutationFn: (files) => api.upload(id, files),
    onSuccess: (r) => { setResults(r.results); refresh() },
  })
  const retry = useMutation({ mutationFn: (docId) => api.retryDocument(id, docId), onSuccess: refresh })
  const remove = useMutation({
    mutationFn: (docId) => api.deleteDocument(id, docId),
    onSuccess: () => { refresh(); qc.invalidateQueries({ queryKey: ['conflicts', id] }) },
  })
  const superseded = new Set(overview?.superseded_documents || [])

  const onFiles = (list) => {
    const files = Array.from(list || [])
    if (files.length) upload.mutate(files)
  }

  return (
    <div className="documents">
      <div
        className={`dropzone ${drag ? 'drag' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles(e.dataTransfer.files) }}
      >
        <Icon name="upload" size={22} />
        <div>
          <strong>Drop documents here</strong>
          <p className="faint">PDF, DOCX, TXT/MD, PNG/JPG scans · up to 25 MB each · validated by content</p>
        </div>
        <button className="btn" onClick={() => input.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? <span className="spinner" /> : null} Choose files
        </button>
        <input ref={input} type="file" multiple accept={ACCEPT} hidden onChange={(e) => { onFiles(e.target.files); e.target.value = '' }} />
      </div>
      <ErrorNote error={upload.error || retry.error || remove.error} />
      {results?.some((r) => !r.accepted) && (
        <ul className="upload-results">
          {results.filter((r) => !r.accepted).map((r) => (
            <li key={r.filename}><strong>{r.filename}</strong> <span className="form-error">rejected — {r.message}</span></li>
          ))}
        </ul>
      )}

      {documents.length === 0 ? (
        <Empty title="No documents yet">Upload the documents you want to investigate. Each is extracted, indexed and scanned for conflicts and hidden instructions.</Empty>
      ) : (
        <div className="doc-table" role="table">
          <div className="doc-row doc-head" role="row">
            <span>Document</span><span>Status</span><span>Role</span><span>Dated</span><span>Extracted</span><span />
          </div>
          {documents.map((d) => (
            <div className="doc-row" role="row" key={d.id}>
              <span className="doc-name">
                <span className="doc-kind mono">{KIND[d.kind] || d.filename.split('.').pop().toUpperCase()}</span>
                <span>
                  <span className="doc-file">{d.filename}</span>
                  {d.title && d.title !== d.filename && <span className="faint doc-title">{d.title}</span>}
                  <span className="doc-badges">
                    {superseded.has(d.id) && <span className="chip warn-chip">superseded</span>}
                    {d.ocrUsed && <span className="chip">OCR · {(d.quality ?? 0).toFixed(2)}</span>}
                    {d.securityFlags > 0 && <span className="chip danger-chip">{d.securityFlags} security flag</span>}
                  </span>
                </span>
              </span>
              <StatusCell d={d} onRetry={() => retry.mutate(d.id)} />
              <span className="muted">{d.role ? ROLE[d.role] : '—'}</span>
              <span className="mono muted">{d.docDate ? formatDate(d.docDate) : '—'}</span>
              <span className="mono muted">
                {d.status === 'INDEXED' ? `${d.pages ? `${d.pages} p · ` : ''}${d.chunks} passages · ${d.facts} facts` : '—'}
              </span>
              <span className="doc-actions">
                {d.status === 'INDEXED' && (
                  <button className="btn btn-ghost btn-sm" title="Open document"
                    onClick={() => openSource({ kind: 'document', documentId: d.id, filename: d.filename, page: d.pages ? 1 : null, chunkId: `${d.id}#c0`, docKind: d.kind })}>
                    <Icon name="page" size={15} />
                  </button>
                )}
                <button className="btn btn-ghost btn-sm btn-danger" aria-label={`Remove ${d.filename}`}
                  onClick={() => { if (confirm(`Remove ${d.filename} from this investigation?`)) remove.mutate(d.id) }}>
                  <Icon name="trash" size={15} />
                </button>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
