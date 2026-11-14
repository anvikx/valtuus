import { useCallback, useEffect, useState, type ReactElement } from 'react'

import {
  getAudit,
  getCart,
  getSession,
  type AuditEntry,
  type AuditTrail,
  type Cart,
} from '../api.ts'
import {
  elapsedText,
  entryTime,
  PHASE_GROUPS,
  withRequestEntry,
} from '../components/AuditTimeline.tsx'
import { isSignedOut, redirectToLogin } from '../session.ts'

interface RecordPageProps {
  readonly cartId: string
}

interface PageData {
  readonly cart: Cart
  readonly audit: AuditTrail
}

type LoadState =
  | { readonly kind: 'loading' }
  | { readonly kind: 'failed' }
  | { readonly kind: 'ready'; readonly data: PageData }

const REQUEST_ACTOR = 'Buyer, via the agent'

// The session comes first, so a signed out user never gets a cart request.
async function loadPage(cartId: string): Promise<PageData> {
  await getSession()
  const [cart, audit] = await Promise.all([getCart(cartId), getAudit(cartId)])

  return {
    cart,
    audit,
  }
}

function CodeBlock({ label, code }: { label: string; code: string | null }): ReactElement | null {
  if (code === null) {
    return null
  }

  return (
    <div className="stack-tight">
      <p className="label">{label}</p>
      <pre className="record-code">
        <code>{code}</code>
      </pre>
    </div>
  )
}

function Details({ entry }: { entry: AuditEntry }): ReactElement | null {
  if (entry.input === null && entry.output === null) {
    return null
  }

  return (
    <details className="record-details">
      <summary>Details</summary>
      <div className="stack-tight">
        <CodeBlock label="The exact call" code={entry.input} />
        <CodeBlock label="The answer" code={entry.output} />
      </div>
    </details>
  )
}

function RecordLine({
  entry,
  startedAt,
}: {
  entry: AuditEntry
  startedAt: string | null
}): ReactElement {
  return (
    <li className="record-line">
      <time className="record-line-time" dateTime={entry.at}>
        {entryTime(entry.at, startedAt)}
      </time>
      <span className="record-line-who">{entry.actor ?? REQUEST_ACTOR}</span>
      <div className="record-line-body">
        <p>{entry.sentence}</p>
        <Details entry={entry} />
      </div>
    </li>
  )
}

function RecordBody({ cart, audit }: PageData): ReactElement {
  const entries = withRequestEntry(audit, cart.requestText)
  const elapsed = elapsedText(audit.elapsedSeconds, cart.status)

  return (
    <>
      <ol className="record-phases" role="list">
        {PHASE_GROUPS.map(({ phase, label }) => {
          const phaseEntries = entries.filter((entry) => entry.phase === phase)
          return (
            <li className="stack-tight" key={phase}>
              <h2 className="label">{label}</h2>
              {phaseEntries.length === 0 ? (
                <p className="muted">No records.</p>
              ) : (
                <ol className="record-lines" role="list">
                  {phaseEntries.map((entry) => (
                    <RecordLine key={entry.id} entry={entry} startedAt={audit.startedAt} />
                  ))}
                </ol>
              )}
            </li>
          )
        })}
      </ol>
      {elapsed === null ? null : <p className="record-elapsed">{elapsed}</p>}
    </>
  )
}

// A full page for the audit log of one cart. The approval page links here.
export function RecordPage({ cartId }: RecordPageProps): ReactElement {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(
    () =>
      loadPage(cartId).then(
        (data) => {
          setState({ kind: 'ready', data })
        },
        (error: unknown) => {
          if (isSignedOut(error)) {
            redirectToLogin()
            return
          }

          setState({ kind: 'failed' })
        },
      ),
    [cartId],
  )

  useEffect(() => {
    void load()
  }, [load])

  if (state.kind === 'loading') {
    return (
      <main>
        <p className="muted" role="status">
          Loading the record.
        </p>
      </main>
    )
  }

  if (state.kind === 'failed') {
    return (
      <main className="stack">
        <p className="alert" role="alert">
          The record could not be loaded.
        </p>
        <button
          className="button button-primary"
          type="button"
          onClick={() => {
            setState({ kind: 'loading' })
            void load()
          }}
        >
          Retry
        </button>
      </main>
    )
  }

  const { cart, audit } = state.data

  return (
    <main className="record-page stack">
      <a href={`/carts/${encodeURIComponent(cartId)}`}>Back to the order</a>
      <header className="stack-tight">
        <h1 className="title">Record</h1>
        <p className="muted">What happened to this request, step by step.</p>
        <blockquote className="record-request">{cart.requestText}</blockquote>
      </header>
      <RecordBody cart={cart} audit={audit} />
    </main>
  )
}
