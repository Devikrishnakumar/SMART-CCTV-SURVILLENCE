import { useState } from 'react'
import { ArrowUpRight, Menu, X } from 'lucide-react'

const links = [
  { label: 'Overview', href: '#overview' },
  { label: 'Detection', href: '#signals' },
  { label: 'Camera setup', href: '#cameras' },
]

export default function Navbar() {
  const [open, setOpen] = useState(false)

  return (
    <nav className="site-nav" aria-label="Main navigation">
      <div className="nav-inner">
        <a className="brand" href="#top" aria-label="NovaGuard home">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 38 38" fill="none">
              <path d="M19 3.5 32.5 9v9.2c0 8.1-5.5 13.1-13.5 16.3C11 31.3 5.5 26.3 5.5 18.2V9L19 3.5Z" stroke="currentColor" strokeWidth="1.4" />
              <circle cx="19" cy="18.5" r="5.1" stroke="currentColor" strokeWidth="1.4" />
              <circle cx="19" cy="18.5" r="1.7" fill="currentColor" />
              <path d="M19 8v3M19 26v3M8.5 18.5h3M26.5 18.5h3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
          </span>
          <span className="brand-copy">
            <strong>NOVAGUARD</strong>
            <small>VIDEO INTELLIGENCE</small>
          </span>
        </a>

        <div className="nav-links">
          {links.map((link) => <a key={link.href} href={link.href}>{link.label}</a>)}
        </div>

        <a className="nav-cta" href="/dashboard">
          Open dashboard <ArrowUpRight size={15} strokeWidth={1.8} />
        </a>

        <button
          className="nav-menu-toggle"
          type="button"
          aria-label={open ? 'Close menu' : 'Open menu'}
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          {open ? <X size={21} /> : <Menu size={21} />}
        </button>
      </div>

      {open && (
        <div className="mobile-nav-panel">
          {links.map((link) => (
            <a key={link.href} href={link.href} onClick={() => setOpen(false)}>{link.label}</a>
          ))}
          <a href="/dashboard" onClick={() => setOpen(false)}>Open dashboard <ArrowUpRight size={15} /></a>
        </div>
      )}
    </nav>
  )
}
