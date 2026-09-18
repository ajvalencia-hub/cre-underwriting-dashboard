import type { ReactNode } from 'react'

interface LayoutProps {
  nav: ReactNode
  summary: ReactNode
  children: ReactNode
}

export default function Layout({ nav, summary, children }: LayoutProps) {
  return (
    <div className="flex h-full min-h-screen bg-slate-50 text-slate-900">
      {/* Keyboard users otherwise tab through the nav, header and tabs (~40
          stops) before reaching a field. Visible only when focused. */}
      <button
        type="button"
        onClick={() => {
          const target = [...document.querySelectorAll<HTMLElement>('main input, main select, main textarea')].find(
            (el) => el.offsetParent !== null,
          )
          target?.focus()
        }}
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[70] focus:rounded focus:bg-slate-900 focus:px-3 focus:py-1.5 focus:text-sm focus:text-white"
      >
        Skip to the first field
      </button>
      <aside className="w-64 shrink-0 border-r border-slate-200 bg-white">
        <div className="px-4 py-4 text-sm font-semibold tracking-wide text-slate-500">
          CRE UNDERWRITING
        </div>
        <nav className="px-2">{nav}</nav>
      </aside>

      <main className="flex-1 overflow-y-auto px-8 py-6">{children}</main>

      <aside className="w-80 shrink-0 border-l border-slate-200 bg-white">
        <div className="sticky top-0 max-h-screen overflow-y-auto px-4 py-4">
          <div className="text-sm font-semibold tracking-wide text-slate-500">
            SUMMARY
          </div>
          <div className="mt-3">{summary}</div>
        </div>
      </aside>
    </div>
  )
}
