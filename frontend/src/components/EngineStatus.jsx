import { useQuery } from '@tanstack/react-query'
import { api } from '../api.js'

/** Shows which engines are actually live, so a fallback is never mistaken for the real thing. */
export function EngineStatus({ compact = false }) {
  const { data, isError } = useQuery({ queryKey: ['status'], queryFn: api.status, refetchInterval: 30_000 })
  const ai = data?.ai
  const up = ai && ai.status !== 'unavailable'
  const items = up
    ? [
        ['Evidence store', ai.store?.ok ? (ai.store.backend === 'pgvector' ? 'PostgreSQL + pgvector' : 'SQLite (local)') : 'down', ai.store?.ok],
        ['Embeddings', ai.semantic_embeddings ? ai.embeddings.split('/').pop() : 'lexical fallback', ai.semantic_embeddings],
        ['Re-ranker', ai.reranker === 'unavailable' || ai.reranker === 'disabled' ? 'off' : 'cross-encoder', ai.reranker !== 'unavailable'],
        ['OCR', ai.ocr ? 'RapidOCR' : ai.models === 'loading' ? 'loading…' : 'unavailable', !!ai.ocr],
        ['Reasoning', ai.llm?.configured ? `Claude (${ai.llm.model}) + verification` : 'Extractive engine (no LLM key)', true],
      ]
    : []
  if (compact) {
    const ok = up && ai.status === 'ok'
    return (
      <span className="engine-dot" title={up ? items.map((i) => `${i[0]}: ${i[1]}`).join('\n') : 'Evidence service unavailable'}>
        <span className="dot" style={{ background: ok ? 'var(--supported)' : up ? 'var(--uncertain)' : 'var(--contradicted)' }} />
        {up ? (ai.llm?.configured ? 'Claude + engine' : 'Extractive engine') : 'AI offline'}
      </span>
    )
  }
  return (
    <section className="engine-status">
      <h2 className="eyebrow">Engines</h2>
      {isError || (data && !up) ? (
        <p className="form-error">The evidence service is unavailable. Uploads will queue and questions will fail until it is back.</p>
      ) : (
        <dl>
          {items.map(([k, v, ok]) => (
            <div key={k}>
              <dt className="faint">{k}</dt>
              <dd><span className="dot" style={{ background: ok ? 'var(--supported)' : 'var(--uncertain)' }} />{v}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  )
}
