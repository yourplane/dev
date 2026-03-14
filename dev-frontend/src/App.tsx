import { useState, useEffect, useCallback, useRef } from 'react'
import { BrowserRouter, Link, Routes, Route, useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { api, apiBaseUrl } from './api'
import { parseLogToSegments, type LogSegment } from './logParser'
import './App.css'

export function Layout() {
  return (
    <div className="app">
      <header className="header">
        <h1 className="logo"><Link to="/">Dev</Link></h1>
        <nav>
          <Link to="/" className="nav-link">Tasks</Link>
          <Link to="/new" className="nav-link">New task</Link>
          <Link to="/archive" className="nav-link">Archive</Link>
        </nav>
      </header>
      <main className="main">
        <Routes>
          <Route index element={<TaskListPage />} />
          <Route path="new" element={<CreateTaskPage />} />
          <Route path="archive" element={<ArchivePage />} />
          <Route path="task/:taskName" element={<TaskCommsPage />} />
        </Routes>
      </main>
    </div>
  )
}

const DEFAULT_TAB_TITLE = 'Dev – Task management'

function TaskListPage() {
  const [tasks, setTasks] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastArchived, setLastArchived] = useState<{ archivedName: string; taskName: string } | null>(() => {
    try {
      const raw = sessionStorage.getItem('dev_undo_archive')
      if (raw) {
        sessionStorage.removeItem('dev_undo_archive')
        return JSON.parse(raw) as { archivedName: string; taskName: string }
      }
    } catch {
      // ignore
    }
    return null
  })

  const loadTasks = useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const res = await api.getTasks()
      setTasks(res.tasks)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadTasks()
  }, [loadTasks])

  const handleUndoArchive = useCallback(async () => {
    if (!lastArchived) return
    try {
      await api.unarchiveTask(lastArchived.archivedName)
      setLastArchived(null)
      loadTasks()
    } catch {
      // leave banner so user can retry or dismiss
    }
  }, [lastArchived, loadTasks])

  return (
    <>
      {lastArchived && (
        <div className="archive-undo-banner">
          <span>Task {lastArchived.taskName} archived.</span>
          <button type="button" className="archive-undo-btn" onClick={handleUndoArchive}>Undo</button>
          <button type="button" className="archive-dismiss-btn" onClick={() => setLastArchived(null)}>Dismiss</button>
        </div>
      )}
      <TaskList
        tasks={tasks}
        loading={loading}
        error={error}
        onRefresh={loadTasks}
        onArchived={setLastArchived}
      />
    </>
  )
}

function TaskList({
  tasks,
  loading,
  error,
  onRefresh,
  onArchived,
}: {
  tasks: string[]
  loading: boolean
  error: string | null
  onRefresh: () => void
  onArchived?: (info: { archivedName: string; taskName: string }) => void
}) {
  const [archiving, setArchiving] = useState<string | null>(null)
  const [archiveError, setArchiveError] = useState<string | null>(null)

  const handleArchive = async (taskName: string) => {
    if (!confirm(`Archive task "${taskName}"?`)) return
    setArchiveError(null)
    setArchiving(taskName)
    try {
      const res = await api.archiveTask(taskName)
      onRefresh()
      const archivedName = res.archived_to.split('/').pop() ?? ''
      onArchived?.({ archivedName, taskName })
    } catch (e) {
      setArchiveError(e instanceof Error ? e.message : String(e))
    } finally {
      setArchiving(null)
    }
  }

  if (loading) return <p className="status">Loading tasks…</p>
  if (error) {
    return (
      <div className="status error">
        <p className="error-title">Could not connect to dev-server</p>
        <p>{error}</p>
        <p className="hint">
          Ensure dev-server is running from the dev repo root: <code>uv run --project dev-server uvicorn dev_server.main:app --reload --host 127.0.0.1</code>.
          The client uses <code>{apiBaseUrl}</code> (default <code>/api</code> via Vite proxy; set <code>VITE_DEV_SERVER_URL</code> in <code>.env</code> to override).
        </p>
        <button type="button" onClick={onRefresh}>Retry</button>
      </div>
    )
  }

  return (
    <section className="task-list">
      <h2>Tasks</h2>
      <p className="task-list-archive-link"><Link to="/archive">View archive</Link></p>
      {archiveError && <p className="inline-error">{archiveError}</p>}
      {tasks.length === 0 ? (
        <p className="empty">No tasks yet. Create one from “New task”.</p>
      ) : (
        <ul>
          {tasks.map((name) => (
            <li key={name} className="task-row">
              <Link to={`/task/${encodeURIComponent(name)}`} className="task-name">{name}</Link>
              <button
                type="button"
                className="archive-btn"
                onClick={() => handleArchive(name)}
                disabled={archiving === name}
              >
                {archiving === name ? 'Archiving…' : 'Archive'}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function CreateTaskPage() {
  const navigate = useNavigate()
  useEffect(() => {
    document.title = 'Dev – New task'
    return () => { document.title = DEFAULT_TAB_TITLE }
  }, [])
  return (
    <CreateTaskForm
      onCreated={(taskName) => navigate(`/task/${encodeURIComponent(taskName)}`)}
      onCancel={() => navigate('/')}
    />
  )
}

function formatArchiveDateLabel(dateStr: string): string {
  if (!dateStr) return 'Unknown date'
  const [month, day] = dateStr.split('-')
  const months: Record<string, string> = {
    jan: 'Jan', feb: 'Feb', mar: 'Mar', apr: 'Apr', may: 'May', jun: 'Jun',
    jul: 'Jul', aug: 'Aug', sep: 'Sep', oct: 'Oct', nov: 'Nov', dec: 'Dec',
  }
  return `${day} ${months[month] ?? month}`
}

function ArchivePage() {
  const [entries, setEntries] = useState<Array<{ archived_name: string; task_name: string; archived_date: string }>>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [unarchiving, setUnarchiving] = useState<string | null>(null)
  const [unarchiveError, setUnarchiveError] = useState<string | null>(null)
  const [restoredTask, setRestoredTask] = useState<string | null>(null)

  const loadArchive = useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const res = await api.getArchive()
      setEntries(res.entries)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    document.title = 'Dev – Archive'
    return () => { document.title = DEFAULT_TAB_TITLE }
  }, [])

  useEffect(() => {
    loadArchive()
  }, [loadArchive])

  const handleUnarchive = async (archivedName: string) => {
    if (!confirm(`Unarchive this task?`)) return
    setUnarchiveError(null)
    setUnarchiving(archivedName)
    setRestoredTask(null)
    try {
      const res = await api.unarchiveTask(archivedName)
      setRestoredTask(res.restored_task_name)
      await loadArchive()
    } catch (e) {
      setUnarchiveError(e instanceof Error ? e.message : String(e))
    } finally {
      setUnarchiving(null)
    }
  }

  const byDate = entries.reduce<Record<string, typeof entries>>((acc, e) => {
    const d = e.archived_date || 'unknown'
    if (!acc[d]) acc[d] = []
    acc[d].push(e)
    return acc
  }, {})
  const dateOrder = [...new Set(entries.map((e) => e.archived_date || 'unknown'))].sort().reverse()

  if (loading) return <p className="status">Loading archive…</p>
  if (error) {
    return (
      <section className="archive-view">
        <p className="inline-error">{error}</p>
        <p><Link to="/">← Back to tasks</Link></p>
      </section>
    )
  }

  return (
    <section className="archive-view">
      <h2>Archive</h2>
      <p><Link to="/">← Back to tasks</Link></p>
      {unarchiveError && <p className="inline-error">{unarchiveError}</p>}
      {restoredTask && (
        <p className="archive-restored">
          Restored. <Link to={`/task/${encodeURIComponent(restoredTask)}`}>Open {restoredTask}</Link>
        </p>
      )}
      {entries.length === 0 ? (
        <p className="empty">No archived tasks.</p>
      ) : (
        <div className="archive-by-date">
          {dateOrder.map((dateKey) => (
            <div key={dateKey} className="archive-date-group">
              <h3>{formatArchiveDateLabel(dateKey)}</h3>
              <ul>
                {byDate[dateKey].map((e) => (
                  <li key={e.archived_name} className="task-row">
                    <span className="task-name">{e.task_name}</span>
                    <button
                      type="button"
                      className="unarchive-btn"
                      onClick={() => handleUnarchive(e.archived_name)}
                      disabled={unarchiving === e.archived_name}
                    >
                      {unarchiving === e.archived_name ? 'Unarchiving…' : 'Unarchive'}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function CreateTaskForm({
  onCreated,
  onCancel,
}: {
  onCreated: (taskName: string) => void
  onCancel: () => void
}) {
  const [repos, setRepos] = useState<Record<string, string>>({})
  const [reposLoading, setReposLoading] = useState(true)
  const [title, setTitle] = useState('')
  const [repo, setRepo] = useState('')
  const [repoCustom, setRepoCustom] = useState('')
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.getRepos().then((r) => {
      if (!cancelled) setRepos(r)
    }).finally(() => {
      if (!cancelled) setReposLoading(false)
    })
    return () => { cancelled = true }
  }, [])

  const repoValue = repo === '__custom__' ? repoCustom : repo

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!title.trim()) { setError('Title is required'); return }
    if (!repoValue.trim()) { setError('Repo is required (select a shorthand or enter a URL)'); return }
    setSubmitting(true)
    try {
      const res = await api.createTask({
        title: title.trim(),
        repo: repoValue.trim(),
        comment: comment.trim() || undefined,
      })
      onCreated(res.task_name)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="create-form">
      <h2>New task</h2>
      <form onSubmit={handleSubmit}>
        {error && <p className="inline-error">{error}</p>}
        <label>
          <span>Title <span className="required">*</span></span>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Task title"
            required
          />
        </label>
        <label>
          <span>Repo <span className="required">*</span></span>
          {reposLoading ? (
            <span className="hint">Loading shorthands…</span>
          ) : (
            <div className="repo-radio-group" role="radiogroup" aria-label="Repo">
              {Object.entries(repos).map(([name, url]) => (
                <label key={name} className="repo-radio-option">
                  <input
                    type="radio"
                    name="repo"
                    value={name}
                    checked={repo === name}
                    onChange={() => setRepo(name)}
                  />
                  <span>{name} — {url}</span>
                </label>
              ))}
              <label className="repo-radio-option">
                <input
                  type="radio"
                  name="repo"
                  value="__custom__"
                  checked={repo === '__custom__'}
                  onChange={() => setRepo('__custom__')}
                />
                <span>Custom URL…</span>
              </label>
              {repo === '__custom__' && (
                <input
                  type="text"
                  value={repoCustom}
                  onChange={(e) => setRepoCustom(e.target.value)}
                  placeholder="https://github.com/user/repo.git"
                  className="repo-custom"
                />
              )}
            </div>
          )}
        </label>
        <label>
          Description / comment
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Optional"
            rows={3}
          />
        </label>
        <div className="form-actions">
          <button type="submit" disabled={submitting}>
            {submitting ? 'Creating…' : 'Create task'}
          </button>
          <button type="button" onClick={onCancel}>Cancel</button>
        </div>
      </form>
      <p className="hint">
        Repo shorthands are configured via the CLI: <code>dev repos add &lt;name&gt; &lt;url&gt;</code> (stored in <code>~/.config/dev/repos.json</code>).
      </p>
    </section>
  )
}

const COMMAND_LABEL: Record<string, string> = {
  'plan-implement': 'Plan',
  implement: 'Implement',
}

function ParsedLogView({ raw }: { raw: string }) {
  const segments = parseLogToSegments(raw)
  if (segments.length === 0) {
    return <pre className="feed-log-content feed-log-raw">(no parseable events)</pre>
  }
  return (
    <div className="feed-log-parsed">
      {segments.map((seg, i) => (
        <LogSegmentBlock key={i} segment={seg} />
      ))}
    </div>
  )
}

function LogSegmentBlock({ segment }: { segment: LogSegment }) {
  const { type, text } = segment
  const label = type === 'tool_call' ? 'Tool call' : type === 'thinking' ? 'Thinking' : type.charAt(0).toUpperCase() + type.slice(1)
  if (type === 'thinking') {
    return (
      <div className="feed-log-segment feed-log-thinking">
        <span className="feed-log-segment-label">{label}</span>
        <div className="feed-log-segment-body">
          <ReactMarkdown>{text.trim() || '\u00a0'}</ReactMarkdown>
        </div>
      </div>
    )
  }
  if (type === 'tool_call') {
    return (
      <div className="feed-log-segment feed-log-tool-call">
        <span className="feed-log-segment-label">{label}</span>
        <pre className="feed-log-segment-body feed-log-terminal">{text}</pre>
      </div>
    )
  }
  return (
    <div className="feed-log-segment feed-log-default">
      <span className="feed-log-segment-label">{label}</span>
      <div className="feed-log-segment-body">
        <ReactMarkdown>{text.trim() || '\u00a0'}</ReactMarkdown>
      </div>
    </div>
  )
}

function TaskCommsPage() {
  const { taskName } = useParams<{ taskName: string }>()
  const navigate = useNavigate()
  if (!taskName) {
    navigate('/')
    return null
  }
  return <TaskCommsPageContent taskName={taskName} navigate={navigate} />
}

export function TaskCommsPageContent({
  taskName,
  navigate,
}: {
  taskName: string
  navigate: (to: string) => void
}) {
  const [feedEntries, setFeedEntries] = useState<Array<{ type: string; id: string; created_at: number }>>([])
  const [contents, setContents] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [commentText, setCommentText] = useState('')
  const [posting, setPosting] = useState(false)
  const [postError, setPostError] = useState<string | null>(null)
  const [activeCommand, setActiveCommand] = useState<string | null>(null)
  const [activeLogFilename, setActiveLogFilename] = useState<string | null>(null)
  const [commandError, setCommandError] = useState<string | null>(null)
  const [startingCommand, setStartingCommand] = useState<string | null>(null)
  const [creatingPr, setCreatingPr] = useState(false)
  const [prUrl, setPrUrl] = useState<string | null>(null)
  const [prError, setPrError] = useState<string | null>(null)
  const [scrollToBottomAfterLoad, setScrollToBottomAfterLoad] = useState(false)
  const lastCommsEntryRef = useRef<HTMLDivElement | null>(null)
  const hasScrolledInitialRef = useRef(false)
  const [archiving, setArchiving] = useState(false)
  const [archiveError, setArchiveError] = useState<string | null>(null)
  const [collapsedKeys, setCollapsedKeys] = useState<Set<string>>(new Set())

  const toggleCollapsed = useCallback((key: string) => {
    setCollapsedKeys((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const handleArchive = async () => {
    if (!confirm(`Archive task "${taskName}"?`)) return
    setArchiveError(null)
    setArchiving(true)
    try {
      const res = await api.archiveTask(taskName)
      const archivedName = res.archived_to.split('/').pop() ?? ''
      sessionStorage.setItem('dev_undo_archive', JSON.stringify({ archivedName, taskName }))
      navigate('/')
    } catch (e) {
      setArchiveError(e instanceof Error ? e.message : String(e))
    } finally {
      setArchiving(false)
    }
  }

  const loadCommandStatus = useCallback(async () => {
    try {
      const res = await api.getTaskCommandStatus(taskName)
      setActiveCommand(res.active && res.command ? res.command : null)
      setActiveLogFilename(res.active && res.active_log_filename ? res.active_log_filename : null)
    } catch {
      // ignore; task might not exist yet
    }
  }, [taskName])

  const loadFeed = useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const res = await api.getTaskFeed(taskName)
      setFeedEntries(res.entries)
      const map: Record<string, string> = {}
      await Promise.all(
        res.entries.map(async (entry) => {
          // Skip fetching the active log file; its content is streamed instead
          if (entry.type === 'log' && entry.id === activeLogFilename) {
            map[entry.id] = ''
            return
          }
          const text =
            entry.type === 'comms'
              ? await api.getTaskCommsFile(taskName, entry.id)
              : await api.getTaskLogFile(taskName, entry.id)
          map[entry.id] = text
        })
      )
      setContents((prev) => {
        const next = { ...map }
        // Preserve streamed content for the active log when reloading feed
        if (activeLogFilename && (prev[activeLogFilename] ?? '').length > 0) {
          next[activeLogFilename] = prev[activeLogFilename]
        }
        return next
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [taskName, activeLogFilename])

  useEffect(() => {
    loadCommandStatus()
  }, [loadCommandStatus])

  useEffect(() => {
    const interval = setInterval(loadCommandStatus, 3000)
    return () => clearInterval(interval)
  }, [loadCommandStatus])

  const prevActiveCommandRef = useRef<string | null>(null)
  useEffect(() => {
    if (prevActiveCommandRef.current !== null && activeCommand === null) {
      loadFeed()
    }
    prevActiveCommandRef.current = activeCommand
  }, [activeCommand, loadFeed])

  // When a command becomes active with an active log, reload feed so the new log entry appears
  useEffect(() => {
    if (activeCommand && activeLogFilename) {
      loadFeed()
    }
  }, [activeCommand, activeLogFilename, loadFeed])

  // Stream the active log via SSE while command is running
  useEffect(() => {
    if (!activeCommand || !activeLogFilename) return
    const es = api.openTaskLogStream(taskName)
    es.onmessage = (e: MessageEvent) => {
      const data = e.data != null ? String(e.data) : ''
      setContents((prev) => ({
        ...prev,
        [activeLogFilename]: (prev[activeLogFilename] ?? '') + data + (data && !data.endsWith('\n') ? '\n' : ''),
      }))
    }
    es.onerror = () => {
      es.close()
    }
    return () => {
      es.close()
    }
  }, [taskName, activeCommand, activeLogFilename])

  const handleStartCommand = async (command: string) => {
    setCommandError(null)
    setStartingCommand(command)
    try {
      await api.startTaskCommand(taskName, command)
      await loadCommandStatus()
    } catch (e) {
      setCommandError(e instanceof Error ? e.message : String(e))
    } finally {
      setStartingCommand(null)
    }
  }

  const handleCreatePr = async () => {
    setPrError(null)
    setPrUrl(null)
    setCreatingPr(true)
    try {
      const res = await api.createTaskPr(taskName)
      setPrUrl(res.pr_url)
    } catch (e) {
      setPrError(e instanceof Error ? e.message : String(e))
    } finally {
      setCreatingPr(false)
    }
  }

  useEffect(() => {
    loadFeed()
  }, [loadFeed])

  useEffect(() => {
    document.title = `Dev – ${taskName}`
    return () => { document.title = DEFAULT_TAB_TITLE }
  }, [taskName])

  const handlePostComment = async (e: React.FormEvent) => {
    e.preventDefault()
    const content = commentText.trim()
    if (!content) return
    setPostError(null)
    setPosting(true)
    try {
      await api.postTaskComms(taskName, content)
      setCommentText('')
      setScrollToBottomAfterLoad(true)
      await loadFeed()
    } catch (e) {
      setPostError(e instanceof Error ? e.message : String(e))
    } finally {
      setPosting(false)
    }
  }

  useEffect(() => {
    if (!loading && feedEntries.length > 0) {
      if (scrollToBottomAfterLoad) {
        lastCommsEntryRef.current?.scrollIntoView({ behavior: 'instant' })
        setScrollToBottomAfterLoad(false)
      } else if (!hasScrolledInitialRef.current) {
        lastCommsEntryRef.current?.scrollIntoView({ behavior: 'smooth' })
        hasScrolledInitialRef.current = true
      }
    }
  }, [loading, scrollToBottomAfterLoad, feedEntries.length])

  // Keep scrolled to bottom of page when active log content is streaming
  useEffect(() => {
    if (activeLogFilename && contents[activeLogFilename]) {
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' })
    }
  }, [activeLogFilename, contents[activeLogFilename]])

  if (loading) return <p className="status">Loading feed…</p>
  if (error) {
    return (
      <section className="task-comms">
        <p className="inline-error">{error}</p>
        <p><Link to="/">← Back to tasks</Link></p>
      </section>
    )
  }

  return (
    <section className="task-comms">
      <div className="task-comms-header">
        <h2>{taskName}</h2>
        <button
          type="button"
          className="archive-btn archive-btn-task-view"
          onClick={handleArchive}
          disabled={archiving}
        >
          {archiving ? 'Archiving…' : 'Archive'}
        </button>
      </div>
      {archiveError && <p className="inline-error">{archiveError}</p>}
      <p><Link to="/">← Back to tasks</Link></p>
      {feedEntries.length === 0 ? (
        <p className="empty">No comms or agent logs yet for this task.</p>
      ) : (
        <div className="comms-history">
          {feedEntries.map((entry, i) => {
            const entryKey = `${entry.type}:${entry.id}`
            const isCollapsed = collapsedKeys.has(entryKey)
            return (
              <div
                key={entryKey}
                className={entry.type === 'log' ? 'feed-entry feed-log-entry' : 'comms-entry'}
                ref={i === feedEntries.length - 1 ? lastCommsEntryRef : undefined}
              >
                <button
                  type="button"
                  className="feed-entry-header"
                  onClick={() => toggleCollapsed(entryKey)}
                  aria-expanded={!isCollapsed}
                >
                  <span className="feed-entry-chevron" aria-hidden>
                    {isCollapsed ? '▶' : '▼'}
                  </span>
                  <span className="feed-entry-title">
                    {entry.type === 'log'
                      ? `Agent log: ${entry.id}${entry.id === activeLogFilename ? ' (live)' : ''}`
                      : entry.id}
                  </span>
                </button>
                {!isCollapsed && (
                  <div className="comms-content">
                    {entry.type === 'log' ? (
                      <ParsedLogView raw={contents[entry.id] ?? ''} />
                    ) : (
                      <ReactMarkdown>{contents[entry.id] ?? '(loading…)'}</ReactMarkdown>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
      <div className="task-commands">
        {activeCommand ? (
          <p className="command-status">
            <span className="command-spinner" aria-hidden /> Running: {COMMAND_LABEL[activeCommand] ?? activeCommand}
          </p>
        ) : (
          <div className="command-buttons">
            <button
              type="button"
              className="command-btn"
              disabled={!!startingCommand}
              onClick={() => handleStartCommand('plan-implement')}
            >
              {startingCommand === 'plan-implement' ? 'Starting…' : 'Plan'}
            </button>
            <button
              type="button"
              className="command-btn"
              disabled={!!startingCommand}
              onClick={() => handleStartCommand('implement')}
            >
              {startingCommand === 'implement' ? 'Starting…' : 'Implement'}
            </button>
            <button
              type="button"
              className="command-btn"
              disabled={!!startingCommand || creatingPr}
              onClick={handleCreatePr}
              aria-busy={creatingPr}
            >
              {creatingPr ? 'Creating PR…' : 'Create PR'}
            </button>
          </div>
        )}
        {commandError && <p className="inline-error">{commandError}</p>}
        {prError && <p className="inline-error">{prError}</p>}
        {prUrl && (
          <p className="pr-result">
            <a href={prUrl} target="_blank" rel="noopener noreferrer">Open PR</a>
          </p>
        )}
      </div>
      <form className="comms-post-form" onSubmit={handlePostComment}>
        <label className="comms-post-form-label">Add comment</label>
        <textarea
          className="comms-post-form-textarea"
          value={commentText}
          onChange={(e) => setCommentText(e.target.value)}
          placeholder="Write a comment…"
          rows={3}
          disabled={posting}
        />
        {postError && <p className="inline-error">{postError}</p>}
        <div className="form-actions">
          <button type="submit" disabled={posting || !commentText.trim()}>
            {posting ? 'Posting…' : 'Post comment'}
          </button>
        </div>
      </form>
    </section>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout />
    </BrowserRouter>
  )
}
