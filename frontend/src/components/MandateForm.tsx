import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactElement,
} from 'react'

import type { AllergenPolicy, MandateEdit } from '../api.ts'
import {
  ALLERGEN_WORDS,
  REQUIRED_ATTRIBUTE_CODES,
  formatAllergen,
  formatAttribute,
} from '../format.ts'
import { POLICY_WORDS } from './MandateView.tsx'

const ALLERGEN_CODES = Object.keys(ALLERGEN_WORDS)

type CodeField = 'required' | 'forbidden'

const POLICY_CHOICES: readonly AllergenPolicy[] = ['ask', 'block']
const MAX_ORDER_ID = 'max-order'
const MAX_DAY_ID = 'max-day'

// A stored value the form does not offer must still show, or Save keeps a rule the user cannot
// see ("order" as policy, an allergen code outside the 14).
function withStored<T>(choices: readonly T[], stored: readonly T[]): readonly T[] {
  return [...choices, ...stored.filter((value) => !choices.includes(value))]
}

// The backend bound is 1,000,000 with 2 decimals. Digits are compared as text, never as floats.
const MONEY_FORMAT = /^(\d{1,7})(?:\.(\d{1,2}))?$/
const MAX_INTEGER_PART = 1_000_000
const FORMAT_ERROR = 'Use digits and a dot, for example 1500.00. Up to 2 decimals.'
const EMPTY_ERROR = 'Enter an amount.'
const MAX_ERROR = 'The most is 1000000.00.'

interface MandateFormProps {
  readonly initial: MandateEdit
  readonly version: number
  readonly isSaving: boolean
  readonly isFailed: boolean
  readonly onSave: (edit: MandateEdit) => void
  readonly onCancel: () => void
}

function moneyError(value: string, hasTriedSave: boolean): string | null {
  if (value === '') {
    return hasTriedSave ? EMPTY_ERROR : null
  }

  const match = MONEY_FORMAT.exec(value)
  if (match === null) {
    return FORMAT_ERROR
  }

  const whole = Number(match[1])
  const hasCents = /[1-9]/.test(match[2] ?? '')
  const isOver = whole > MAX_INTEGER_PART || (whole === MAX_INTEGER_PART && hasCents)
  return isOver ? MAX_ERROR : null
}

interface MoneyFieldProps {
  readonly id: string
  readonly label: string
  readonly hint: string
  readonly value: string
  readonly error: string | null
  readonly onChange: (value: string) => void
}

function MoneyField({ id, label, hint, value, error, onChange }: MoneyFieldProps): ReactElement {
  const describedBy = error === null ? `${id}-hint` : `${id}-hint ${id}-error`

  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      <div className="input-row mandate-money">
        <input
          aria-describedby={describedBy}
          aria-invalid={error !== null}
          autoComplete="off"
          className="input"
          id={id}
          inputMode="decimal"
          type="text"
          value={value}
          onChange={(event) => {
            onChange(event.target.value.trim())
          }}
        />
        <span className="mandate-unit">EUR</span>
      </div>
      <span className="muted" id={`${id}-hint`}>
        {hint}
      </span>
      {error === null ? null : (
        <span className="field-error" id={`${id}-error`}>
          {error}
        </span>
      )}
    </div>
  )
}

interface BrandsProps {
  readonly brands: readonly string[]
  readonly onChange: (brands: readonly string[]) => void
}

function BrandsField({ brands, onChange }: BrandsProps): ReactElement {
  const [draft, setDraft] = useState('')

  function add(): void {
    const name = draft.trim()
    const isKnown = brands.some((brand) => brand.toLowerCase() === name.toLowerCase())
    setDraft('')
    if (name === '' || isKnown) {
      return
    }

    onChange([...brands, name])
  }

  // Enter adds the brand. Without this it would submit the whole form.
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key !== 'Enter') {
      return
    }

    event.preventDefault()
    add()
  }

  return (
    <fieldset className="mandate-group">
      <legend className="heading">Preferred brands</legend>
      <p className="muted" id="brands-hint">
        Another brand then needs your approval. Leave empty for any brand.
      </p>
      {brands.length === 0 ? null : (
        <ul className="mandate-chips" role="list">
          {brands.map((brand) => (
            <li key={brand}>
              <button
                aria-label={`Remove ${brand}`}
                className="button-quiet"
                type="button"
                onClick={() => {
                  onChange(brands.filter((other) => other !== brand))
                }}
              >
                {brand} <span aria-hidden="true">×</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="input-row">
        <label className="sr-only" htmlFor="brand">
          Add a brand
        </label>
        <input
          aria-describedby="brands-hint"
          autoComplete="off"
          className="input"
          id="brand"
          placeholder="Add a brand"
          type="text"
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value)
          }}
          onKeyDown={onKeyDown}
        />
        <button className="button button-outline" type="button" onClick={add}>
          Add
        </button>
      </div>
    </fieldset>
  )
}

export function MandateForm({
  initial,
  version,
  isSaving,
  isFailed,
  onSave,
  onCancel,
}: MandateFormProps): ReactElement {
  const [draft, setDraft] = useState<MandateEdit>(initial)
  const [hasTriedSave, setHasTriedSave] = useState(false)
  const orderError = moneyError(draft.maxOrder, hasTriedSave)
  const dayError = moneyError(draft.maxPerDay, hasTriedSave)
  const attributeCodes = withStored(REQUIRED_ATTRIBUTE_CODES, initial.required)
  const allergenCodes = withStored(ALLERGEN_CODES, initial.forbidden)
  const policies = withStored(POLICY_CHOICES, [initial.unknownPolicy])
  const saveButton = useRef<HTMLButtonElement>(null)

  // The busy state disables Save, so focus falls to the page body. Retry takes it back.
  useEffect(() => {
    if (isFailed && !isSaving) {
      saveButton.current?.focus()
    }
  }, [isFailed, isSaving])

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    setHasTriedSave(true)
    // Focus on the bad field reads its error, which a screen reader would not hear otherwise.
    const invalidId =
      moneyError(draft.maxOrder, true) !== null
        ? MAX_ORDER_ID
        : moneyError(draft.maxPerDay, true) !== null
          ? MAX_DAY_ID
          : null
    if (invalidId !== null) {
      document.getElementById(invalidId)?.focus()
      return
    }

    onSave(draft)
  }

  function toggle(field: CodeField, code: string, isOn: boolean): void {
    const rest = draft[field].filter((other) => other !== code)
    setDraft({ ...draft, [field]: isOn ? [...rest, code] : rest })
  }

  return (
    <form className="mandate-form" noValidate onSubmit={submit}>
      <fieldset className="mandate-group">
        <legend className="heading">What the agent may order alone</legend>
        <MoneyField
          error={orderError}
          hint={`Now ${initial.maxOrder} EUR. Up to this total the agent orders with no approval.`}
          id={MAX_ORDER_ID}
          label="Per order, ex VAT"
          value={draft.maxOrder}
          onChange={(maxOrder) => {
            setDraft({ ...draft, maxOrder })
          }}
        />
        <MoneyField
          error={dayError}
          hint={`Now ${initial.maxPerDay} EUR. All automatic orders for one delivery day together.`}
          id={MAX_DAY_ID}
          label="Per delivery day, ex VAT"
          value={draft.maxPerDay}
          onChange={(maxPerDay) => {
            setDraft({ ...draft, maxPerDay })
          }}
        />
      </fieldset>

      <BrandsField
        brands={draft.preferredBrands}
        onChange={(preferredBrands) => {
          setDraft({ ...draft, preferredBrands })
        }}
      />

      <fieldset aria-describedby="required-hint" className="mandate-group">
        <legend className="heading">Every product must be</legend>
        <p className="muted" id="required-hint">
          The agent orders only products with all of these, and does not ask the buyer about them.
        </p>
        <div className="mandate-checks">
          {attributeCodes.map((code) => (
            <label className="mandate-choice" key={code}>
              <input
                checked={draft.required.includes(code)}
                type="checkbox"
                onChange={(event) => {
                  toggle('required', code, event.target.checked)
                }}
              />
              {formatAttribute(code)}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset aria-describedby="forbidden-hint" className="mandate-group">
        <legend className="heading">Does not contain</legend>
        <p className="muted" id="forbidden-hint">
          The agent never orders a product that matches these.
        </p>
        <div className="mandate-checks">
          {allergenCodes.map((code) => (
            <label className="mandate-choice" key={code}>
              <input
                checked={draft.forbidden.includes(code)}
                type="checkbox"
                onChange={(event) => {
                  toggle('forbidden', code, event.target.checked)
                }}
              />
              {formatAllergen(code)}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="mandate-group">
        <legend className="heading">When allergen data is missing</legend>
        {policies.map((policy) => (
          <label className="mandate-choice" key={policy}>
            <input
              checked={draft.unknownPolicy === policy}
              name="unknown-policy"
              type="radio"
              onChange={() => {
                setDraft({ ...draft, unknownPolicy: policy })
              }}
            />
            {POLICY_WORDS[policy]}
          </label>
        ))}
      </fieldset>

      <div className="actions">
        {isFailed ? (
          <p className="alert" role="alert">
            The rules could not be saved. Your changes are still here.
          </p>
        ) : null}
        <p className="muted">
          Saving makes version {version + 1}. Open carts are not changed, and no order is placed.
        </p>
        <button
          className="button button-primary"
          disabled={isSaving}
          ref={saveButton}
          type="submit"
        >
          {isFailed ? 'Retry' : `Save as version ${version + 1}`}
        </button>
        <button
          className="button button-text mandate-cancel"
          disabled={isSaving}
          type="button"
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </form>
  )
}
