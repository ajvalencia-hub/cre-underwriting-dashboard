// Module navigation: the tabs, how the left rail groups them, and the
// remembered last tab. Split out of App.tsx (roadmap #32).

export const TABS = [
  'pipeline',
  'quickscreen',
  'documents',
  'setup',
  'dashboard',
  'cashflow',
  'sensitivity',
  'risk',
  'scenarios',
  'approval',
  'comps',
  'portfolio',
  'settings',
] as const
export type Tab = (typeof TABS)[number]

/** Views that span many deals — no one-deal summary panel beside them. */
export const MULTI_DEAL_TABS: ReadonlySet<Tab> = new Set<Tab>(['pipeline', 'portfolio', 'comps', 'settings'])

// Left-rail module navigation. Grouped (workflow steps under "This deal"),
// no step numbers — "0." / "5b." implied a strict order that doesn't exist.
export const NAV_GROUPS: { label: string; items: readonly (readonly [Tab, string])[] }[] = [
  {
    label: 'Portfolio',
    items: [
      ['pipeline', 'Deals'],
      ['portfolio', 'Portfolio'],
      ['comps', 'Comps'],
    ],
  },
  {
    label: 'This deal',
    items: [
      ['quickscreen', 'Quick Screen'],
      ['documents', 'Documents'],
      ['setup', 'Template & Mapping'],
      ['dashboard', 'Deal Inputs'],
      ['cashflow', 'Cash Flow'],
      ['sensitivity', 'Sensitivity'],
      ['risk', 'Risk'],
      ['scenarios', 'Scenarios'],
      ['approval', 'IC Approval'],
    ],
  },
  { label: '', items: [['settings', 'Settings']] },
]

// Reopen where the user was (per browser / desktop profile). Storage can be
// unavailable (private mode); the app then just starts on Quick Screen.
const LAST_TAB_KEY = 'cre.lastTab'

export function loadLastTab(): Tab {
  try {
    const stored = localStorage.getItem(LAST_TAB_KEY)
    return (TABS as readonly string[]).includes(stored ?? '') ? (stored as Tab) : 'quickscreen'
  } catch {
    return 'quickscreen'
  }
}

export function rememberTab(tab: Tab): void {
  try {
    localStorage.setItem(LAST_TAB_KEY, tab)
  } catch {
    // storage unavailable — not remembering the tab is harmless
  }
}
