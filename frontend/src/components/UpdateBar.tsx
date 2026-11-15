import type { ReactElement, Ref } from 'react'

// 'closed': a silent check found the cart decided elsewhere, expired or withdrawn.
type UpdateKind = 'revised' | 'closed'

const MESSAGE: Readonly<Record<UpdateKind, string>> = {
  revised: 'This order was updated. Review the changes.',
  closed: 'This order no longer waits for you. Review what happened.',
}

interface UpdateBarProps {
  readonly kind: UpdateKind
  readonly onReview: () => void
  readonly ref?: Ref<HTMLButtonElement>
}

// Rule 4: the new version never replaces what the user reads. It shows after this tap.
export function UpdateBar({ kind, onReview, ref }: UpdateBarProps): ReactElement {
  return (
    <div className="update-bar" role="status">
      <span>{MESSAGE[kind]}</span>
      <button className="button button-light" type="button" ref={ref} onClick={onReview}>
        Review
      </button>
    </div>
  )
}
