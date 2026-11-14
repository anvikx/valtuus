import { useCallback, useEffect, useState, type ReactElement } from 'react'

import {
  getAudit,
  getCart,
  getSession,
  type AuditEntry,
  type AuditTrail,
  type Cart,
} from '../api.ts'
import { entryTime, PHASE_GROUPS, withRequestEntry } from '../components/AuditTimeline.tsx'
import { formatElapsed } from '../format.ts'
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

interface Who {
  readonly label: string
  readonly tone: 'buyer' | 'agent' | 'supplier' | 'rules' | 'user'
}

const BUYER: Who = { label: 'Buyer, via the agent', tone: 'buyer' }
const AGENT: Who = { label: 'Agent', tone: 'agent' }
const SUPPLIER: Who = { label: 'Valio Aimo (mock)', tone: 'supplier' }
const RULES: Who = { label: 'Rules', tone: 'rules' }
const USER: Who = { label: 'Main user', tone: 'user' }

const GATEWAY_ACTOR = 'gateway'

// The gateway records the caller (an agent id or a user id) as the actor, so the step says who
// spoke: the policy check is the rules even when the agent's call ran it, the supplier gives offers
// and confirms the order, only the main user approves or changes the limits. Other steps are the
// agent's.
const WHO_BY_STEP: Readonly<Record<string, Who>> = {
  POLICY: RULES,
  OFFER: SUPPLIER,
  ORDER: SUPPLIER,
  APPROVAL: USER,
  MANDATE_CHANGED: USER,
}

// The answer follows the call on its own line, marked like a reply: "◀ {...}".
const ANSWER_MARK = '◀ '

// The session comes first, so a signed out user never gets a cart request.
async function loadPage(cartId: string): Promise<PageData> {
  await getSession()
  const [cart, audit] = await Promise.all([getCart(cartId), getAudit(cartId)])

  return {
    cart,
    audit,
  }
}

// "gateway" is the rules engine at any step, for example a cart that expires at its deadline.
function whoOf({ step, actor }: AuditEntry): Who {
  if (step === null) {
    return BUYER
  }

  if (actor === GATEWAY_ACTOR) {
    return RULES
  }

  return WHO_BY_STEP[step] ?? AGENT
}

function detailsText({ input, output }: AuditEntry): string | null {
  const parts = [input, output === null ? null : `${ANSWER_MARK}${output}`]
  const text = parts.filter((part) => part !== null).join('\n')
  return text === '' ? null : text
}

function Details({ entry }: { entry: AuditEntry }): ReactElement | null {
  const text = detailsText(entry)
  if (text === null) {
    return null
  }

  return (
    <details className="record-details">
      <summary>Details</summary>
      <pre className="record-code">
        <code>{text}</code>
      </pre>
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
  const { label, tone } = whoOf(entry)

  return (
    <li className="record-line">
      <time className="record-line-time" dateTime={entry.at}>
        {entryTime(entry.at, startedAt)}
      </time>
      <span className={`record-line-who record-who-${tone}`}>{label}</span>
      <div className="record-line-body">
        <p>{entry.sentence}</p>
        <Details entry={entry} />
      </div>
    </li>
  )
}

// The time runs to the order record when there is one, else to the last record.
function Elapsed({ cart, audit }: PageData): ReactElement | null {
  if (audit.elapsedSeconds === null) {
    return null
  }

  const label = cart.status === 'ordered' ? 'From request to order' : 'Time elapsed'
  return (
    <p className="record-elapsed">
      {label}: <strong>{formatElapsed(audit.elapsedSeconds)}</strong>
    </p>
  )
}

function RecordLog({ cart, audit }: PageData): ReactElement {
  const entries = withRequestEntry(audit, cart.requestText)
  const orderLabel = cart.orderId === null ? 'Append only' : `Order ${cart.orderId} · append only`

  return (
    <section aria-label="Record" className="record-panel">
      <div className="record-bar">
        <span className="record-command">&gt; record {cart.id}</span>
        <span>{orderLabel}</span>
      </div>
      {/* Focusable so a keyboard user can scroll the log. */}
      <div className="record-scroll" tabIndex={0}>
        <ol className="record-phases" role="list">
          {PHASE_GROUPS.map(({ phase, label }) => {
            const phaseEntries = entries.filter((entry) => entry.phase === phase)
            return (
              <li key={phase}>
                <h2 className="record-phase">{label}</h2>
                {phaseEntries.length === 0 ? (
                  <p className="record-empty">No records.</p>
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
        <Elapsed cart={cart} audit={audit} />
      </div>
    </section>
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
        <h1 className="title record-title">Record</h1>
        <p className="muted">
          What happened with cart {cart.id}, step by step, in the words the gateway wrote at the
          time.
        </p>
      </header>
      <RecordLog cart={cart} audit={audit} />
      <p className="muted">
        The record shows only what reached the gateway. The buyer&apos;s words are the agent&apos;s
        report. Open Details to see the exact call and the answer.
      </p>
    </main>
  )
}
