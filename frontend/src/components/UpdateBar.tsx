import type { ReactElement, Ref } from 'react'

interface UpdateBarProps {
  readonly onReview: () => void
  readonly ref?: Ref<HTMLButtonElement>
}

// Rule 4: the new version never replaces what the user reads. It shows after this tap.
export function UpdateBar({ onReview, ref }: UpdateBarProps): ReactElement {
  return (
    <div className="update-bar" role="status">
      <span>This order was updated. Review the changes.</span>
      <button className="button button-light" type="button" ref={ref} onClick={onReview}>
        Review
      </button>
    </div>
  )
}
