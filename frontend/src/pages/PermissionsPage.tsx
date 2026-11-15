import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react'

import {
  ApiError,
  getMandate,
  getSession,
  saveMandate,
  type Mandate,
  type MandateEdit,
} from '../api.ts'
import { MandateForm } from '../components/MandateForm.tsx'
import { MandateView, POLICY_WORDS, autoOrderWords } from '../components/MandateView.tsx'
import { money } from '../components/ResultScreen.tsx'
import { formatAllergen, formatAttribute } from '../format.ts'
import { isSignedOut, redirectToLogin } from '../session.ts'

interface Loaded {
  readonly buyerId: string
  readonly mandate: Mandate
}

type LoadState =
  | { readonly kind: 'loading' }
  | { readonly kind: 'failed' }
  | { readonly kind: 'ready'; readonly data: Loaded }

type Mode =
  | { readonly kind: 'view' }
  | { readonly kind: 'edit'; readonly isFailed: boolean }
  // The mandate before the save, to say what changed.
  | { readonly kind: 'saved'; readonly before: Mandate }

const CURRENCY = 'EUR'

async function loadMandate(): Promise<Loaded> {
  // The session comes first. The mandate read below takes an agent key on the real backend
  // (backend gap: it needs a session route), so its 401 means "no route for you", not "sign
  // in". Without this order that 401 would send a signed in user to login in a loop.
  const session = await getSession()
  try {
    return {
      buyerId: session.buyerId,
      mandate: await getMandate(),
    }
  } catch (error: unknown) {
    throw error instanceof ApiError && error.kind === 'unauthenticated'
      ? new ApiError('failed')
      : error
  }
}

// A mode change remounts the title (key). Focus moves to it, so a screen reader reads the new
// state and keyboard focus is not lost.
function focusOnMount(title: HTMLHeadingElement | null): void {
  title?.focus()
}

function listOrNone(values: readonly string[]): string {
  return values.length === 0 ? 'none' : values.join(', ')
}

// Sentences for the fields that differ. Money shows as sent.
function changesBetween(before: Mandate, after: Mandate): string[] {
  const changes: string[] = []
  if (before.canAutoOrder !== after.canAutoOrder) {
    changes.push(`Orders by itself: ${autoOrderWords(after.canAutoOrder)}.`)
  }

  if (before.maxOrder !== after.maxOrder) {
    changes.push(
      `Per order: from ${money(before.maxOrder, CURRENCY)} to ${money(after.maxOrder, CURRENCY)}.`,
    )
  }

  if (before.maxPerDay !== after.maxPerDay) {
    changes.push(
      `Per delivery day: from ${money(before.maxPerDay, CURRENCY)} to ${money(after.maxPerDay, CURRENCY)}.`,
    )
  }

  if (before.preferredBrands.join() !== after.preferredBrands.join()) {
    changes.push(`Preferred brands: ${listOrNone(after.preferredBrands)}.`)
  }

  if ([...before.required].sort().join() !== [...after.required].sort().join()) {
    changes.push(`Every product must be: ${listOrNone(after.required.map(formatAttribute))}.`)
  }

  if ([...before.forbidden].sort().join() !== [...after.forbidden].sort().join()) {
    changes.push(`Does not contain: ${listOrNone(after.forbidden.map(formatAllergen))}.`)
  }

  if (before.unknownPolicy !== after.unknownPolicy) {
    changes.push(`Allergen data missing: ${POLICY_WORDS[after.unknownPolicy]}.`)
  }

  return changes
}

interface SavedNoticeProps {
  readonly before: Mandate
  readonly after: Mandate
}

function SavedNotice({ before, after }: SavedNoticeProps): ReactElement {
  const changes = changesBetween(before, after)

  return (
    <div className="mandate-saved" role="status">
      <p>
        <strong>Saved as version {after.version}.</strong> Open carts are not changed. The agent's
        next checkout uses the new rules.
      </p>
      {changes.length === 0 ? null : (
        <ul className="mandate-bullets">
          {changes.map((change) => (
            <li key={change}>{change}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

interface ReadyProps {
  readonly data: Loaded
  readonly onSaved: (mandate: Mandate) => void
}

function PermissionsView({ data, onSaved }: ReadyProps): ReactElement {
  const { buyerId, mandate } = data
  const [mode, setMode] = useState<Mode>({ kind: 'view' })
  const [isSaving, setIsSaving] = useState(false)
  // A ref, not state: a second tap before React renders still reads the old isSaving.
  const isBusyRef = useRef(false)
  const isEditing = mode.kind === 'edit'

  async function save(edit: MandateEdit): Promise<void> {
    if (isBusyRef.current) {
      return
    }

    isBusyRef.current = true
    setIsSaving(true)
    try {
      const saved = await saveMandate(edit)
      setMode({ kind: 'saved', before: mandate })
      onSaved(saved)
    } catch (error: unknown) {
      if (isSignedOut(error)) {
        redirectToLogin()
        return
      }

      setMode({ kind: 'edit', isFailed: true })
    } finally {
      isBusyRef.current = false
      setIsSaving(false)
    }
  }

  const subtitle = isEditing
    ? `${buyerId} · now version ${mandate.version}`
    : `${buyerId} · rules version ${mandate.version}`

  return (
    <main className="mandate">
      {mode.kind === 'saved' ? <SavedNotice after={mandate} before={mode.before} /> : null}
      <header className="mandate-head">
        <h1 className="title" key={mode.kind} ref={focusOnMount} tabIndex={-1}>
          {isEditing ? 'Change agent limits' : 'Agent permissions'}
        </h1>
        <span className="muted">{subtitle}</span>
        {isEditing ? null : (
          <p>
            Your agent proposes. You decide. These rules are checked in code at every order. A
            prompt cannot change them.
          </p>
        )}
      </header>
      {mode.kind === 'edit' ? (
        <MandateForm
          initial={mandate}
          isFailed={mode.isFailed}
          isSaving={isSaving}
          version={mandate.version}
          onCancel={() => {
            setMode({ kind: 'view' })
          }}
          onSave={(edit) => {
            void save(edit)
          }}
        />
      ) : (
        <MandateView
          mandate={mandate}
          onEdit={() => {
            setMode({ kind: 'edit', isFailed: false })
          }}
        />
      )}
    </main>
  )
}

// The main user edits the agent's mandate. Save makes a new version.
export function PermissionsPage(): ReactElement {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(
    () =>
      loadMandate().then(
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
    [],
  )

  useEffect(() => {
    void load()
  }, [load])

  if (state.kind === 'loading') {
    return (
      <main>
        <p className="muted" role="status">
          Loading the rules.
        </p>
      </main>
    )
  }

  if (state.kind === 'failed') {
    return (
      <main className="stack">
        <p className="alert" role="alert">
          The rules could not be loaded.
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

  return (
    <PermissionsView
      data={state.data}
      onSaved={(mandate) => {
        setState({ kind: 'ready', data: { ...state.data, mandate } })
      }}
    />
  )
}
