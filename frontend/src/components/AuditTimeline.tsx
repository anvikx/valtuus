import type { ReactElement } from 'react'

import type { AuditEntry, AuditTrail, CartStatus, FlowPhase } from '../api.ts'
import { formatClock, formatDate, formatElapsed } from '../format.ts'
import { Icon } from './Icon.tsx'

interface PhaseGroup {
  readonly phase: FlowPhase
  readonly label: string
}

export const PHASE_GROUPS: readonly PhaseGroup[] = [
  { phase: 'request', label: '1 Request' },
  { phase: 'lookup', label: '2 Lookup' },
  { phase: 'order', label: '3 Order' },
  { phase: 'approval', label: '4 Approval' },
]

const REQUEST_ENTRY_ID = 'request'

interface AuditTimelineProps {
  readonly cartId: string
  readonly audit: AuditTrail | null
  readonly requestText: string
  readonly status: CartStatus
  readonly initialState?: 'open' | 'collapsed'
}

// No audit step maps to REQUEST yet. Until one does, the Request group shows
// the buyer's words at the time of the first record.
export function withRequestEntry(audit: AuditTrail, requestText: string): readonly AuditEntry[] {
  const hasRequestRecord = audit.entries.some((entry) => entry.phase === 'request')
  if (hasRequestRecord || audit.startedAt === null) {
    return audit.entries
  }

  const requestEntry: AuditEntry = {
    id: REQUEST_ENTRY_ID,
    phase: 'request',
    sentence: `The buyer asked: "${requestText}"`,
    at: audit.startedAt,
    actor: null,
    input: null,
    output: null,
  }
  return [requestEntry, ...audit.entries]
}

// A record on a later day than the first one also shows its date, so an expiry the next day
// does not read as the same morning.
export function entryTime(at: string, startedAt: string | null): string {
  const isSameDay = startedAt === null || formatDate(at) === formatDate(startedAt)
  return isSameDay ? formatClock(at) : `${formatDate(at)} ${formatClock(at)}`
}

function EntryList({
  entries,
  startedAt,
}: {
  entries: readonly AuditEntry[]
  startedAt: string | null
}): ReactElement {
  if (entries.length === 0) {
    return <p className="muted">No records.</p>
  }

  return (
    <ol className="timeline-entries">
      {entries.map((entry) => (
        <li className="timeline-entry" key={entry.id}>
          <time className="timeline-time" dateTime={entry.at}>
            {entryTime(entry.at, startedAt)}
          </time>
          <p>{entry.sentence}</p>
        </li>
      ))}
    </ol>
  )
}

// The elapsed time runs to the order record when there is one, else to the last record.
export function elapsedText(seconds: number | null, status: CartStatus): string | null {
  if (seconds === null) {
    return null
  }

  const elapsed = formatElapsed(seconds)
  return status === 'ordered' ? `${elapsed} from request to order` : `${elapsed} elapsed`
}

// What happened to the cart, in 4 groups, one plain sentence per audit record.
export function AuditTimeline({
  cartId,
  audit,
  requestText,
  status,
  initialState = 'open',
}: AuditTimelineProps): ReactElement {
  if (audit === null) {
    return <p className="muted">The timeline could not be loaded.</p>
  }

  const entries = withRequestEntry(audit, requestText)
  const elapsed = elapsedText(audit.elapsedSeconds, status)

  return (
    <details className="record" open={initialState === 'open'}>
      <summary className="record-summary">
        <span>Record {elapsed === null ? null : <span className="muted">{elapsed}</span>}</span>
        <Icon className="record-chevron" name="chevron" />
      </summary>
      <ol className="stack timeline">
        {PHASE_GROUPS.map(({ phase, label }) => (
          <li className="stack-tight" key={phase}>
            <h3 className="label">{label}</h3>
            <EntryList
              entries={entries.filter((entry) => entry.phase === phase)}
              startedAt={audit.startedAt}
            />
          </li>
        ))}
      </ol>
      <a className="record-link" href={`/carts/${encodeURIComponent(cartId)}/record`}>
        Open full record
      </a>
    </details>
  )
}
