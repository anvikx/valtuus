import type { ReactElement } from 'react'

import type { FlowPhase } from '../api.ts'
import { PHASE_GROUPS } from './AuditTimeline.tsx'
import { Icon, type IconName } from './Icon.tsx'

interface FlowStepsProps {
  // The step that waits for the user. Steps before it are done. Null: every step is done.
  readonly currentPhase: FlowPhase | null
  // The last step stopped the flow: the cart is closed and was not ordered.
  readonly stopTone?: StopTone
}

export type StopTone = 'deny' | 'muted'

type StepState = 'done' | 'current' | 'upcoming' | StopTone

const STEP_SUFFIX: Readonly<Record<StepState, string>> = {
  done: ', done',
  current: ', waits for you',
  upcoming: ', not reached',
  deny: ', stopped',
  muted: ', stopped',
}

const STEP_ICON: Readonly<Partial<Record<StepState, IconName>>> = {
  done: 'check',
  deny: 'cross',
  muted: 'minus',
}

function stepState(phase: FlowPhase, currentPhase: FlowPhase | null): StepState {
  if (currentPhase === null) {
    return 'done'
  }

  const index = PHASE_GROUPS.findIndex((group) => group.phase === phase)
  const currentIndex = PHASE_GROUPS.findIndex((group) => group.phase === currentPhase)
  if (index === currentIndex) {
    return 'current'
  }

  return index < currentIndex ? 'done' : 'upcoming'
}

const LAST_PHASE: FlowPhase = 'approval'

export function FlowSteps({ currentPhase, stopTone }: FlowStepsProps): ReactElement {
  return (
    // role list: Safari drops list semantics, and so the label, when list-style is none.
    <ol className="flow-steps" role="list" aria-label="Order flow">
      {PHASE_GROUPS.map(({ phase, label }) => {
        const isStopped = stopTone !== undefined && phase === LAST_PHASE
        const state = isStopped ? stopTone : stepState(phase, currentPhase)

        return (
          <li
            className={`flow-step flow-step-${state}`}
            key={phase}
            aria-current={isStopped ? 'step' : undefined}
          >
            <span className="flow-step-name">
              {STEP_ICON[state] === undefined ? null : (
                <Icon className="flow-step-icon" name={STEP_ICON[state]} />
              )}
              {label}
              <span className="sr-only">{STEP_SUFFIX[state]}</span>
            </span>
          </li>
        )
      })}
    </ol>
  )
}
