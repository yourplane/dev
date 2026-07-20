import type { TaskListStatus } from './api'
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
  showInApp: (notification: { taskName: string; title: string }) => void
  showTabTitle: (override: { taskName: string; title: string }) => void
}

export function deliverTaskNotification(
  event: TaskCompletionEvent,
  prefs: NotificationPreferences,
  permission: NotificationPermission | 'unsupported',
  tabVisible: boolean,
  handlers: TaskNotificationHandlers,
): boolean {
  const primary = chooseNotificationDelivery(prefs, permission, tabVisible)
  if (primary === 'none') return false

  if (primary === 'browser') {
    const notification = showBrowserNotification(event.title, event.taskName, handlers.navigateToTask)
    if (notification) return true
    const fallback = chooseNotificationFallbackDelivery(prefs, tabVisible)
    if (fallback === 'in_app') {
      handlers.showInApp({ taskName: event.taskName, title: event.title })
      return true
    }
    if (fallback === 'tab_title') {
      handlers.showTabTitle({ taskName: event.taskName, title: event.title })
      return true
    }
    return false
  }

  if (primary === 'in_app') {
    handlers.showInApp({ taskName: event.taskName, title: event.title })
    return true
  }

  if (primary === 'tab_title') {
    handlers.showTabTitle({ taskName: event.taskName, title: event.title })
    return true
  }

  return false
}

export function createTestNotificationEvent(): TaskCompletionEvent {
  const status = 'plan_complete' as const
  return {
    taskName: 'notifications-test',
    status,
    title: completionNotificationTitle('notifications test', status),
    dedupeKey: 'test-notification',
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

export function showBrowserNotification(
  title: string,
  taskName: string,
  onClick: () => void,
): Notification | null {
  if (typeof Notification === 'undefined') return null
  try {
    const notification = new Notification(title, { tag: `dev-task-${taskName}` })
    notification.onclick = () => {
      window.focus()
      onClick()
      notification.close()
    }
    return notification
  } catch {
    return null
  }
}
