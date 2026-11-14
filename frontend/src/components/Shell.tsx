import { useEffect, useState, type ReactElement, type ReactNode } from 'react'

import { getSession } from '../api.ts'

interface ShellProps {
  readonly path: string
  readonly children: ReactNode
}

interface NavLink {
  readonly href: string
  readonly label: string
  readonly paths: readonly string[]
}

// The approval, record and order pages show no nav, so the user stays on the one decision.
const NAV_LINKS: readonly NavLink[] = [
  { href: '/inbox', label: 'Approvals', paths: ['/', '/inbox'] },
  { href: '/permissions', label: 'Agent permissions', paths: ['/permissions'] },
]

function MainNav({ path }: { readonly path: string }): ReactElement {
  return (
    <nav aria-label="Main" className="app-nav">
      {NAV_LINKS.map(({ href, label, paths }) => (
        <a
          aria-current={paths.includes(path) ? 'page' : undefined}
          className="app-nav-link"
          href={href}
          key={href}
        >
          {label}
        </a>
      ))}
    </nav>
  )
}

// Desktop only: the phone header has no room, and the page title line names the buyer.
// A failed session read hides the label: the page itself sends a signed out user to login.
function UserLabel(): ReactElement | null {
  const [buyerId, setBuyerId] = useState<string | null>(null)

  useEffect(() => {
    getSession().then(
      (session) => {
        setBuyerId(session.buyerId)
      },
      () => {
        setBuyerId(null)
      },
    )
  }, [])

  return buyerId === null ? null : <span className="muted app-user">Main user, {buyerId}</span>
}

// Every page carries the Prototype tag and the disclaimer, so nobody takes it for a Valio Aimo
// production system.
export function Shell({ path, children }: ShellProps): ReactElement {
  const hasNav = NAV_LINKS.some(({ paths }) => paths.includes(path))

  return (
    <div className="app-shell">
      <header className={hasNav ? 'app-header app-header-nav' : 'app-header'}>
        <span className="app-name">Valtuus</span>
        {hasNav ? <MainNav path={path} /> : null}
        {hasNav ? <UserLabel /> : null}
        <span className="tag">Prototype</span>
      </header>
      {children}
      <footer className="app-footer">Valtuus prototype for the Valio Aimo challenge.</footer>
    </div>
  )
}
