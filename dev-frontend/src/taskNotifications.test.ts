import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  BROWSER_NOTIFICATIONS_KEY,
  INAPP_NOTIFICATIONS_KEY,
  chooseNotificationDelivery,
  chooseNotificationFallbackDelivery,
  deliverTaskNotification,
  deliverTestBrowserNotification,
  deliverTestInAppNotification,
  detectCompletionEvents,
  loadNotificationPreferences,
  saveNotificationPreferences,
  shouldSuppressForRoute,
} from './taskNotifications'
import { isCompletionTransition } from './taskStatus'

describe('taskStatus', () => {
  it('detects completion transitions from active states and into completion statuses', () => {
    expect(isCompletionTransition('running', 'plan_complete')).toBe(true)
    expect(isCompletionTransition('syncing', 'failed')).toBe(true)
    expect(isCompletionTransition('running', 'idle')).toBe(true)
    expect(isCompletionTransition('plan_complete', 'implement_complete')).toBe(true)
    expect(isCompletionTransition('ready_for_next_step', 'waiting_for_answers')).toBe(true)
    expect(isCompletionTransition('idle', 'plan_complete')).toBe(true)
    expect(isCompletionTransition('plan_complete', 'plan_complete')).toBe(false)
    expect(isCompletionTransition('idle', 'idle')).toBe(false)
    expect(isCompletionTransition('user_comment', 'idle')).toBe(false)
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

  it('chooses delivery split by tab visibility', () => {
    const prefs = { browserEnabled: true, inAppEnabled: true }
    expect(chooseNotificationDelivery(prefs, 'granted', true)).toBe('in_app')
    expect(chooseNotificationDelivery(prefs, 'granted', false)).toBe('browser')
    expect(chooseNotificationDelivery({ ...prefs, browserEnabled: false }, 'granted', true)).toBe('in_app')
    expect(chooseNotificationDelivery({ ...prefs, browserEnabled: false }, 'denied', false)).toBe('tab_title')
    expect(chooseNotificationDelivery({ browserEnabled: true, inAppEnabled: false }, 'granted', true)).toBe('none')
    expect(chooseNotificationDelivery({ browserEnabled: false, inAppEnabled: false }, 'granted', true)).toBe('none')
  })

  it('detects completion events after initialization only', () => {
    const previous = new Map([['foo', 'running' as const]])
    const first = detectCompletionEvents(previous, [{ name: 'foo', status: 'plan_complete' }], false)
    expect(first.events).toHaveLength(0)
    expect(first.nextPrevious.get('foo')).toBe('plan_complete')

    const second = detectCompletionEvents(first.nextPrevious, [{ name: 'foo', status: 'plan_complete' }], true)
    expect(second.events).toHaveLength(0)

    const third = detectCompletionEvents(second.nextPrevious, [{ name: 'foo', status: 'implement_complete' }], true)
    expect(third.events).toHaveLength(1)
    expect(third.events[0].title).toBe('Task foo — Implement complete')

    const fourth = detectCompletionEvents(
      new Map([['bar', 'idle' as const]]),
      [{ name: 'bar', status: 'plan_complete' }],
      true,
    )
    expect(fourth.events).toHaveLength(1)
  })

  it('suppresses notifications on the matching task feed route', () => {
    expect(shouldSuppressForRoute('my-task', '/task/my-task')).toBe(true)
    expect(shouldSuppressForRoute('my-task', '/task/other-task')).toBe(false)
    expect(shouldSuppressForRoute('my-task', '/settings')).toBe(false)
    expect(shouldSuppressForRoute('a/b', '/task/a%2Fb')).toBe(true)
  })

  it('cascades to in-app when browser delivery fails in the foreground', () => {
    const showInApp = vi.fn()
    const showTabTitle = vi.fn()
    const prefs = { browserEnabled: true, inAppEnabled: true }
    const originalNotification = globalThis.Notification

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(globalThis as any).Notification = class {
      static permission = 'granted'
      constructor() {
        throw new Error('blocked')
      }
    }

    try {
      const delivered = deliverTaskNotification(
        {
          taskName: 'foo',
          status: 'plan_complete',
          title: 'Task foo — Plan complete',
          dedupeKey: 'foo:running->plan_complete',
        },
        prefs,
        'granted',
        true,
        {
          navigateToTask: vi.fn(),
          showInApp,
          showTabTitle,
        },
      )
      expect(delivered).toBe(true)
      expect(showInApp).toHaveBeenCalledWith({ taskName: 'foo', title: 'Task foo — Plan complete' })
      expect(showTabTitle).not.toHaveBeenCalled()
    } finally {
      globalThis.Notification = originalNotification
    }
  })

  it('uses tab title fallback when browser delivery fails in the background', () => {
    expect(chooseNotificationFallbackDelivery({ browserEnabled: true, inAppEnabled: true }, false)).toBe('tab_title')
    expect(chooseNotificationFallbackDelivery({ browserEnabled: true, inAppEnabled: true }, true)).toBe('in_app')
  })

  it('delivers split test notifications independently', () => {
    const showInApp = vi.fn()
    const event = {
      taskName: 'notifications-test',
      status: 'plan_complete' as const,
      title: 'Task notifications test — Plan complete',
      dedupeKey: 'test-notification',
    }
    expect(deliverTestInAppNotification(event, { browserEnabled: false, inAppEnabled: false }, showInApp)).toBe(false)
    expect(deliverTestInAppNotification(event, { browserEnabled: true, inAppEnabled: true }, showInApp)).toBe(true)
    expect(showInApp).toHaveBeenCalledWith({
      taskName: 'notifications-test',
      title: 'Task notifications test — Plan complete',
    })

    const originalNotification = globalThis.Notification
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(globalThis as any).Notification = class {
      static permission = 'granted'
      onclick: (() => void) | null = null
      constructor(public title: string) {}
      close() {}
    }
    try {
      const foreground = deliverTestBrowserNotification(
        event,
        { browserEnabled: true, inAppEnabled: true },
        'granted',
        vi.fn(),
      )
      expect(foreground.delivered).toBe(true)

      const background = deliverTestBrowserNotification(
        event,
        { browserEnabled: true, inAppEnabled: true },
        'granted',
        vi.fn(),
      )
      expect(background.delivered).toBe(true)
      expect(deliverTestBrowserNotification(
        event,
        { browserEnabled: false, inAppEnabled: true },
        'granted',
        vi.fn(),
      ).delivered).toBe(false)
    } finally {
      globalThis.Notification = originalNotification
    }
  })
})
