import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, type TaskListEntry, type TaskListStatus } from './api'
import { isCloudMode } from './cloudAuth'
import {
  chooseNotificationDelivery,
  detectCompletionEvents,
  loadNotificationPreferences,
  shouldSuppressForRoute,
  showBrowserNotification,
  type NotificationDelivery,
  type TaskCompletionEvent,
} from './taskNotifications'

const TASK_POLL_INTERVAL_MS = 1000
const DEFAULT_TAB_TITLE = 'Dev – Task management'

interface TaskListContextValue {
  tasks: TaskListEntry[]
  loading: boolean
  error: string | null
  refreshTasks: (opts?: { silent?: boolean }) => Promise<void>
  inAppNotification: InAppNotification | null
  setInAppNotification: (n: InAppNotification | null) => void
}

const TaskListContext = createContext<TaskListContextValue | null>(null)

export function useTaskList(): TaskListContextValue {
  const ctx = useContext(TaskListContext)
  if (!ctx) throw new Error('useTaskList must be used within TaskListProvider')
  return ctx
}

export interface InAppNotification {
  taskName: string
  title: string
}

interface PageTitleContextValue {
  pageTitle: string
  setPageTitle: (title: string) => void
  tabTitleOverride: { taskName: string; title: string } | null
  clearTabTitleOverride: () => void
}

const PageTitleContext = createContext<PageTitleContextValue | null>(null)

export function usePageTitle(title: string): void {
  const ctx = useContext(PageTitleContext)
  useEffect(() => {
    if (ctx) {
      ctx.setPageTitle(title)
      return () => ctx.setPageTitle(DEFAULT_TAB_TITLE)
    }
    document.title = title
    return () => {
      document.title = DEFAULT_TAB_TITLE
    }
  }, [title, ctx])
}

function currentNotificationPermission(): NotificationPermission | 'unsupported' {
  if (typeof Notification === 'undefined') return 'unsupported'
  return Notification.permission
}

function deliverCompletion(
  event: TaskCompletionEvent,
  delivery: NotificationDelivery,
  navigate: (path: string) => void,
  setInAppNotification: (n: InAppNotification | null) => void,
  setTabTitleOverride: (override: { taskName: string; title: string } | null) => void,
): void {
  const openTask = () => navigate(`/task/${encodeURIComponent(event.taskName)}`)

  if (delivery === 'browser') {
    showBrowserNotification(event.title, event.taskName, openTask)
    return
  }
  if (delivery === 'in_app') {
    setInAppNotification({ taskName: event.taskName, title: event.title })
    return
  }
  if (delivery === 'tab_title') {
    setTabTitleOverride({ taskName: event.taskName, title: event.title })
  }
}

export function TaskNotificationBanner() {
  const ctx = useContext(TaskListContext)
  const navigate = useNavigate()
  if (!ctx?.inAppNotification || !isCloudMode()) return null
  const { inAppNotification, setInAppNotification } = ctx
  return (
    <div className="task-notification-banner">
      <button
        type="button"
        className="task-notification-banner-main"
        onClick={() => {
          setInAppNotification(null)
          navigate(`/task/${encodeURIComponent(inAppNotification.taskName)}`)
        }}
      >
        {inAppNotification.title}
      </button>
      <button
        type="button"
        className="archive-dismiss-btn"
        onClick={() => setInAppNotification(null)}
      >
        Dismiss
      </button>
    </div>
  )
}

export function TaskListProvider({ children }: { children: ReactNode }) {
  const [tasks, setTasks] = useState<TaskListEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [inAppNotification, setInAppNotification] = useState<InAppNotification | null>(null)
  const [pageTitle, setPageTitle] = useState(DEFAULT_TAB_TITLE)
  const [tabTitleOverride, setTabTitleOverride] = useState<{ taskName: string; title: string } | null>(null)

  const location = useLocation()
  const navigate = useNavigate()
  const tabVisibleRef = useRef(!document.hidden)
  const previousStatusesRef = useRef<Map<string, TaskListStatus>>(new Map())
  const pollInitializedRef = useRef(false)
  const notifiedKeysRef = useRef<Set<string>>(new Set())

  const refreshTasks = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setError(null)
      setLoading(true)
    }
    try {
      const res = await api.getTasks()
      setTasks(res.tasks)
      if (!silent) setError(null)

      if (isCloudMode()) {
        const prefs = loadNotificationPreferences()
        const { events, nextPrevious } = detectCompletionEvents(
          previousStatusesRef.current,
          res.tasks,
          pollInitializedRef.current,
        )
        previousStatusesRef.current = nextPrevious
        pollInitializedRef.current = true

        const tabVisible = tabVisibleRef.current
        const delivery = chooseNotificationDelivery(prefs, currentNotificationPermission(), tabVisible)

        for (const event of events) {
          if (notifiedKeysRef.current.has(event.dedupeKey)) continue
          if (shouldSuppressForRoute(event.taskName, location.pathname)) continue
          if (delivery === 'none') continue
          notifiedKeysRef.current.add(event.dedupeKey)
          deliverCompletion(event, delivery, navigate, setInAppNotification, setTabTitleOverride)
        }
      }
    } catch (e) {
      if (!silent) setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (!silent) setLoading(false)
    }
  }, [location.pathname, navigate])

  useEffect(() => {
    void refreshTasks()
  }, [refreshTasks])

  useEffect(() => {
    const interval = setInterval(() => {
      const pollWhileHidden = isCloudMode()
      if (pollWhileHidden || !document.hidden) {
        void refreshTasks({ silent: true })
      }
    }, TASK_POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [refreshTasks])

  useEffect(() => {
    const onVisibility = () => {
      const visible = !document.hidden
      tabVisibleRef.current = visible
      if (visible) {
        setTabTitleOverride(null)
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [])

  useEffect(() => {
    if (isCloudMode() && tabTitleOverride && document.hidden) {
      document.title = `● ${tabTitleOverride.title}`
      return
    }
    document.title = pageTitle
  }, [pageTitle, tabTitleOverride])

  useEffect(() => {
    if (!isCloudMode()) return
    const match = location.pathname.match(/^\/task\/([^/]+)/)
    if (!match) return
    const viewedTask = decodeURIComponent(match[1])
    setInAppNotification((current) => (current?.taskName === viewedTask ? null : current))
    setTabTitleOverride((current) => (current?.taskName === viewedTask ? null : current))
  }, [location.pathname])

  const clearTabTitleOverride = useCallback(() => setTabTitleOverride(null), [])

  const contextValue: TaskListContextValue = {
    tasks,
    loading,
    error,
    refreshTasks,
    inAppNotification,
    setInAppNotification,
  }

  return (
    <PageTitleContext.Provider value={{ pageTitle, setPageTitle, tabTitleOverride, clearTabTitleOverride }}>
      <TaskListContext.Provider value={contextValue}>
        {children}
      </TaskListContext.Provider>
    </PageTitleContext.Provider>
  )
}
