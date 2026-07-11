import { describe, expect, it } from 'vitest'
import { buildFeedNavTargets, findCurrentNavIndex, navTargetId } from './feedScrollNav'

describe('buildFeedNavTargets', () => {
  const entries = [
    { type: 'comms', id: '001-user.md' },
    { type: 'log', id: 'run.log' },
    { type: 'comms', id: '002-reply.md' },
  ]

  it('skips collapsed entries and uses one header stop per expanded entry', () => {
    const collapsed = new Set(['comms:002-reply.md'])
    const targets = buildFeedNavTargets(entries, (key) => collapsed.has(key))
    expect(targets.map(navTargetId)).toEqual(['comms:001-user.md:header', 'log:run.log:header'])
  })

  it('includes comms and expanded log headers when not collapsed', () => {
    const targets = buildFeedNavTargets(entries, () => false)
    expect(targets.map(navTargetId)).toEqual([
      'comms:001-user.md:header',
      'log:run.log:header',
      'comms:002-reply.md:header',
    ])
  })
})

describe('findCurrentNavIndex', () => {
  it('picks the last target at or above the viewport anchor', () => {
    const targets = buildFeedNavTargets(
      [
        { type: 'comms', id: 'a.md' },
        { type: 'comms', id: 'b.md' },
        { type: 'comms', id: 'c.md' },
      ],
      () => false,
    )
    document.body.innerHTML = `
      <button data-feed-nav-type="header" data-feed-nav-key="comms:a.md"></button>
      <button data-feed-nav-type="header" data-feed-nav-key="comms:b.md"></button>
      <button data-feed-nav-type="header" data-feed-nav-key="comms:c.md"></button>
    `
    const rects: Record<string, number> = {
      'comms:a.md': 0,
      'comms:b.md': 100,
      'comms:c.md': 200,
    }
    for (const [key, top] of Object.entries(rects)) {
      const el = document.querySelector(`[data-feed-nav-key="${key}"]`) as HTMLElement
      el.getBoundingClientRect = () =>
        ({ top, bottom: top + 20, left: 0, right: 0, width: 0, height: 20, x: 0, y: top, toJSON: () => ({}) }) as DOMRect
    }
    expect(findCurrentNavIndex(targets, 80)).toBe(0)

    rects['comms:b.md'] = 50
    rects['comms:c.md'] = 200
    for (const [key, top] of Object.entries(rects)) {
      const el = document.querySelector(`[data-feed-nav-key="${key}"]`) as HTMLElement
      el.getBoundingClientRect = () =>
        ({ top, bottom: top + 20, left: 0, right: 0, width: 0, height: 20, x: 0, y: top, toJSON: () => ({}) }) as DOMRect
    }
    expect(findCurrentNavIndex(targets, 80)).toBe(1)
  })
})
