import { useRef, useState, type ReactElement, type SubmitEvent } from 'react'

import type { Cart, CartChange, CartUpdate } from '../api.ts'
import { ChangeSheet } from './ChangeSheet.tsx'
import { ApprovalSummary } from './CartReview.tsx'
import { TrustMark } from './TrustMark.tsx'

// A quick reason only fills the field. The user can still edit it before sending.
const QUICK_REASONS = ['Wrong product', 'Wrong quantity', 'Too expensive', 'Not now'] as const

const REASON_FIELD_ID = 'reject-reason'
const REASON_ERROR_ID = 'reject-reason-error'

interface DecisionPanelProps {
  readonly cart: Cart
  readonly isBusy: boolean
  // An update the user has not reviewed yet: every decision waits for the Review tap.
  readonly isReviewPending: boolean
  readonly update?: CartUpdate
  readonly onApprove: () => void
  readonly onReject: (reason: string) => void
  readonly onChange: (change: CartChange) => void
}

// Approve, change or open the reject sheet. isBusy disables every button while a call runs.
export function DecisionPanel({
  cart,
  isBusy,
  isReviewPending,
  update,
  onApprove,
  onReject,
  onChange,
}: DecisionPanelProps): ReactElement {
  const isLocked = isBusy || isReviewPending
  const [reason, setReason] = useState('')
  const [isReasonMissing, setIsReasonMissing] = useState(false)
  const sheet = useRef<HTMLDialogElement>(null)
  const changeSheet = useRef<HTMLDialogElement>(null)
  const reasonField = useRef<HTMLTextAreaElement>(null)

  function fillReason(text: string): void {
    setReason(text)
    setIsReasonMissing(false)
    reasonField.current?.focus()
  }

  function openSheet(): void {
    sheet.current?.showModal()
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

    // Close first: a failed call shows Retry on the page, which a modal would cover.
    sheet.current?.close()
    onReject(trimmed)
  }

  return (
    <>
      <div className="desktop-only stack">
        <ApprovalSummary cart={cart} update={update} />
        <TrustMark />
      </div>
      <div className="actions">
        {cart.isInsideLimits ? (
          <p className="muted">This order is now inside the agent's limits.</p>
        ) : null}
        <button
          className="button button-primary"
          type="button"
          disabled={isLocked}
          onClick={onApprove}
        >
          {isReviewPending
            ? 'Review the update first'
            : `Approve order (${cart.total} ${cart.currency})`}
        </button>
        <div className="actions-secondary">
          <button
            className="button button-change"
            type="button"
            disabled={isLocked}
            aria-haspopup="dialog"
            onClick={() => changeSheet.current?.showModal()}
          >
            Change
          </button>
          <button
            className="button button-text"
            type="button"
            disabled={isLocked}
            aria-haspopup="dialog"
            onClick={openSheet}
          >
            Reject
          </button>
        </div>
      </div>

      <ChangeSheet
        // The sheet copies the lines on mount, and the lines change when Review shows the update.
        key={`${cart.revision}-${isReviewPending}`}
        ref={changeSheet}
        cart={cart}
        isBusy={isBusy}
        onSave={onChange}
      />

      <dialog
        className="sheet"
        ref={sheet}
        aria-labelledby="reject-title"
        onClose={() => {
          setIsReasonMissing(false)
        }}
      >
        <form className="stack" onSubmit={submit} noValidate>
          <span className="sheet-grip" aria-hidden="true" />
          <h2 className="heading" id="reject-title">
            Why do you reject this order?
          </h2>
          <p className="muted">
            Your agent reads this reason and tells the buyer. No order is placed.
          </p>

          <ul className="chips" aria-label="Quick reasons">
            {QUICK_REASONS.map((quickReason) => (
              <li key={quickReason}>
                <button
                  className="button-quiet"
                  type="button"
                  disabled={isBusy}
                  aria-pressed={reason === quickReason}
                  onClick={() => {
                    fillReason(quickReason)
                  }}
                >
                  {quickReason}
                </button>
              </li>
            ))}
          </ul>

          <div className="field">
            <label className="field-label" htmlFor={REASON_FIELD_ID}>
              Reason (required)
            </label>
            <textarea
              className="input"
              id={REASON_FIELD_ID}
              ref={reasonField}
              rows={3}
              value={reason}
              required
              aria-invalid={isReasonMissing}
              aria-describedby={isReasonMissing ? REASON_ERROR_ID : undefined}
              onChange={(event) => {
                fillReason(event.target.value)
              }}
            />
            {isReasonMissing ? (
              <p className="field-error" id={REASON_ERROR_ID}>
                Write a reason, or tap one above.
              </p>
            ) : null}
          </div>

          <div className="sheet-actions">
            <button
              className="button button-outline"
              type="button"
              disabled={isBusy}
              onClick={() => sheet.current?.close()}
            >
              Cancel
            </button>
            <button className="button button-deny" type="submit" disabled={isBusy}>
              Send rejection
            </button>
          </div>
        </form>
      </dialog>
    </>
  )
}
