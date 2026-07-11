import { describe, expect, it, vi } from 'vitest'
import {
  buildFeedNavTargets,
  findCurrentNavIndex,
  navTargetId,
  scrollToNavTarget,
} from './feedScrollNav'

describe('buildFeedNavTargets', () => {
  const entries = [
    { type: 'comms', id: '001-user.md' },
    { type: 'log', id: 'run.log' },
    { type: 'comms', id: '002-reply.md' },
  ]

  it('skips collapsed entries and appends a page-bottom stop', () => {
    const collapsed = new Set(['comms:002-reply.md'])
    const targets = buildFeedNavTargets(entries, (key) => collapsed.has(key))
    expect(targets.map(navTargetId)).toEqual([
      'comms:001-user.md:header',
      'log:run.log:header',
      'page:bottom:footer',
    ])
  })

  it('includes comms and expanded log headers when not collapsed', () => {
    const targets = buildFeedNavTargets(entries, () => false)
    expect(targets.map(navTargetId)).toEqual([
      'comms:001-user.md:header',
      'log:run.log:header',
      'comms:002-reply.md:header',
      'page:bottom:footer',
    ])
  })

  it('always includes a page-bottom stop even with no feed entries', () => {
    const targets = buildFeedNavTargets([], () => false)
    expect(targets.map(navTargetId)).toEqual(['page:bottom:footer'])
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
    Object.defineProperty(document.documentElement, 'scrollHeight', { value: 5000, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true })
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true })
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

  it('returns the page-bottom index when near the page bottom', () => {
    const targets = buildFeedNavTargets([{ type: 'comms', id: 'a.md' }], () => false)
    document.body.innerHTML = ''
    Object.defineProperty(document.documentElement, 'scrollHeight', { value: 1000, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true })
    Object.defineProperty(window, 'scrollY', { value: 150, configurable: true })
    expect(findCurrentNavIndex(targets, 80)).toBe(targets.length - 1)
  })

  it('prefers a visible feed header over the page-bottom stop when near the bottom', () => {
    const targets = buildFeedNavTargets([{ type: 'comms', id: 'a.md' }], () => false)
    document.body.innerHTML = `<button data-feed-nav-type="header" data-feed-nav-key="comms:a.md"></button>`
    Object.defineProperty(document.documentElement, 'scrollHeight', { value: 1000, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true })
    Object.defineProperty(window, 'scrollY', { value: 150, configurable: true })
    const el = document.querySelector('[data-feed-nav-key="comms:a.md"]') as HTMLElement
    el.getBoundingClientRect = () =>
      ({ top: 50, bottom: 70, left: 0, right: 0, width: 0, height: 20, x: 0, y: 50, toJSON: () => ({}) }) as DOMRect
    expect(findCurrentNavIndex(targets, 80)).toBe(0)
  })
})

describe('scrollToNavTarget', () => {
  it('scrolls to absolute page bottom for the page-bottom target', () => {
    const scrollTo = vi.fn()
    window.scrollTo = scrollTo
    Object.defineProperty(document.documentElement, 'scrollHeight', { value: 1234, configurable: true })
    scrollToNavTarget({ kind: 'page-bottom' }, 'smooth')
    expect(scrollTo).toHaveBeenCalledWith({ top: 1234, behavior: 'smooth' })
  })
})
