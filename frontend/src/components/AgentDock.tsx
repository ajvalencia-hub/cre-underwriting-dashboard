// STUB (Phase 0, F1) — F3 replaces the body with the Run 6 floating agent
// chat dock. App.tsx already mounts it OUTSIDE <Layout> (so it survives
// every tab switch) and only after boot/auth:
//
//   <>
//     <Layout …>…</Layout>
//     <AgentDock dealId={…} schema={…} currentValues={…} icLocked={…}
//                onApproveProposal={…} hidden={tab === 'agent'} />
//   </>
//
// Props: AgentSurfaceProps (documented in pages/AgentPage.tsx) plus
// - hidden: true while the Agent tab itself is showing (no duplicate chat).
//
// Layering: z-40 (above the sticky deal header z-30, below the palette /
// modals z-50 and toasts). Escape closes it. The open/closed flag goes
// through lib/safeStorage. Renders nothing until F3 lands.
import type { AgentSurfaceProps } from '../pages/AgentPage'

export interface AgentDockProps extends AgentSurfaceProps {
  hidden: boolean
}

export default function AgentDock(props: AgentDockProps) {
  void props
  return null
}
