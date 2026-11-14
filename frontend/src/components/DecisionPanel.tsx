import { useRef, useState, type ReactElement, type SubmitEvent } from 'react'

// A quick reason only fills the field. The user can still edit it before sending.
const QUICK_REASONS = ['Wrong product', 'Wrong quantity', 'Too expensive', 'Not now'] as const

const REASON_FIELD_ID = 'reject-reason'
const REASON_ERROR_ID = 'reject-reason-error'

interface DecisionPanelProps {
  readonly isBusy: boolean
  readonly onApprove: () => void
  readonly onReject: (reason: string) => void
}

// Approve, or open the reject form. isBusy disables every button while a call runs.
export function DecisionPanel({ isBusy, onApprove, onReject }: DecisionPanelProps): ReactElement {
  const [isRejecting, setIsRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [isReasonMissing, setIsReasonMissing] = useState(false)
  const reasonField = useRef<HTMLTextAreaElement>(null)

  function fillReason(text: string): void {
    setReason(text)
    setIsReasonMissing(false)
    reasonField.current?.focus()
  }

  function submit(event: SubmitEvent<HTMLFormElement>): void {
    event.preventDefault()
    const trimmed = reason.trim()
    if (trimmed === '') {
      setIsReasonMissing(true)
      reasonField.current?.focus()
      return
    }

    onReject(trimmed)
  }

  if (!isRejecting) {
    return (
      <div className="actions">
        <button
          className="button button-primary"
          type="button"
          disabled={isBusy}
          onClick={onApprove}
        >
          Approve order
        </button>
        <button
          className="button button-text"
          type="button"
          disabled={isBusy}
          onClick={() => {
            setIsRejecting(true)
          }}
        >
          Reject
        </button>
      </div>
    )
  }

  return (
    <form className="card stack" onSubmit={submit} noValidate>
      <div className="field">
        <label className="field-label" htmlFor={REASON_FIELD_ID}>
          Why do you reject this order?
        </label>
        <textarea
          className="input"
          id={REASON_FIELD_ID}
          ref={reasonField}
          rows={3}
          value={reason}
          required
          autoFocus
          aria-invalid={isReasonMissing}
          aria-describedby={isReasonMissing ? REASON_ERROR_ID : undefined}
          onChange={(event) => {
            fillReason(event.target.value)
          }}
        />
        {isReasonMissing ? (
          <p className="field-error" id={REASON_ERROR_ID}>
            Write a reason, or tap one below.
          </p>
        ) : null}
      </div>

      <ul className="chips" aria-label="Quick reasons">
        {QUICK_REASONS.map((quickReason) => (
          <li key={quickReason}>
            <button
              className="button-quiet"
              type="button"
              disabled={isBusy}
              onClick={() => {
                fillReason(quickReason)
              }}
            >
              {quickReason}
            </button>
          </li>
        ))}
      </ul>

      <div className="actions">
        <button className="button button-deny" type="submit" disabled={isBusy}>
          Reject order
        </button>
        <button
          className="button button-text-quiet"
          type="button"
          disabled={isBusy}
          onClick={() => {
            setIsRejecting(false)
            setIsReasonMissing(false)
          }}
        >
          Cancel
        </button>
      </div>
    </form>
  )
}
