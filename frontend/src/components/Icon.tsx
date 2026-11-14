import type { ReactElement } from 'react'

// Inline SVG paths on a 24 x 24 grid, drawn with currentColor. No icon dependency.
const ICON_PATHS = {
  attention: 'M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M12 7.5v6M12 16.5v.01',
} as const

export type IconName = keyof typeof ICON_PATHS

interface IconProps {
  readonly name: IconName
  readonly className?: string
}

// Decorative only: the text next to an icon always says the same thing.
export function Icon({ name, className }: IconProps): ReactElement {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={ICON_PATHS[name]} />
    </svg>
  )
}
