import { render, screen, fireEvent } from '@testing-library/react'
import { Confidence } from '../components/Confidence.jsx'
import { StatusPill } from '../components/ui.jsx'

const confidence = {
  score: 0.55, level: 'MODERATE',
  explanation: ['Confidence is limited because 1 conclusion(s) depend on documents that disagree.', 'Capped at 55% because the verdict is uncertain.'],
  signals: [
    { name: 'relevance', value: 0.92, weight: 0.25, text: 'Average relevance of cited evidence is 0.92.' },
    { name: 'agreement', value: 0.3, weight: 0.2, text: '1 conclusion(s) depend on an unresolved conflict.' },
  ],
}

test('confidence shows the score, the reason and an auditable breakdown', () => {
  render(<Confidence confidence={confidence} />)
  expect(screen.getByText('55')).toBeInTheDocument()
  expect(screen.getByText(/depend on documents that disagree/)).toBeInTheDocument()
  expect(screen.queryByText('Agreement between sources')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /how this was calculated/ }))
  expect(screen.getByText('Agreement between sources')).toBeInTheDocument()
  expect(screen.getByText(/never sets the confidence/)).toBeInTheDocument()
})

test('every evidence status has a distinct, labelled pill', () => {
  const statuses = ['SUPPORTED', 'PARTIALLY_SUPPORTED', 'CONTRADICTED', 'UNCERTAIN', 'INSUFFICIENT_EVIDENCE']
  render(<>{statuses.map((s) => <StatusPill key={s} status={s} />)}</>)
  for (const label of ['Supported', 'Partially supported', 'Contradicted', 'Uncertain', 'Insufficient evidence']) {
    expect(screen.getByText(label)).toBeInTheDocument()
  }
})
