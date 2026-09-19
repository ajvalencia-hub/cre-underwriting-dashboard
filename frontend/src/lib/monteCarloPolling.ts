// Monte Carlo polling budget (wave 2): the Risk panel polls a job every
// 400ms; without a ceiling a stuck job would spin the UI forever. Pure so
// the deadline logic is unit-tested without timers.

export const MONTE_CARLO_POLL_INTERVAL_MS = 400
export const MONTE_CARLO_POLL_TIMEOUT_MS = 5 * 60_000

export function pollTimedOut(
  startedAtMs: number,
  nowMs: number,
  limitMs: number = MONTE_CARLO_POLL_TIMEOUT_MS,
): boolean {
  return nowMs - startedAtMs >= limitMs
}

export function pollTimeoutMessage(limitMs: number = MONTE_CARLO_POLL_TIMEOUT_MS): string {
  const minutes = Math.round(limitMs / 60_000)
  return `Gave up after ${minutes} minute${minutes === 1 ? '' : 's'} — the run may still be going on the server. Try fewer trials or drivers.`
}
