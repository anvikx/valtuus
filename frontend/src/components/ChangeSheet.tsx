import { useState, type ReactElement, type RefObject, type SubmitEvent } from 'react'

import type { Cart, CartChange, CartLine } from '../api.ts'
import { formatCount } from '../format.ts'
import { money } from './ResultScreen.tsx'

const NOTE_FIELD_ID = 'change-note'
const NOTE_HELP_ID = 'change-note-help'
const WHOLE_NUMBER = /^\d+$/

interface ChangeSheetProps {
  readonly ref: RefObject<HTMLDialogElement | null>
  readonly cart: Cart
  readonly isBusy: boolean
  readonly onSave: (change: CartChange) => void
}

type Quantities = Readonly<Record<string, string>>

function initialQuantities(lines: readonly CartLine[]): Quantities {
  return Object.fromEntries(lines.map((line) => [line.productId, String(line.qty)]))
}

// Zero is not a quantity here: Remove is the way to drop a line.
function parseQuantity(text: string): number | null {
  const trimmed = text.trim()
  if (!WHOLE_NUMBER.test(trimmed)) {
    return null
  }

  const quantity = Number.parseInt(trimmed, 10)
  return quantity >= 1 ? quantity : null
}

// Returns the change, or the plain sentence that says what the user must fix.
function collectChange(
  lines: readonly CartLine[],
  quantities: Quantities,
  removed: readonly string[],
  note: string,
): CartChange | string {
  const kept = lines.filter((line) => !removed.includes(line.productId))
  if (kept.length === 0) {
    return 'Keep at least one line, or reject the order.'
  }

  const changed: [string, number][] = []
  for (const line of kept) {
    const quantity = parseQuantity(quantities[line.productId])
    if (quantity === null) {
      return `Enter a whole number for ${line.name}.`
    }

    if (quantity !== line.qty) {
      changed.push([line.productId, quantity])
    }
  }

  const trimmed = note.trim()
  if (changed.length === 0 && removed.length === 0 && trimmed === '') {
    return 'Nothing is changed.'
  }

  return {
    quantities: Object.fromEntries(changed),
    removed,
    note: trimmed,
  }
}

interface LineEditorProps {
  readonly line: CartLine
  readonly currency: string
  readonly quantity: string
  readonly isRemoved: boolean
  readonly onQuantity: (text: string) => void
  readonly onToggleRemoved: () => void
}

function LineEditor({
  line,
  currency,
  quantity,
  isRemoved,
  onQuantity,
  onToggleRemoved,
}: LineEditorProps): ReactElement {
  const inputId = `qty-${line.productId}`

  function step(delta: number): void {
    const current = parseQuantity(quantity) ?? line.qty
    onQuantity(String(Math.max(1, current + delta)))
  }

  return (
    <li className="change-line">
      <div className="line-head">
        <span className="change-line-name">
          <strong>{line.name}</strong>
          <span className="muted">{money(line.unitPrice, currency)} ex VAT each</span>
        </span>
        <button
          className="button button-text button-compact"
          type="button"
          aria-label={`${isRemoved ? 'Keep' : 'Remove'} ${line.name}`}
          onClick={onToggleRemoved}
        >
          {isRemoved ? 'Keep' : 'Remove'}
        </button>
      </div>
      {isRemoved ? (
        <p className="muted">This line is removed when you save.</p>
      ) : (
        <div className="qty-group" role="group" aria-label={line.name}>
          <button
            className="qty-step"
            type="button"
            aria-label={`Less ${line.name}`}
            onClick={() => {
              step(-1)
            }}
          >
            &minus;
          </button>
          <label className="sr-only" htmlFor={inputId}>
            Quantity, {line.name}
          </label>
          <input
            className="input qty-input"
            id={inputId}
            type="text"
            inputMode="numeric"
            value={quantity}
            onChange={(event) => {
              onQuantity(event.target.value)
            }}
          />
          <button
            className="qty-step"
            type="button"
            aria-label={`More ${line.name}`}
            onClick={() => {
              step(1)
            }}
          >
            +
          </button>
          <span className="muted">was {formatCount(line.qty)}</span>
        </div>
      )}
    </li>
  )
}

// Quantities, remove and a note. No total here: the backend sends the new one after the save.
export function ChangeSheet({ ref, cart, isBusy, onSave }: ChangeSheetProps): ReactElement {
  const [quantities, setQuantities] = useState<Quantities>(() => initialQuantities(cart.lines))
  const [removed, setRemoved] = useState<readonly string[]>([])
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)

  function reset(): void {
    setQuantities(initialQuantities(cart.lines))
    setRemoved([])
    setNote('')
    setError(null)
  }

  function toggleRemoved(productId: string): void {
    setError(null)
    setRemoved((current) =>
      current.includes(productId)
        ? current.filter((id) => id !== productId)
        : [...current, productId],
    )
  }

  function submit(event: SubmitEvent<HTMLFormElement>): void {
    event.preventDefault()
    const result = collectChange(cart.lines, quantities, removed, note)
    if (typeof result === 'string') {
      setError(result)
      return
    }

    // Close first: a failed call shows Retry on the page, which a modal would cover.
    ref.current?.close()
    onSave(result)
  }

  return (
    <dialog className="sheet" ref={ref} aria-labelledby="change-title" onClose={reset}>
      <form className="stack" onSubmit={submit} noValidate>
        <span className="sheet-grip" aria-hidden="true" />
        <h2 className="heading" id="change-title">
          Change this order
        </h2>

        <ul className="stack-tight">
          {cart.lines.map((line) => (
            <LineEditor
              key={line.productId}
              line={line}
              currency={cart.currency}
              quantity={quantities[line.productId]}
              isRemoved={removed.includes(line.productId)}
              onQuantity={(text) => {
                setError(null)
                setQuantities((current) => ({ ...current, [line.productId]: text }))
              }}
              onToggleRemoved={() => {
                toggleRemoved(line.productId)
              }}
            />
          ))}
        </ul>

        <div className="field">
          <label className="field-label" htmlFor={NOTE_FIELD_ID}>
            Anything else for the agent? (optional)
          </label>
          <textarea
            className="input"
            id={NOTE_FIELD_ID}
            rows={2}
            value={note}
            placeholder="For example: another brand, or a later day"
            aria-describedby={NOTE_HELP_ID}
            onChange={(event) => {
              setNote(event.target.value)
            }}
          />
          <p className="muted" id={NOTE_HELP_ID}>
            A quantity change is saved by you. A note goes to the agent, and the agent sends an
            update to this page. The new total comes after you save.
          </p>
        </div>

        {error === null ? null : (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}

        <div className="sheet-actions">
          <button
            className="button button-outline"
            type="button"
            disabled={isBusy}
            onClick={() => ref.current?.close()}
          >
            Cancel
          </button>
          <button className="button button-primary" type="submit" disabled={isBusy}>
            Save changes
          </button>
        </div>
      </form>
    </dialog>
  )
}
