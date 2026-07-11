import { parseLogToSegments } from './logParser'

export type FeedNavTarget =
  | { kind: 'header'; entryKey: string }
  | { kind: 'segment'; entryKey: string; segmentIndex: number }

export interface FeedEntryOutline {
  type: string
  id: string
}

export function navTargetId(target: FeedNavTarget): string {
  return target.kind === 'header'
    ? `${target.entryKey}:header`
    : `${target.entryKey}:segment:${target.segmentIndex}`
}

export function buildFeedNavTargets(
  entries: FeedEntryOutline[],
  isCollapsed: (entryKey: string, entry: FeedEntryOutline) => boolean,
  getLogSegmentCount: (entryKey: string, entry: FeedEntryOutline) => number,
): FeedNavTarget[] {
  const targets: FeedNavTarget[] = []
  for (const entry of entries) {
    const entryKey = `${entry.type}:${entry.id}`
    if (isCollapsed(entryKey, entry)) continue
    if (entry.type === 'log') {
      const segmentCount = getLogSegmentCount(entryKey, entry)
      for (let i = 0; i < segmentCount; i++) {
        targets.push({ kind: 'segment', entryKey, segmentIndex: i })
      }
    } else {
      targets.push({ kind: 'header', entryKey })
    }
  }
  return targets
}

export function segmentCountFromLogContent(raw: string | undefined): number {
  if (raw === undefined || raw === '(loading…)') return 0
  return parseLogToSegments(raw).length
}

export function findNavTargetElement(target: FeedNavTarget): HTMLElement | null {
  if (target.kind === 'header') {
    return document.querySelector(
      `[data-feed-nav-key="${CSS.escape(target.entryKey)}"][data-feed-nav-type="header"]`,
    )
  }
  return document.querySelector(
    `[data-feed-nav-key="${CSS.escape(target.entryKey)}"][data-feed-nav-type="segment"][data-feed-nav-segment="${target.segmentIndex}"]`,
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
