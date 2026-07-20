import { describe, it, expect, beforeEach } from 'vitest'
import {
  BROWSER_NOTIFICATIONS_KEY,
  INAPP_NOTIFICATIONS_KEY,
  chooseNotificationDelivery,
  detectCompletionEvents,
  loadNotificationPreferences,
  saveNotificationPreferences,
  shouldSuppressForRoute,
} from './taskNotifications'
import { isCompletionTransition } from './taskStatus'

describe('taskStatus', () => {
  it('detects completion transitions from active states', () => {
    expect(isCompletionTransition('running', 'plan_complete')).toBe(true)
    expect(isCompletionTransition('syncing', 'failed')).toBe(true)
    expect(isCompletionTransition('running', 'idle')).toBe(true)
    expect(isCompletionTransition('idle', 'plan_complete')).toBe(false)
    expect(isCompletionTransition('running', 'user_comment')).toBe(false)
  })
})

describe('taskNotifications', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('loads and saves notification preferences', () => {
    expect(loadNotificationPreferences()).toEqual({ browserEnabled: false, inAppEnabled: false })
    saveNotificationPreferences({ browserEnabled: true, inAppEnabled: true })
    expect(localStorage.getItem(BROWSER_NOTIFICATIONS_KEY)).toBe('true')
    expect(localStorage.getItem(INAPP_NOTIFICATIONS_KEY)).toBe('true')
    expect(loadNotificationPreferences()).toEqual({ browserEnabled: true, inAppEnabled: true })
  })

  it('chooses delivery with OS-first priority', () => {
    const prefs = { browserEnabled: true, inAppEnabled: true }
    expect(chooseNotificationDelivery(prefs, 'granted', true)).toBe('browser')
    expect(chooseNotificationDelivery(prefs, 'denied', true)).toBe('in_app')
    expect(chooseNotificationDelivery({ ...prefs, browserEnabled: false }, 'granted', true)).toBe('in_app')
    expect(chooseNotificationDelivery({ ...prefs, browserEnabled: false }, 'denied', false)).toBe('tab_title')
    expect(chooseNotificationDelivery({ browserEnabled: false, inAppEnabled: false }, 'granted', true)).toBe('none')
  })

  it('detects completion events after initialization only', () => {
    const previous = new Map([['foo', 'running' as const]])
    const first = detectCompletionEvents(previous, [{ name: 'foo', status: 'plan_complete' }], false)
    expect(first.events).toHaveLength(0)
    expect(first.nextPrevious.get('foo')).toBe('plan_complete')

    const second = detectCompletionEvents(first.nextPrevious, [{ name: 'foo', status: 'plan_complete' }], true)
    expect(second.events).toHaveLength(0)

    const third = detectCompletionEvents(second.nextPrevious, [{ name: 'foo', status: 'running' }], true)
    expect(third.events).toHaveLength(0)

    const fourth = detectCompletionEvents(third.nextPrevious, [{ name: 'foo', status: 'implement_complete' }], true)
    expect(fourth.events).toHaveLength(1)
    expect(fourth.events[0].title).toBe('Task foo — Implement complete')
  })

  it('suppresses notifications on the matching task feed route', () => {
    expect(shouldSuppressForRoute('my-task', '/task/my-task')).toBe(true)
    expect(shouldSuppressForRoute('my-task', '/task/other-task')).toBe(false)
    expect(shouldSuppressForRoute('my-task', '/settings')).toBe(false)
    expect(shouldSuppressForRoute('a/b', '/task/a%2Fb')).toBe(true)
  })
})
