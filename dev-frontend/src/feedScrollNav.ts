export type FeedNavTarget =
  | { kind: 'header'; entryKey: string }
  | { kind: 'page-bottom' }

export interface FeedEntryOutline {
  type: string
  id: string
}

export function navTargetId(target: FeedNavTarget): string {
  return target.kind === 'page-bottom' ? 'page:bottom:footer' : `${target.entryKey}:header`
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
  targets.push({ kind: 'page-bottom' })
  return targets
}

export function findNavTargetElement(target: FeedNavTarget): HTMLElement | null {
  if (target.kind === 'page-bottom') return null
  return document.querySelector(
    `[data-feed-nav-key="${CSS.escape(target.entryKey)}"][data-feed-nav-type="header"]`,
  )
}

/** Index of the nav target whose top is at or just above the viewport anchor. */
export function findCurrentNavIndex(targets: FeedNavTarget[], viewportOffsetPx = 80): number {
  if (targets.length === 0) return -1

  const footerIdx = targets.length - 1
  const hasFooter = targets[footerIdx].kind === 'page-bottom'
  const headerTargets = hasFooter ? targets.slice(0, footerIdx) : targets

  let bestIdx = 0
  let found = false
  for (let i = 0; i < headerTargets.length; i++) {
    const el = findNavTargetElement(headerTargets[i])
    if (!el) continue
    found = true
    const top = el.getBoundingClientRect().top
    if (top <= viewportOffsetPx + 8) bestIdx = i
    else break
  }
  if (found) return bestIdx

  if (hasFooter && isNearPageBottom(viewportOffsetPx)) return footerIdx
  return -1
}

export function scrollToNavTarget(target: FeedNavTarget, behavior: ScrollBehavior = 'smooth'): boolean {
  if (target.kind === 'page-bottom') {
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior })
    return true
  }
  const el = findNavTargetElement(target)
  if (!el) return false
  el.scrollIntoView({ behavior, block: 'start' })
  return true
}

export function isNearPageBottom(thresholdPx = 80): boolean {
  return window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - thresholdPx
}

/** True when reading a section body after its header has scrolled fully off-screen. */
export function isInSectionBody(targets: FeedNavTarget[], currentIdx: number): boolean {
  if (currentIdx < 0) return false
  const target = targets[currentIdx]
  if (target.kind !== 'header') return false

  const el = findNavTargetElement(target)
  if (!el) return false

  const top = el.getBoundingClientRect().top
  // While the header row is still visible, up may jump to the previous section.
  if (top >= 0) return false

  const footerIdx = targets.length - 1
  const hasFooter = targets[footerIdx]?.kind === 'page-bottom'
  const lastHeaderIdx = hasFooter ? footerIdx - 1 : targets.length - 1
  return currentIdx <= lastHeaderIdx
}

export function resolveUpNavTargetIndex(
  targets: FeedNavTarget[],
  currentIdx: number,
): { targetIdx: number; snapBack: boolean } {
  if (currentIdx < 0) return { targetIdx: 0, snapBack: false }
  if (isInSectionBody(targets, currentIdx)) {
    return { targetIdx: currentIdx, snapBack: true }
  }
  return { targetIdx: Math.max(0, currentIdx - 1), snapBack: false }
}
