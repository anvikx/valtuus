import { useEffect, useRef, useState, type ReactElement } from 'react'

import { listAgents, stopAgent, type Agent } from '../api.ts'
import { formatDate, formatDateTime, formatHourMinute } from '../format.ts'
import { isSignedOut, redirectToLogin } from '../session.ts'

// The backend stores the last call at most once a minute, so a working agent can look one
// minute old. Two minutes still reads as now.
const ACTIVE_WINDOW_MS = 2 * 60 * 1000

type LoadState =
  | { readonly kind: 'loading' }
  | { readonly kind: 'failed' }
  | { readonly kind: 'ready'; readonly agents: readonly Agent[]; readonly loadedAt: number }

/** "Active now", "Last used 14:03", "Last used Fri 13 Nov 09:12" or "Never used". */
function usageText({ isActive, lastUsedAt }: Agent, now: number): string {
  if (lastUsedAt === null) {
    return 'Never used'
  }

  // A stopped agent's calls are refused, so it is never "active".
  if (isActive && now - Date.parse(lastUsedAt) < ACTIVE_WINDOW_MS) {
    return 'Active now'
  }

  const isToday = formatDate(lastUsedAt) === formatDate(new Date(now).toISOString())
  return `Last used ${isToday ? formatHourMinute(lastUsedAt) : formatDateTime(lastUsedAt)}`
}

interface AgentRowProps {
  readonly agent: Agent
  readonly now: number
  readonly isStopping: boolean
  readonly onStop: (agent: Agent) => void
}

function focusOnMount(element: HTMLElement | null): void {
  element?.focus()
}

function AgentRow({ agent, now, isStopping, onStop }: AgentRowProps): ReactElement {
  const [isConfirming, setIsConfirming] = useState(false)
  const stopButtonRef = useRef<HTMLButtonElement>(null)
  const usage = usageText(agent, now)

  function cancel(): void {
    setIsConfirming(false)
    // The confirm buttons go away, so focus goes back to the button that opened them.
    requestAnimationFrame(() => {
      stopButtonRef.current?.focus()
    })
  }

  return (
    <li className="agent-row">
      <div className="agent-row-head">
        <div className="agent-name">
          <strong>{agent.name}</strong>
          <span className="muted">{agent.isActive ? usage : `Stopped · ${usage}`}</span>
        </div>
        {agent.isActive && !isConfirming ? (
          <button
            className="button button-outline"
            ref={stopButtonRef}
            type="button"
            onClick={() => {
              setIsConfirming(true)
            }}
          >
            Stop agent
          </button>
        ) : null}
      </div>
      {agent.isActive && isConfirming ? (
        <div className="agent-confirm">
          <p ref={focusOnMount} tabIndex={-1}>
            Stop {agent.name}? Its next call is refused. To use it again, it needs a new key.
          </p>
          <div className="agent-confirm-actions">
            <button
              className="button button-deny"
              disabled={isStopping}
              type="button"
              onClick={() => {
                onStop(agent)
              }}
            >
              {isStopping ? 'Stopping' : 'Stop agent'}
            </button>
            <button className="button button-text" type="button" onClick={cancel}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </li>
  )
}

// The agents of the buyer, with the time of their last call and a stop button.
export function AgentList(): ReactElement {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [stoppingId, setStoppingId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [isStopFailed, setIsStopFailed] = useState(false)
  // A ref, not state: a second tap before React renders still reads the old stoppingId.
  const isBusyRef = useRef(false)

  useEffect(() => {
    let isCurrent = true
    listAgents().then(
      (agents) => {
        if (isCurrent) {
          setState({ kind: 'ready', agents, loadedAt: Date.now() })
        }
      },
      // Only the session call may send the user to login, so a failed list only says so.
      () => {
        if (isCurrent) {
          setState({ kind: 'failed' })
        }
      },
    )
    return () => {
      isCurrent = false
    }
  }, [])

  async function stop(agent: Agent): Promise<void> {
    if (isBusyRef.current) {
      return
    }

    isBusyRef.current = true
    setStoppingId(agent.id)
    setIsStopFailed(false)
    try {
      const agents = await stopAgent(agent.id)
      setState({ kind: 'ready', agents, loadedAt: Date.now() })
      setNotice(`${agent.name} is stopped. Its next call is refused.`)
    } catch (error: unknown) {
      if (isSignedOut(error)) {
        redirectToLogin()
        return
      }

      setIsStopFailed(true)
    } finally {
      isBusyRef.current = false
      setStoppingId(null)
    }
  }

  return (
    <section aria-labelledby="agents-heading" className="mandate-section">
      <h2 className="heading" id="agents-heading">
        Agents
      </h2>
      {/* The stop button is gone after a stop, so focus moves to the result. */}
      {notice === null ? null : (
        <p className="mandate-saved" key={notice} ref={focusOnMount} role="status" tabIndex={-1}>
          {notice}
        </p>
      )}
      {isStopFailed ? (
        <p className="alert" role="alert">
          The agent could not be stopped. Try again.
        </p>
      ) : null}
      {state.kind === 'loading' ? (
        <p className="muted" role="status">
          Loading the agents.
        </p>
      ) : null}
      {state.kind === 'failed' ? <p className="muted">The agents could not be loaded.</p> : null}
      {state.kind === 'ready' && state.agents.length === 0 ? (
        <p className="muted">No agent has a key.</p>
      ) : null}
      {state.kind === 'ready' && state.agents.length > 0 ? (
        <ul className="agent-list" role="list">
          {state.agents.map((agent) => (
            <AgentRow
              agent={agent}
              isStopping={stoppingId === agent.id}
              key={agent.id}
              now={state.loadedAt}
              onStop={(target) => {
                void stop(target)
              }}
            />
          ))}
        </ul>
      ) : null}
    </section>
  )
}
