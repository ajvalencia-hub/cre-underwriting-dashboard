import { NAV_GROUPS, type Tab } from '../app/navigation'
import type { InputSection } from '../types/schema'

interface Props {
  tab: Tab
  onSelect: (tab: Tab) => void
  /** Deal Inputs sections, listed under that item while it's open. */
  sections: InputSection[]
  onGoToSection: (sectionId: string) => void
}

/** Left-rail module navigation. It replaced a top tab strip that was
 *  1,298px wide in an 800px column, hiding six modules at 1440px. */
export default function ModuleNav({ tab, onSelect, sections, onGoToSection }: Props) {
  return (
    <div className="space-y-4 pb-4">
      {NAV_GROUPS.map((group) => (
        <div key={group.label}>
          {group.label && (
            <div className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {group.label}
            </div>
          )}
          <ul className="space-y-0.5">
            {group.items.map(([id, label]) => (
              <li key={id}>
                <button
                  onClick={() => onSelect(id)}
                  aria-current={tab === id ? 'page' : undefined}
                  className={`w-full rounded px-2 py-1.5 text-left text-sm ${
                    tab === id ? 'bg-slate-100 font-medium text-slate-900' : 'text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  {label}
                </button>
                {id === 'dashboard' && tab === 'dashboard' && (
                  <ul aria-label="Deal Inputs sections" className="mt-0.5 mb-1 ml-3 border-l border-slate-200 pl-2">
                    {sections.map((section) => (
                      <li key={section.id}>
                        <button
                          onClick={() => onGoToSection(section.id)}
                          className="w-full rounded px-2 py-1 text-left text-xs text-slate-600 hover:bg-slate-100"
                        >
                          {section.label}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}
