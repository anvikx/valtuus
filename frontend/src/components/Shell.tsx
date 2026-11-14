import type { ReactElement, ReactNode } from 'react'

interface ShellProps {
  readonly children: ReactNode
}

// Every page carries the Prototype tag and the disclaimer, so nobody takes it for a Valio Aimo
// production system.
export function Shell({ children }: ShellProps): ReactElement {
  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-name">Valtuus</span>
        <span className="tag">Prototype</span>
      </header>
      {children}
      <footer className="app-footer">
        Valtuus prototype for the Valio Aimo challenge. Not a Valio Aimo production system.
      </footer>
    </div>
  )
}
