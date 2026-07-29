import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, type TaskListEntry, type TaskListStatus } from './api'
import { isCloudMode } from './cloudAuth'
import {
  deliverTaskNotification,
  detectCompletionEvents,
  loadNotificationPreferences,
  shouldSuppressForRoute,
  createTestNotificationEvent,
  deliverTestBrowserNotification,
  deliverTestInAppNotification,
  type BrowserNotificationAttemptResult,
  type TaskCompletionEvent,
} from './taskNotifications'

const TASK_POLL_INTERVAL_MS = 1000
const DEFAULT_TAB_TITLE = 'Dev – Task management'

interface TaskListContextValue {
  tasks: TaskListEntry[]
  loading: boolean
  error: string | null
  refreshTasks: (opts?: { silent?: boolean }) => Promise<void>
  inAppNotifications: InAppNotification[]
  pushInAppNotification: (notification: Omit<InAppNotification, 'id'>) => void
  dismissInAppNotification: (id: string) => void
  deliverNotification: (event: TaskCompletionEvent, opts?: { ignoreRouteSuppression?: boolean }) => Promise<boolean>
  deliverTestInAppNotification: () => boolean
  deliverTestBrowserNotification: () => Promise<BrowserNotificationAttemptResult>
}

const TaskListContext = createContext<TaskListContextValue | null>(null)

export function useTaskList(): TaskListContextValue {
  const ctx = useContext(TaskListContext)
  if (!ctx) throw new Error('useTaskList must be used within TaskListProvider')
  return ctx
}

export interface InAppNotification {
  id: string
  taskName: string
  title: string
  clickUrl?: string
}

let inAppNotificationIdCounter = 0

function nextInAppNotificationId(): string {
  inAppNotificationIdCounter += 1
  return `in-app-${Date.now()}-${inAppNotificationIdCounter}`
}

interface PageTitleContextValue {
  pageTitle: string
  setPageTitle: (title: string) => void
  tabTitleOverride: { taskName: string; title: string } | null
  clearTabTitleOverride: () => void
}

const PageTitleContext = createContext<PageTitleContextValue | null>(null)

export function usePageTitle(title: string): void {
  const setPageTitle = useContext(PageTitleContext)?.setPageTitle
  useEffect(() => {
    if (setPageTitle) {
      setPageTitle(title)
      return () => setPageTitle(DEFAULT_TAB_TITLE)
    }
    document.title = title
    return () => {
      document.title = DEFAULT_TAB_TITLE
    }
  }, [title, setPageTitle])
}

function currentNotificationPermission(): NotificationPermission | 'unsupported' {
  if (typeof Notification === 'undefined') return 'unsupported'
  return Notification.permission
}

export function TaskListProvider({ children }: { children: ReactNode }) {
  const [tasks, setTasks] = useState<TaskListEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [inAppNotifications, setInAppNotifications] = useState<InAppNotification[]>([])
  const [pageTitle, setPageTitle] = useState(DEFAULT_TAB_TITLE)
  const [tabTitleOverride, setTabTitleOverride] = useState<{ taskName: string; title: string } | null>(null)

  const location = useLocation()
  const navigate = useNavigate()
  const tabVisibleRef = useRef(!document.hidden)
  const previousStatusesRef = useRef<Map<string, TaskListStatus>>(new Map())
  const pollInitializedRef = useRef(false)
  const notifiedKeysRef = useRef<Set<string>>(new Set())
  const locationPathnameRef = useRef(location.pathname)
  const refreshGenerationRef = useRef(0)
  const loadingGenerationRef = useRef<number | null>(null)
  const prevPathnameRef = useRef(location.pathname)

  locationPathnameRef.current = location.pathname

  const pushInAppNotification = useCallback((notification: Omit<InAppNotification, 'id'>) => {
    setInAppNotifications((current) => [
      { ...notification, id: nextInAppNotificationId() },
      ...current,
    ])
  }, [])

  const dismissInAppNotification = useCallback((id: string) => {
    setInAppNotifications((current) => current.filter((item) => item.id !== id))
  }, [])

  const deliverNotification = useCallback(async (
    event: TaskCompletionEvent,
    { ignoreRouteSuppression = false }: { ignoreRouteSuppression?: boolean } = {},
  ) => {
    const prefs = loadNotificationPreferences()
    if (!prefs.browserEnabled && !prefs.inAppEnabled) return false
    if (!ignoreRouteSuppression && shouldSuppressForRoute(event.taskName, locationPathnameRef.current)) return false

    return deliverTaskNotification(
      event,
      prefs,
      currentNotificationPermission(),
      tabVisibleRef.current,
      {
        navigateToTask: () => navigate(`/task/${encodeURIComponent(event.taskName)}`),
        showInApp: (notification) => pushInAppNotification(notification),
        showTabTitle: (override) => setTabTitleOverride(override),
      },
    )
  }, [navigate, pushInAppNotification])

  const deliverNotificationRef = useRef(deliverNotification)
  deliverNotificationRef.current = deliverNotification

  const processCompletionNotifications = useCallback(async (tasks: TaskListEntry[]) => {
    if (!isCloudMode()) return

    const prefs = loadNotificationPreferences()
    const { events, nextPrevious } = detectCompletionEvents(
      previousStatusesRef.current,
      tasks,
      pollInitializedRef.current,
    )
    previousStatusesRef.current = nextPrevious
    pollInitializedRef.current = true

    for (const event of events) {
      if (notifiedKeysRef.current.has(event.dedupeKey)) continue
      if (shouldSuppressForRoute(event.taskName, locationPathnameRef.current)) continue
      if (!prefs.browserEnabled && !prefs.inAppEnabled) continue
      const delivered = await deliverNotificationRef.current(event, { ignoreRouteSuppression: false })
      if (delivered) notifiedKeysRef.current.add(event.dedupeKey)
    }
  }, [])

  const deliverTestInAppNotificationHandler = useCallback(() => {
    const prefs = loadNotificationPreferences()
    return deliverTestInAppNotification(createTestNotificationEvent(), prefs, (notification) => {
      pushInAppNotification(notification)
    })
  }, [pushInAppNotification])

  const deliverTestBrowserNotificationHandler = useCallback(async (): Promise<BrowserNotificationAttemptResult> => {
    const prefs = loadNotificationPreferences()
    return deliverTestBrowserNotification(
      createTestNotificationEvent(),
      prefs,
      currentNotificationPermission(),
    )
  }, [])

  const refreshTasks = useCallback(async ({ silent = false } = {}) => {
    const generation = refreshGenerationRef.current + 1
    refreshGenerationRef.current = generation
    if (!silent) {
      setError(null)
      setLoading(true)
      loadingGenerationRef.current = generation
    }
    let fetchedTasks: TaskListEntry[] | null = null
    try {
      const res = await api.getTasks()
      if (generation === refreshGenerationRef.current) {
        fetchedTasks = res.tasks
        setTasks((current) => (tasksUnchanged(current, res.tasks) ? current : res.tasks))
        if (!silent) setError(null)
      }
    } catch (e) {
      if (generation === refreshGenerationRef.current && !silent) {
        setError(e instanceof Error ? e.message : String(e))
      }
    } finally {
      if (!silent && loadingGenerationRef.current === generation) {
        setLoading(false)
        loadingGenerationRef.current = null
      }
    }

    if (fetchedTasks && generation === refreshGenerationRef.current) {
      void processCompletionNotifications(fetchedTasks)
    }
  }, [processCompletionNotifications])

  useEffect(() => {
    void refreshTasks()
  }, [refreshTasks])

  useEffect(() => {
    const prev = prevPathnameRef.current
    prevPathnameRef.current = location.pathname
    const returnedToTaskList = location.pathname === '/' && /^\/task\//.test(prev)
    if (returnedToTaskList) {
      void refreshTasks({ silent: true })
    }
  }, [location.pathname, refreshTasks])

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
      if (isCloudMode()) {
        void refreshTasks({ silent: true })
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [refreshTasks])

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
    setInAppNotifications((current) => {
      const next = current.filter((item) => item.taskName !== viewedTask)
      return next.length === current.length ? current : next
    })
    setTabTitleOverride((current) => (current?.taskName === viewedTask ? null : current))
  }, [location.pathname])

  const clearTabTitleOverride = useCallback(() => setTabTitleOverride(null), [])

  const contextValue = useMemo<TaskListContextValue>(() => ({
    tasks,
    loading,
    error,
    refreshTasks,
    inAppNotifications,
    pushInAppNotification,
    dismissInAppNotification,
    deliverNotification,
    deliverTestInAppNotification: deliverTestInAppNotificationHandler,
    deliverTestBrowserNotification: deliverTestBrowserNotificationHandler,
  }), [
    tasks,
    loading,
    error,
    refreshTasks,
    inAppNotifications,
    pushInAppNotification,
    dismissInAppNotification,
    deliverNotification,
    deliverTestInAppNotificationHandler,
    deliverTestBrowserNotificationHandler,
  ])

  const pageTitleContextValue = useMemo(
    () => ({ pageTitle, setPageTitle, tabTitleOverride, clearTabTitleOverride }),
    [pageTitle, tabTitleOverride, clearTabTitleOverride],
  )

  return (
    <PageTitleContext.Provider value={pageTitleContextValue}>
      <TaskListContext.Provider value={contextValue}>
        {children}
      </TaskListContext.Provider>
    </PageTitleContext.Provider>
  )
}

function tasksUnchanged(current: TaskListEntry[], next: TaskListEntry[]): boolean {
  if (current.length !== next.length) return false
  for (let i = 0; i < current.length; i += 1) {
    if (current[i].name !== next[i].name || current[i].status !== next[i].status) return false
  }
  return true
}
