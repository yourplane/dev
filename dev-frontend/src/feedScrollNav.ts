export type FeedNavTarget = { kind: 'header'; entryKey: string }

export interface FeedEntryOutline {
  type: string
  id: string
}

export function navTargetId(target: FeedNavTarget): string {
  return `${target.entryKey}:header`
}

export function buildFeedNavTargets(
  entries: FeedEntryOutline[],
  isCollapsed: (entryKey: string, entry: FeedEntryOutline) => boolean,
): FeedNavTarget[] {
  const targets: FeedNavTarget[] = []
  for (const entry of entries) {
    const entryKey = `${entry.type}:${entry.id}`
    if (isCollapsed(entryKey, entry)) continue
    targets.push({ kind: 'header', entryKey })
  }
  return targets
}

export function findNavTargetElement(target: FeedNavTarget): HTMLElement | null {
  return document.querySelector(
    `[data-feed-nav-key="${CSS.escape(target.entryKey)}"][data-feed-nav-type="header"]`,
  )
}

/** Index of the nav target whose top is at or just above the viewport anchor. */
export function findCurrentNavIndex(targets: FeedNavTarget[], viewportOffsetPx = 80): number {
  if (targets.length === 0) return -1
  let bestIdx = 0
  let found = false
  for (let i = 0; i < targets.length; i++) {
    const el = findNavTargetElement(targets[i])
    if (!el) continue
    found = true
    const top = el.getBoundingClientRect().top
    if (top <= viewportOffsetPx + 8) bestIdx = i
    else break
  }
  return found ? bestIdx : -1
}

export function scrollToNavTarget(target: FeedNavTarget, behavior: ScrollBehavior = 'smooth'): boolean {
  const el = findNavTargetElement(target)
  if (!el) return false
  el.scrollIntoView({ behavior, block: 'start' })
  return true
}

export function isNearPageBottom(thresholdPx = 80): boolean {
  return window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - thresholdPx
}
