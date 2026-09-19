// Roadmap #30: rank the palette's local commands (actions, tabs, fields)
// against what's typed, Linear-style: a title that starts with the query
// beats one with a word starting with it, which beats a plain substring,
// which beats the letters appearing in order ("dscr" in "Min DSCR", "ltc"
// in "LTV or LTC").

export type CommandGroup = 'actions' | 'tabs' | 'fields'

export interface PaletteCommand {
  id: string
  group: CommandGroup
  title: string
  /** Shown under the title (a field's section, an action's detail). */
  subtitle?: string
  /** Extra words that should match (a field id, synonyms). */
  keywords?: string
  /** A keyboard shortcut to show beside the title, e.g. "⌘↩". */
  shortcut?: string
  run: () => void
}

function isSubsequence(needle: string, hay: string): boolean {
  let i = 0
  for (const ch of hay) {
    if (ch === needle[i]) i += 1
    if (i === needle.length) return true
  }
  return needle.length === 0
}

/** Higher is better; 0 means no match. */
export function commandScore(query: string, command: PaletteCommand): number {
  const q = query.trim().toLowerCase()
  if (!q) return 1
  const title = command.title.toLowerCase()
  const extra = `${command.subtitle ?? ''} ${command.keywords ?? ''}`.toLowerCase()
  if (title.startsWith(q)) return 100 - Math.min(title.length, 50) / 100
  if (title.split(/[\s/()&,.-]+/).some((word) => word.startsWith(q))) return 80
  if (title.includes(q)) return 60
  if (extra.split(/[\s/()&,.-]+/).some((word) => word.startsWith(q))) return 40
  if (extra.includes(q)) return 30
  if (isSubsequence(q, title)) return 20
  return 0
}

/** Commands matching `query`, best first (stable for ties), at most
 *  `limit` per group. An empty query keeps actions and tabs (fields are too
 *  many to list unasked). */
export function searchCommands(
  commands: PaletteCommand[],
  query: string,
  limit: Partial<Record<CommandGroup, number>> = {},
): PaletteCommand[] {
  const empty = query.trim() === ''
  const counts: Partial<Record<CommandGroup, number>> = {}
  return commands
    .filter((c) => !(empty && c.group === 'fields'))
    .map((command, index) => ({ command, index, score: commandScore(query, command) }))
    .filter((r) => r.score > 0)
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .filter(({ command }) => {
      const max = limit[command.group]
      counts[command.group] = (counts[command.group] ?? 0) + 1
      return max === undefined || (counts[command.group] ?? 0) <= max
    })
    .map((r) => r.command)
}
