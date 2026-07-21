import type { TaskListStatus } from './api'
import { showServiceWorkerNotification } from './notificationServiceWorker'
import { completionNotificationTitle, isCompletionTransition } from './taskStatus'

export const BROWSER_NOTIFICATIONS_KEY = 'dev_notifications_browser_enabled'
export const INAPP_NOTIFICATIONS_KEY = 'dev_notifications_inapp_enabled'

export interface NotificationPreferences {
  browserEnabled: boolean
  inAppEnabled: boolean
}

export function loadNotificationPreferences(): NotificationPreferences {
  try {
    return {
      browserEnabled: localStorage.getItem(BROWSER_NOTIFICATIONS_KEY) === 'true',
      inAppEnabled: localStorage.getItem(INAPP_NOTIFICATIONS_KEY) === 'true',
    }
  } catch {
    return { browserEnabled: false, inAppEnabled: false }
  }
}

export function saveNotificationPreferences(prefs: NotificationPreferences): void {
  try {
    localStorage.setItem(BROWSER_NOTIFICATIONS_KEY, prefs.browserEnabled ? 'true' : 'false')
    localStorage.setItem(INAPP_NOTIFICATIONS_KEY, prefs.inAppEnabled ? 'true' : 'false')
  } catch {
    // ignore storage errors
  }
}

export type NotificationDelivery = 'browser' | 'in_app' | 'tab_title' | 'none'

export function chooseNotificationDelivery(
  prefs: NotificationPreferences,
  permission: NotificationPermission | 'unsupported',
  tabVisible: boolean,
): NotificationDelivery {
  if (tabVisible) {
    if (prefs.inAppEnabled) return 'in_app'
    return 'none'
  }
  if (prefs.browserEnabled && permission === 'granted') return 'browser'
  if (prefs.inAppEnabled) return 'tab_title'
  return 'none'
}

export function chooseNotificationFallbackDelivery(
  prefs: NotificationPreferences,
  tabVisible: boolean,
): NotificationDelivery {
  if (tabVisible && prefs.inAppEnabled) return 'in_app'
  if (!tabVisible && prefs.inAppEnabled) return 'tab_title'
  return 'none'
}

export interface TaskNotificationHandlers {
  navigateToTask: () => void
  showInApp: (notification: { taskName: string; title: string; clickUrl?: string }) => void
  showTabTitle: (override: { taskName: string; title: string }) => void
}

export async function deliverTaskNotification(
  event: TaskCompletionEvent,
  prefs: NotificationPreferences,
  permission: NotificationPermission | 'unsupported',
  tabVisible: boolean,
  handlers: TaskNotificationHandlers,
): Promise<boolean> {
  const primary = chooseNotificationDelivery(prefs, permission, tabVisible)
  if (primary === 'none') return false

  if (primary === 'browser') {
    const delivered = await showBrowserNotification(event.title, event.taskName, event.clickUrl)
    if (delivered) return true
    const fallback = chooseNotificationFallbackDelivery(prefs, tabVisible)
    if (fallback === 'in_app') {
      handlers.showInApp({ taskName: event.taskName, title: event.title, clickUrl: event.clickUrl })
      return true
    }
    if (fallback === 'tab_title') {
      handlers.showTabTitle({ taskName: event.taskName, title: event.title })
      return true
    }
    return false
  }

  if (primary === 'in_app') {
    handlers.showInApp({ taskName: event.taskName, title: event.title, clickUrl: event.clickUrl })
    return true
  }

  if (primary === 'tab_title') {
    handlers.showTabTitle({ taskName: event.taskName, title: event.title })
    return true
  }

  return false
}

export const TEST_NOTIFICATION_TITLE = 'Test notification'

export function createTestNotificationEvent(): TaskCompletionEvent {
  return {
    taskName: 'notifications-test',
    status: 'plan_complete',
    title: TEST_NOTIFICATION_TITLE,
    dedupeKey: 'test-notification',
    clickUrl: '/settings',
  }
}

export function deliverTestInAppNotification(
  event: TaskCompletionEvent,
  prefs: NotificationPreferences,
  showInApp: (notification: { taskName: string; title: string; clickUrl?: string }) => void,
): boolean {
  if (!prefs.inAppEnabled) return false
  showInApp({ taskName: event.taskName, title: event.title, clickUrl: event.clickUrl })
  return true
}

export interface BrowserNotificationAttemptResult {
  delivered: boolean
  failureReason?: string
}

export async function deliverTestBrowserNotification(
  event: TaskCompletionEvent,
  prefs: NotificationPreferences,
  permission: NotificationPermission | 'unsupported',
): Promise<BrowserNotificationAttemptResult> {
  if (!prefs.browserEnabled) {
    return {
      delivered: false,
      failureReason: 'Browser notifications are disabled. Turn on the browser notifications toggle above.',
    }
  }
  if (permission === 'unsupported') {
    return {
      delivered: false,
      failureReason: 'This browser does not support the Web Notifications API.',
    }
  }
  if (permission === 'denied') {
    return {
      delivered: false,
      failureReason: 'Browser notification permission is blocked. Allow notifications for this site in your browser settings, then try again.',
    }
  }
  if (permission === 'default') {
    return {
      delivered: false,
      failureReason: 'Browser notification permission has not been granted yet. Click Enable browser notifications first.',
    }
  }

  const delivered = await showBrowserNotification(event.title, event.taskName, event.clickUrl)
  if (delivered) return { delivered: true }

  return {
    delivered: false,
    failureReason: 'The browser refused to create an OS notification. Check site notification settings, Do Not Disturb / focus modes, and try again with the Dev tab in the background.',
  }
}

export function completionDedupeKey(taskName: string, prev: TaskListStatus, next: TaskListStatus): string {
  return `${taskName}:${prev}->${next}`
}

export interface TaskCompletionEvent {
  taskName: string
  status: TaskListStatus
  title: string
  dedupeKey: string
  clickUrl?: string
}

export function detectCompletionEvents(
  previous: Map<string, TaskListStatus>,
  tasks: Array<{ name: string; status: TaskListStatus }>,
  initialized: boolean,
): { events: TaskCompletionEvent[]; nextPrevious: Map<string, TaskListStatus> } {
  const nextPrevious = new Map<string, TaskListStatus>()
  const events: TaskCompletionEvent[] = []

  for (const task of tasks) {
    const prev = previous.get(task.name)
    nextPrevious.set(task.name, task.status)
    if (!initialized || prev === undefined) continue
    if (!isCompletionTransition(prev, task.status)) continue
    events.push({
      taskName: task.name,
      status: task.status,
      title: completionNotificationTitle(task.name, task.status),
      dedupeKey: completionDedupeKey(task.name, prev, task.status),
    })
  }

  return { events, nextPrevious }
}

export function shouldSuppressForRoute(taskName: string, pathname: string): boolean {
  const match = pathname.match(/^\/task\/([^/]+)/)
  if (!match) return false
  try {
    return decodeURIComponent(match[1]) === taskName
  } catch {
    return match[1] === taskName
  }
}

export async function showBrowserNotification(
  title: string,
  taskName: string,
  clickUrl?: string,
): Promise<boolean> {
  if (typeof Notification === 'undefined') return false
  return showServiceWorkerNotification(title, taskName, clickUrl)
}
