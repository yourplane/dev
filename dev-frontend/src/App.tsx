import { useState, useEffect, useCallback, useRef, memo } from 'react'
import { BrowserRouter, Link, Routes, Route, useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { api, apiBaseUrl } from './api'
import { parseLogToSegments, type LogSegment, type ToolCallInfo } from './logParser'
import './App.css'

const FEED_POLL_INTERVAL_MS = 15000

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
  const [copyFromArchiveLoading, setCopyFromArchiveLoading] = useState<string | null>(null)
  const [copyFromArchiveError, setCopyFromArchiveError] = useState<string | null>(null)
  const [copiedTask, setCopiedTask] = useState<string | null>(null)

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

  const handleCopyFromArchive = async (archivedName: string) => {
    if (!confirm('Create a new task from this archive? Same name and comms, new agent chat and no old logs.')) return
    setCopyFromArchiveError(null)
    setCopyFromArchiveLoading(archivedName)
    setCopiedTask(null)
    try {
      const res = await api.copyFromArchive(archivedName)
      setCopiedTask(res.task_name)
    } catch (e) {
      setCopyFromArchiveError(e instanceof Error ? e.message : String(e))
    } finally {
      setCopyFromArchiveLoading(null)
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
      {(unarchiveError || copyFromArchiveError) && (
        <p className="inline-error">{unarchiveError ?? copyFromArchiveError}</p>
      )}
      {restoredTask && (
        <p className="archive-restored">
          Restored. <Link to={`/task/${encodeURIComponent(restoredTask)}`}>Open {restoredTask}</Link>
        </p>
      )}
      {copiedTask && (
        <p className="archive-restored">
          Task created. <Link to={`/task/${encodeURIComponent(copiedTask)}`}>Open {copiedTask}</Link>
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
                      className="copy-from-archive-btn"
                      onClick={() => handleCopyFromArchive(e.archived_name)}
                      disabled={copyFromArchiveLoading === e.archived_name}
                      title="Create a new task with the same name and comms, new agent chat and no old logs"
                    >
                      {copyFromArchiveLoading === e.archived_name ? 'Copying…' : 'Copy from archive'}
                    </button>
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

const DRAFT_DEBOUNCE_MS = 400

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
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [createStatusMessage, setCreateStatusMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [addName, setAddName] = useState('')
  const [addUrl, setAddUrl] = useState('')
  const [addError, setAddError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState<string | null>(null)
  const [draftStatus, setDraftStatus] = useState<'saved' | 'unsaved' | 'saving'>('saved')
  const draftLoadedRef = useRef(false)
  const lastSavedSnapshotRef = useRef<{ title: string; repo: string; comment: string } | null>(null)

  const loadRepos = useCallback(() => {
    return api.getRepos().then(setRepos)
  }, [])

  useEffect(() => {
    let cancelled = false
    api.getRepos().then((r) => {
      if (!cancelled) setRepos(r)
    }).finally(() => {
      if (!cancelled) setReposLoading(false)
    })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (reposLoading) return
    let cancelled = false
    api.getNewTaskDraft().then((d) => {
      if (cancelled) return
      const loadedTitle = d.title ?? ''
      const loadedRepo = d.repo ?? ''
      const loadedComment = d.comment ?? ''
      setTitle(loadedTitle)
      setRepo(loadedRepo)
      setComment(loadedComment)
      lastSavedSnapshotRef.current = { title: loadedTitle, repo: loadedRepo, comment: loadedComment }
      draftLoadedRef.current = true
      setDraftStatus('saved')
    }).catch(() => { /* ignore */ })
    return () => { cancelled = true }
  }, [reposLoading])

  useEffect(() => {
    if (!draftLoadedRef.current) return
    const snapshot = lastSavedSnapshotRef.current
    if (snapshot && title === snapshot.title && repo === snapshot.repo && comment === snapshot.comment) {
      setDraftStatus('saved')
      return
    }
    setDraftStatus('unsaved')
    const t = setTimeout(() => {
      const payload = { title, repo, comment }
      const empty = !title.trim() && !repo.trim() && !comment.trim()
      setDraftStatus('saving')
      api.setNewTaskDraft(empty ? {} : payload).then(() => {
        lastSavedSnapshotRef.current = { title, repo, comment }
        setDraftStatus('saved')
      }).catch(() => {
        setDraftStatus('unsaved')
      })
    }, DRAFT_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [title, repo, comment])

  const handleRemoveRepo = async (name: string) => {
    if (!confirm(`Remove "${name}" from your repo list?`)) return
    setAddError(null)
    setRemoving(name)
    try {
      await api.removeRepo(name)
      await loadRepos()
      if (repo === name) setRepo('')
    } catch (e) {
      setAddError(e instanceof Error ? e.message : String(e))
    } finally {
      setRemoving(null)
    }
  }

  const openAddModal = () => {
    setAddName('')
    setAddUrl('')
    setAddError(null)
    setAddModalOpen(true)
  }

  const handleAddRepo = async (e: React.FormEvent) => {
    e.preventDefault()
    setAddError(null)
    const n = addName.trim()
    const u = addUrl.trim()
    if (!n) { setAddError('Name is required'); return }
    if (!u) { setAddError('URL is required'); return }
    setAdding(true)
    try {
      await api.addRepo(n, u)
      await loadRepos()
      setAddName('')
      setAddUrl('')
      setAddModalOpen(false)
    } catch (e) {
      setAddError(e instanceof Error ? e.message : String(e))
    } finally {
      setAdding(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!title.trim()) { setError('Title is required'); return }
    if (!repo.trim()) { setError('Select a repo'); return }
    setCreateStatusMessage(null)
    setSubmitting(true)
    try {
      const res = await api.createTask(
        {
          title: title.trim(),
          repo: repo.trim(),
          comment: comment.trim() || undefined,
        },
        (msg) => setCreateStatusMessage(msg),
      )
      onCreated(res.task_name)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
      setCreateStatusMessage(null)
    }
  }

  return (
    <section className="create-form">
      <h2>New task</h2>
      <div className={`draft-status draft-status-${draftStatus}`} role="status" aria-live="polite">
        {draftStatus === 'saved' && 'All changes saved to draft'}
        {draftStatus === 'unsaved' && 'Unsaved changes'}
        {draftStatus === 'saving' && 'Saving draft…'}
      </div>
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
          ) : Object.keys(repos).length === 0 ? (
            <div className="repo-empty">
              <p className="hint">No repos yet. Click Add to add one.</p>
              <button type="button" className="repo-add-open-btn" onClick={openAddModal}>
                Add repo
              </button>
            </div>
          ) : (
            <>
            <div className="repo-radio-group" role="radiogroup" aria-label="Repo">
              {Object.entries(repos).map(([name, url]) => (
                <div key={name} className="repo-radio-option repo-radio-row">
                  <label className="repo-radio-label">
                    <input
                      type="radio"
                      name="repo"
                      value={name}
                      checked={repo === name}
                      onChange={() => setRepo(name)}
                    />
                    <span>{name} — {url}</span>
                  </label>
                  <button
                    type="button"
                    className="repo-remove-btn"
                    onClick={() => handleRemoveRepo(name)}
                    disabled={removing !== null}
                    title={`Remove ${name}`}
                    aria-label={`Remove ${name}`}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
            <button type="button" className="repo-add-open-btn" onClick={openAddModal}>
              Add repo
            </button>
            </>
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
        <div className="form-actions create-form-submit-row">
          {submitting && (
            <p className="command-status create-task-status" role="status" aria-live="polite">
              <span className="command-spinner" aria-hidden />
              {createStatusMessage ?? 'Starting…'}
            </p>
          )}
          <button type="submit" disabled={submitting}>
            {submitting ? 'Creating…' : 'Create task'}
          </button>
          <button type="button" onClick={onCancel}>Cancel</button>
        </div>
      </form>
      {addModalOpen && (
        <div className="modal-backdrop" onClick={() => setAddModalOpen(false)}>
          <div className="modal-content repo-add-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="repo-add-modal-title">
            <h3 id="repo-add-modal-title" className="modal-title">Add repo</h3>
            {addError && <p className="inline-error">{addError}</p>}
            <form onSubmit={handleAddRepo}>
              <label>
                <span>Name</span>
                <input
                  type="text"
                  value={addName}
                  onChange={(e) => setAddName(e.target.value)}
                  placeholder="Shorthand name"
                  autoFocus
                />
              </label>
              <label>
                <span>URL</span>
                <input
                  type="text"
                  value={addUrl}
                  onChange={(e) => setAddUrl(e.target.value)}
                  placeholder="https://github.com/user/repo.git"
                />
              </label>
              <div className="form-actions">
                <button type="submit" disabled={adding}>
                  {adding ? 'Adding…' : 'Add'}
                </button>
                <button type="button" onClick={() => setAddModalOpen(false)}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  )
}

const COMMAND_LABEL: Record<string, string> = {
  'plan-implement': 'Plan',
  implement: 'Implement',
  do: 'Do',
}

const FeedEntryRow = memo(function FeedEntryRow({
  entry,
  contents,
  loadingContentKeys,
  isCollapsed,
  entryKey,
  toggleCollapsed,
  loadEntryContent,
  activeLogFilename,
  isLast,
  lastEntryRef,
  onDeleteComms,
}: {
  entry: { type: string; id: string; created_at: number; deletable?: boolean | null }
  contents: Record<string, string>
  loadingContentKeys: Set<string>
  isCollapsed: boolean
  entryKey: string
  toggleCollapsed: (key: string) => void
  loadEntryContent: (entryId: string, type: string) => void
  activeLogFilename: string | null
  isLast: boolean
  lastEntryRef: React.RefObject<HTMLDivElement>
  onDeleteComms?: (filename: string) => void
}) {
  useEffect(() => {
    if (!isCollapsed && contents[entry.id] === undefined && !loadingContentKeys.has(entryKey)) {
      loadEntryContent(entry.id, entry.type)
    }
  }, [isCollapsed, entry.id, entry.type, entryKey, contents[entry.id], loadEntryContent, loadingContentKeys])

  const title =
    entry.type === 'log'
      ? `Agent log: ${entry.id}${entry.id === activeLogFilename ? ' (live)' : ''}`
      : entry.id

  return (
    <div
      ref={isLast ? lastEntryRef : undefined}
      className={entry.type === 'log' ? 'feed-entry feed-log-entry' : 'comms-entry'}
    >
      <div className="feed-entry-header-row">
        <button
          type="button"
          className="feed-entry-header"
          onClick={() => toggleCollapsed(entryKey)}
          aria-expanded={!isCollapsed}
        >
          <span className="feed-entry-chevron" aria-hidden>
            {isCollapsed ? '▶' : '▼'}
          </span>
          <span className="feed-entry-title">{title}</span>
        </button>
        {entry.type === 'comms' && entry.deletable === true && onDeleteComms && (
          <button
            type="button"
            className="comms-entry-delete-btn"
            onClick={() => onDeleteComms(entry.id)}
            aria-label="Remove comms entry"
            title="Remove this comms entry (only entries after the last agent log can be removed)"
          >
            Remove
          </button>
        )}
      </div>
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
})

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

function getShellOutput(result: unknown): string {
  if (result == null) return ''
  const r = result as Record<string, unknown>
  const inner = (r.success != null && r.success !== false ? (r.success as Record<string, unknown>) : r) as Record<string, unknown>
  function fromObj(obj: Record<string, unknown>): string {
    if (typeof obj.output === 'string') return obj.output
    if (typeof obj.combinedOutput === 'string') return obj.combinedOutput
    if (typeof obj.interleavedOutput === 'string') return obj.interleavedOutput
    const stdout = typeof obj.stdout === 'string' ? obj.stdout : ''
    const stderr = typeof obj.stderr === 'string' ? obj.stderr : ''
    return stderr ? stdout + (stdout ? '\n' : '') + stderr : stdout
  }
  const fromInner = fromObj(inner)
  if (fromInner) return fromInner
  return fromObj(r)
}

function getReadSuccess(result: unknown): boolean {
  if (result == null) return false
  const r = result as Record<string, unknown>
  return r.success !== undefined && r.success !== null
}

function getReadPath(args: Record<string, unknown>, result: unknown): string {
  if (result != null) {
    const r = result as Record<string, unknown>
    const success = r.success as Record<string, unknown> | undefined
    if (success && typeof success.path === 'string') return success.path
  }
  return typeof args.path === 'string' ? args.path : ''
}

type TodoWriteItem = { id?: string; content?: string; status?: string }

function normalizeTodoItems(raw: unknown): TodoWriteItem[] {
  if (!Array.isArray(raw)) return []
  return raw.map((item) => {
    if (item && typeof item === 'object' && !Array.isArray(item)) {
      const o = item as Record<string, unknown>
      return {
        id: typeof o.id === 'string' ? o.id : undefined,
        content: typeof o.content === 'string' ? o.content : undefined,
        status: typeof o.status === 'string' ? o.status : undefined,
      }
    }
    return {}
  })
}

function getTodoListFromResult(result: unknown): TodoWriteItem[] {
  if (result == null) return []
  const r = result as Record<string, unknown>
  const success = r.success as Record<string, unknown> | undefined
  const todos = success?.todos ?? success?.todo ?? r.todos ?? r.todo
  return normalizeTodoItems(todos)
}

/** Todos live in args while streaming; result may mirror them when completed. */
function getTodoListFromToolCall(args: Record<string, unknown>, result: unknown): TodoWriteItem[] {
  const fromArgs = args.todos ?? args.todo
  if (Array.isArray(fromArgs) && fromArgs.length > 0) {
    return normalizeTodoItems(fromArgs)
  }
  return getTodoListFromResult(result)
}

function isTodoWriteTool(toolKey: string): boolean {
  if (
    toolKey === 'todo_writeToolCall' ||
    toolKey === 'todoWriteToolCall' ||
    toolKey === 'updateTodosToolCall' ||
    toolKey === 'update_todosToolCall'
  ) {
    return true
  }
  const lower = toolKey.toLowerCase()
  if (!lower.endsWith('toolcall')) return false
  if (!lower.includes('todo')) return false
  // e.g. todo_write*, *Todos* (update todos), todo merge tools
  return (
    lower.includes('write') ||
    lower.includes('todos') ||
    (lower.includes('update') && lower.includes('todo'))
  )
}

/** Maps Cursor / proto enums (TODO_STATUS_COMPLETED) and plain names to UI buckets. */
function classifyTodoStatus(statusRaw: string | undefined): 'done' | 'active' | 'cancelled' | 'pending' {
  const s = (statusRaw ?? '').toLowerCase()
  if (s.includes('completed') || s === 'done') return 'done'
  if (s.includes('cancelled') || s === 'canceled') return 'cancelled'
  if (s.includes('in_progress') || s.includes('inprogress')) return 'active'
  return 'pending'
}

function TodoWriteCheckboxList({ items }: { items: TodoWriteItem[] }) {
  if (items.length === 0) {
    return <p className="feed-log-todo-empty">(no items)</p>
  }
  return (
    <ul className="feed-log-tool-call-todos feed-log-todo-checkbox-list" role="list" aria-label="Todo list">
      {items.map((t, i) => {
        const bucket = classifyTodoStatus(t.status)
        const isDone = bucket === 'done'
        const isCancelled = bucket === 'cancelled'
        const isInProgress = bucket === 'active'
        const rowClass = [
          'feed-log-todo-row',
          isDone && 'feed-log-todo-row--done',
          isCancelled && 'feed-log-todo-row--cancelled',
          isInProgress && 'feed-log-todo-row--active',
        ]
          .filter(Boolean)
          .join(' ')
        return (
          <li key={t.id ?? `todo-${i}`} className={rowClass}>
            <span
              className={[
                'feed-log-todo-box',
                isDone && 'feed-log-todo-box--done',
                isCancelled && 'feed-log-todo-box--cancelled',
                isInProgress && 'feed-log-todo-box--active',
              ]
                .filter(Boolean)
                .join(' ')}
              aria-hidden
            />
            <span className="feed-log-todo-label">{t.content ?? ''}</span>
          </li>
        )
      })}
    </ul>
  )
}

function getEditDiff(result: unknown, args: Record<string, unknown>): string {
  if (result != null) {
    const r = result as Record<string, unknown>
    if (typeof r.diff === 'string') return r.diff
    const success = r.success as Record<string, unknown> | undefined
    if (success && typeof success.diffString === 'string') return success.diffString
  }
  const oldStr = args.old_string ?? args.oldString
  const newStr = args.new_string ?? args.newString
  if (oldStr != null && newStr != null) {
    return `- ${typeof oldStr === 'string' ? oldStr : JSON.stringify(oldStr)}\n+ ${typeof newStr === 'string' ? newStr : JSON.stringify(newStr)}`
  }
  return ''
}

function getEditFilePath(args: Record<string, unknown>, result: unknown): string {
  if (result != null) {
    const r = result as Record<string, unknown>
    const success = r.success as Record<string, unknown> | undefined
    if (success && typeof success.path === 'string') return success.path
  }
  return typeof args.path === 'string' ? args.path : ''
}

function getWebSearchSuccess(result: unknown): boolean {
  if (result == null) return false
  const r = result as Record<string, unknown>
  return r.success === true || (r.error === undefined && r.success !== false)
}

function getGrepSummary(result: unknown): { totalMatchedLines?: number; totalLines?: number; text?: string } {
  if (result == null) return {}
  const r = result as Record<string, unknown>
  const success = r.success as Record<string, unknown> | undefined
  const workspaceResults = success?.workspaceResults as Record<string, { content?: Record<string, unknown> }> | undefined
  if (!workspaceResults) return {}
  const firstWs = Object.values(workspaceResults)[0]
  const first = firstWs?.content
  if (!first || typeof first !== 'object') return {}
  const data = first as Record<string, unknown>
  const totalMatchedLines = data.totalMatchedLines as number | undefined
  const totalLines = data.totalLines as number | undefined
  const matches = data.matches as Array<{ file?: string; matches?: Array<{ lineNumber?: number; content?: string }> }> | undefined
  if (!Array.isArray(matches)) return { totalMatchedLines, totalLines }
  const lines: string[] = []
  for (const m of matches.slice(0, 30)) {
    const file = m.file ?? ''
    for (const hit of (m.matches ?? []).slice(0, 5)) {
      lines.push(`${file}:${hit.lineNumber ?? ''} ${(hit.content ?? '').slice(0, 80)}`)
    }
  }
  return { totalMatchedLines, totalLines, text: lines.join('\n') }
}

function getGlobFiles(result: unknown): string[] {
  if (result == null) return []
  const r = result as Record<string, unknown>
  const success = r.success as Record<string, unknown> | undefined
  const files = success?.files ?? r.files
  return Array.isArray(files) ? files.filter((f): f is string => typeof f === 'string') : []
}

function ToolCallBlock({ toolCall }: { toolCall: ToolCallInfo }) {
  const { toolKey, humanLabel, args, result, status } = toolCall
  const isStarted = status === 'started'

  if (isStarted) {
    if (toolKey === 'shellToolCall') {
      const command = typeof args.command === 'string' ? args.command : ''
      const partialOutput = toolCall.partialOutput ?? ''
      const block = [command ? `$ ${command}` : '(running…)', partialOutput].filter(Boolean).join(partialOutput ? '\n\n' : '')
      return (
        <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-shell">
          <pre className="feed-log-shell-block">
            <span className="feed-log-tool-call-spinner" aria-hidden />
            {block || ' '}
          </pre>
        </div>
      )
    }
    if (isTodoWriteTool(toolKey)) {
      const todos = getTodoListFromToolCall(args, result)
      return (
        <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-todo-write">
          <div className="feed-log-tool-call-header">
            <span className="feed-log-tool-call-spinner" aria-hidden />
            <span className="feed-log-segment-label">{humanLabel}</span>
          </div>
          <div className="feed-log-segment-body">
            <TodoWriteCheckboxList items={todos} />
          </div>
        </div>
      )
    }
    return (
      <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-in-progress">
        <div className="feed-log-tool-call-header">
          <span className="feed-log-tool-call-spinner" aria-hidden />
          <span className="feed-log-segment-label">{humanLabel}</span>
        </div>
      </div>
    )
  }

  if (toolKey === 'readToolCall') {
    const path = getReadPath(args, result)
    const success = getReadSuccess(result)
    return (
      <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-read">
        <div className="feed-log-tool-call-header feed-log-tool-call-read-line">
          <span className="feed-log-segment-label">{humanLabel}</span>
          <span className="feed-log-tool-call-read-path feed-log-file-path">{path || '—'}</span>
          {!success && <span className="feed-log-tool-call-status feed-log-tool-call-error">Error</span>}
        </div>
      </div>
    )
  }

  if (toolKey === 'shellToolCall') {
    const command = typeof args.command === 'string' ? args.command : ''
    const output = getShellOutput(result)
    const block = [command ? `$ ${command}` : '', output].filter(Boolean).join('\n\n')
    const failed =
      result != null &&
      typeof result === 'object' &&
      ((result as Record<string, unknown>).success === false ||
        (typeof (result as Record<string, unknown>).exitCode === 'number' &&
          (result as Record<string, unknown>).exitCode !== 0))
    return (
      <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-shell">
        {failed && (
          <div className="feed-log-tool-call-header feed-log-tool-call-shell-failed">
            <span className="feed-log-tool-call-status feed-log-tool-call-error">Command failed</span>
          </div>
        )}
        <pre className="feed-log-shell-block">{block || ' '}</pre>
      </div>
    )
  }

  if (isTodoWriteTool(toolKey)) {
    const todos = getTodoListFromToolCall(args, result)
    return (
      <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-todo-write">
        <div className="feed-log-tool-call-header">
          <span className="feed-log-segment-label">{humanLabel}</span>
        </div>
        <div className="feed-log-segment-body">
          <TodoWriteCheckboxList items={todos} />
        </div>
      </div>
    )
  }

  if (toolKey === 'search_replaceToolCall' || toolKey === 'editToolCall') {
    const diff = getEditDiff(result, args)
    const filePath = getEditFilePath(args, result)
    return (
      <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-diff">
        <div className="feed-log-tool-call-header">
          <span className="feed-log-segment-label">{humanLabel}</span>
          {filePath ? <span className="feed-log-tool-call-edit-path feed-log-file-path">{filePath}</span> : null}
        </div>
        <div className="feed-log-diff-body">
          {diff ? (
            diff.split('\n').map((line, i) => {
              if (line.startsWith('-')) {
                return <div key={i} className="feed-log-diff-line feed-log-diff-removed">{line}</div>
              }
              if (line.startsWith('+')) {
                return <div key={i} className="feed-log-diff-line feed-log-diff-added">{line}</div>
              }
              return <div key={i} className="feed-log-diff-line">{line || '\u00a0'}</div>
            })
          ) : (
            <div className="feed-log-diff-line">(no diff)</div>
          )}
        </div>
      </div>
    )
  }

  if (toolKey === 'writeToolCall') {
    const diff = getEditDiff(result, args)
    const content = diff || (args.contents != null ? String(args.contents) : '')
    const filePath = getEditFilePath(args, result)
    const displayContent = content || (typeof args.path === 'string' ? args.path : '')
    return (
      <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-diff">
        <div className="feed-log-tool-call-header">
          <span className="feed-log-segment-label">{humanLabel}</span>
          {filePath ? <span className="feed-log-tool-call-edit-path feed-log-file-path">{filePath}</span> : null}
        </div>
        <div className="feed-log-diff-body">
          {displayContent ? (
            displayContent.split('\n').map((line, i) => {
              if (line.startsWith('-')) {
                return <div key={i} className="feed-log-diff-line feed-log-diff-removed">{line}</div>
              }
              if (line.startsWith('+')) {
                return <div key={i} className="feed-log-diff-line feed-log-diff-added">{line}</div>
              }
              return <div key={i} className="feed-log-diff-line">{line || '\u00a0'}</div>
            })
          ) : (
            <div className="feed-log-diff-line">(no content)</div>
          )}
        </div>
      </div>
    )
  }

  if (toolKey === 'web_searchToolCall' || toolKey === 'webSearchToolCall') {
    const query =
      (typeof args.searchTerm === 'string' ? args.searchTerm : null) ??
      (typeof args.query === 'string' ? args.query : '')
    const success = getWebSearchSuccess(result)
    return (
      <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-web-search">
        <div className="feed-log-tool-call-header">
          <span className="feed-log-tool-call-search-icon" aria-hidden />
          <span className="feed-log-segment-label">{humanLabel}</span>
          {query ? <span className="feed-log-tool-call-search-query">{query}</span> : null}
          <span className="feed-log-tool-call-status">{success ? 'Success' : 'Error'}</span>
        </div>
      </div>
    )
  }

  if (toolKey === 'mcp_web_fetchToolCall' || toolKey === 'mcpWebFetchToolCall' || toolKey === 'webFetchToolCall') {
    const url = typeof args.url === 'string' ? args.url : ''
    if (!url) {
      return (
        <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-web-fetch">
          <div className="feed-log-tool-call-header">
            <span className="feed-log-segment-label">{humanLabel}</span>
          </div>
        </div>
      )
    }
    const href = url.startsWith('http') ? url : `https://${url}`
    let domain = ''
    try {
      domain = new URL(href).hostname
    } catch {
      domain = url
    }
    const faviconUrl = `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=32`
    return (
      <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-web-fetch">
        <div className="feed-log-tool-call-header">
          <span className="feed-log-segment-label">{humanLabel}</span>
          <a href={href} target="_blank" rel="noopener noreferrer" className="feed-log-tool-call-web-fetch-link">
            <img src={faviconUrl} alt="" className="feed-log-tool-call-favicon" width={16} height={16} />
            <span className="feed-log-tool-call-link">{url}</span>
          </a>
        </div>
      </div>
    )
  }

  if (toolKey === 'grepToolCall') {
    const summary = getGrepSummary(result)
    const pattern = typeof args.pattern === 'string' ? args.pattern : ''
    const path = typeof args.path === 'string' ? args.path : ''
    const scope = [path, typeof args.glob === 'string' ? args.glob : ''].filter(Boolean).join(' ')
    return (
      <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-search">
        <div className="feed-log-tool-call-header">
          <span className="feed-log-segment-label">{humanLabel}</span>
          {summary.totalMatchedLines != null && (
            <span className="feed-log-tool-call-search-count">{summary.totalMatchedLines} matches</span>
          )}
        </div>
        <div className="feed-log-segment-body feed-log-search-body">
          <p className="feed-log-tool-call-read-path feed-log-search-pattern">{pattern}{scope ? ` in ${scope}` : ''}</p>
          {summary.text ? <pre className="feed-log-search-results">{summary.text}</pre> : null}
        </div>
      </div>
    )
  }

  if (toolKey === 'globToolCall') {
    const files = getGlobFiles(result)
    const pattern = typeof args.globPattern === 'string' ? args.globPattern : (typeof args.pattern === 'string' ? args.pattern : '')
    return (
      <div className="feed-log-segment feed-log-tool-call">
        <div className="feed-log-tool-call-header">
          <span className="feed-log-segment-label">{humanLabel}</span>
          {files.length > 0 && <span className="feed-log-tool-call-status">{files.length} files</span>}
        </div>
        <div className="feed-log-segment-body">
          {pattern ? <p className="feed-log-tool-call-read-path feed-log-file-path">{pattern}</p> : null}
          {files.length > 0 ? <pre className="feed-log-terminal">{files.slice(0, 50).join('\n')}{files.length > 50 ? `\n... and ${files.length - 50} more` : ''}</pre> : null}
        </div>
      </div>
    )
  }

  const hasResult = result !== undefined && result !== null
  const resultStr = hasResult ? (typeof result === 'string' ? result : JSON.stringify(result, null, 2)) : ''
  return (
    <div className="feed-log-segment feed-log-tool-call">
      <div className="feed-log-tool-call-header">
        <span className="feed-log-segment-label">{humanLabel}</span>
        <span className="feed-log-tool-call-status">{status}</span>
      </div>
      <div className="feed-log-segment-body">
        {Object.keys(args).length > 0 && (
          <dl className="feed-log-tool-call-args">
            {Object.entries(args).map(([k, v]) => (
              <div key={k} className="feed-log-tool-call-arg">
                <dt>{k}</dt>
                <dd>{typeof v === 'string' ? v : JSON.stringify(v)}</dd>
              </div>
            ))}
          </dl>
        )}
        {hasResult && (
          <details className="feed-log-tool-call-result">
            <summary>Result</summary>
            <pre className="feed-log-terminal">{resultStr}</pre>
          </details>
        )}
      </div>
    </div>
  )
}

function LogSegmentBlock({ segment }: { segment: LogSegment }) {
  const { type, text, toolCall } = segment
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
  if (type === 'tool_call' && toolCall) {
    return <ToolCallBlock toolCall={toolCall} />
  }
  if (type === 'tool_call') {
    return (
      <div className="feed-log-segment feed-log-tool-call">
        <span className="feed-log-segment-label">{label}</span>
        <pre className="feed-log-segment-body feed-log-terminal">{text || '(no details)'}</pre>
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
  const [feedEntries, setFeedEntries] = useState<
    Array<{ type: string; id: string; created_at: number; deletable?: boolean | null }>
  >([])
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
  const [cancelling, setCancelling] = useState(false)
  const [creatingPr, setCreatingPr] = useState(false)
  const [pullingPrComments, setPullingPrComments] = useState(false)
  const [prUrl, setPrUrl] = useState<string | null>(null)
  const [prError, setPrError] = useState<string | null>(null)
  const [prCommentsStatus, setPrCommentsStatus] = useState<string | null>(null)
  const prRehydrateRunIdRef = useRef(0)
  const [scrollToBottomAfterLoad, setScrollToBottomAfterLoad] = useState(false)
  const [lockedToBottom, setLockedToBottom] = useState(false)
  const programmaticScrollRef = useRef(false)
  const feedLengthRef = useRef(0)
  const lastLockedScrollTimeRef = useRef(0)
  const lastCommsEntryRef = useRef<HTMLDivElement>(null)
  const feedEntriesRef = useRef(feedEntries)
  feedEntriesRef.current = feedEntries
  const activeLogFilenameRef = useRef(activeLogFilename)
  activeLogFilenameRef.current = activeLogFilename
  const hasScrolledInitialRef = useRef(false)
  const [archiving, setArchiving] = useState(false)
  const [archiveError, setArchiveError] = useState<string | null>(null)
  const [downloadingCommsZip, setDownloadingCommsZip] = useState(false)
  const [downloadCommsZipError, setDownloadCommsZipError] = useState<string | null>(null)
  const [deleteCommsError, setDeleteCommsError] = useState<string | null>(null)
  const [collapsedKeys, setCollapsedKeys] = useState<Set<string>>(new Set())
  const [loadingContentKeys, setLoadingContentKeys] = useState<Set<string>>(new Set())
  const [commentDraftStatus, setCommentDraftStatus] = useState<'saved' | 'unsaved' | 'saving'>('saved')
  const commentDraftLoadedRef = useRef(false)
  const lastSavedCommentRef = useRef<string | null>(null)

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

  const handleDownloadCommsZip = async () => {
    setDownloadCommsZipError(null)
    setDownloadingCommsZip(true)
    try {
      await api.downloadTaskCommsZip(taskName)
    } catch (e) {
      setDownloadCommsZipError(e instanceof Error ? e.message : String(e))
    } finally {
      setDownloadingCommsZip(false)
    }
  }

  const loadCommandStatus = useCallback(async () => {
    try {
      const res = await api.getTaskCommandStatus(taskName)
      const nextActive = res.active && res.command ? res.command : null
      setActiveCommand(nextActive)
      if (!nextActive) setCancelling(false)
      setActiveLogFilename(res.active && res.active_log_filename ? res.active_log_filename : null)
    } catch {
      // ignore; task might not exist yet
    }
  }, [taskName])

  const loadEntryContent = useCallback(
    async (entryId: string, type: string) => {
      if (type === 'log' && entryId === activeLogFilename) {
        setContents((prev) => ({ ...prev, [entryId]: prev[entryId] ?? '' }))
        return
      }
      const key = `${type}:${entryId}`
      setLoadingContentKeys((prev) => new Set(prev).add(key))
      try {
        const text =
          type === 'comms'
            ? await api.getTaskCommsFile(taskName, entryId)
            : await api.getTaskLogFile(taskName, entryId)
        setContents((prev) => ({ ...prev, [entryId]: text }))
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoadingContentKeys((prev) => {
          const next = new Set(prev)
          next.delete(key)
          return next
        })
      }
    },
    [taskName, activeLogFilename]
  )

  const loadFeed = useCallback(
    async (opts?: { incremental?: boolean; prefetchNew?: boolean }) => {
      const current = feedEntriesRef.current
      const isIncremental = opts?.incremental && current.length > 0
      if (!isIncremental) {
        setError(null)
        if (current.length === 0) setLoading(true)
      }
      try {
        if (isIncremental) {
          const after = Math.max(...current.map((e) => e.created_at))
          const res = await api.getTaskFeed(taskName, { after })
          const existingKeys = new Set(current.map((e) => `${e.type}:${e.id}`))
          const newEntries = res.entries.filter((e) => !existingKeys.has(`${e.type}:${e.id}`))
          if (newEntries.length === 0) return
          // New log files change the removal cutoff; refresh the full feed so comms `deletable` updates.
          if (newEntries.some((e) => e.type === 'log')) {
            const full = await api.getTaskFeed(taskName)
            setFeedEntries(full.entries)
            setContents((prev) => {
              const next: Record<string, string> = {}
              full.entries.forEach((e) => {
                if (prev[e.id] !== undefined) next[e.id] = prev[e.id]
              })
              const activeLog = activeLogFilenameRef.current
              if (activeLog && (prev[activeLog] ?? '').length > 0) {
                next[activeLog] = prev[activeLog]
              }
              return next
            })
            return
          }
          setFeedEntries((prev) => {
            const keys = new Set(prev.map((e) => `${e.type}:${e.id}`))
            const toAdd = newEntries.filter((e) => !keys.has(`${e.type}:${e.id}`))
            return toAdd.length ? [...prev, ...toAdd] : prev
          })
          if (opts?.prefetchNew && newEntries.length > 0) {
            const activeLog = activeLogFilenameRef.current
            const toFetch = newEntries.filter(
              (entry) => !(entry.type === 'log' && entry.id === activeLog)
            )
            const texts = await Promise.all(
              toFetch.map((entry) =>
                entry.type === 'comms'
                  ? api.getTaskCommsFile(taskName, entry.id)
                  : api.getTaskLogFile(taskName, entry.id)
              )
            )
            setContents((prev) => {
              const next = { ...prev }
              toFetch.forEach((entry, i) => {
                next[entry.id] = texts[i]
              })
              newEntries.forEach((entry) => {
                if (entry.type === 'log' && entry.id === activeLog) {
                  next[entry.id] = prev[entry.id] ?? ''
                }
              })
              return next
            })
          }
        } else {
          const res = await api.getTaskFeed(taskName)
          setFeedEntries(res.entries)
          setContents((prev) => {
            const next: Record<string, string> = {}
            res.entries.forEach((e) => {
              if (prev[e.id] !== undefined) next[e.id] = prev[e.id]
            })
            const activeLog = activeLogFilenameRef.current
            if (activeLog && (prev[activeLog] ?? '').length > 0) {
              next[activeLog] = prev[activeLog]
            }
            return next
          })
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    },
    [taskName]
  )

  const handleDeleteComms = useCallback(
    async (filename: string) => {
      if (!confirm('Remove this comms entry?')) return
      setDeleteCommsError(null)
      try {
        await api.deleteCommsFile(taskName, filename)
        setFeedEntries((prev) => prev.filter((e) => !(e.type === 'comms' && e.id === filename)))
        setContents((prev) => {
          const next = { ...prev }
          delete next[filename]
          return next
        })
      } catch (e) {
        setDeleteCommsError(e instanceof Error ? e.message : String(e))
      }
    },
    [taskName]
  )

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
      loadFeed({ incremental: true, prefetchNew: true })
    }
    prevActiveCommandRef.current = activeCommand
  }, [activeCommand, loadFeed])

  useEffect(() => {
    const interval = setInterval(
      () => loadFeed({ incremental: true, prefetchNew: true }),
      FEED_POLL_INTERVAL_MS
    )
    return () => clearInterval(interval)
  }, [loadFeed])

  // When a command becomes active with an active log, reload feed so the new log entry appears
  useEffect(() => {
    if (activeCommand && activeLogFilename) {
      loadFeed({ incremental: true, prefetchNew: true })
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

  const handleCancelCommand = async () => {
    setCommandError(null)
    setCancelling(true)
    try {
      await api.cancelTaskCommand(taskName)
      // Leave cancelling true; loadCommandStatus will set it false when poll sees command inactive
    } catch (e) {
      setCommandError(e instanceof Error ? e.message : String(e))
      setCancelling(false)
    }
  }

  const handleCreatePr = async () => {
    // Invalidate any in-flight "rehydrate existing PR" request.
    prRehydrateRunIdRef.current += 1
    setPrError(null)
    setPrUrl(null)
    setPrCommentsStatus(null)
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

  const handlePullPrComments = async () => {
    setPrError(null)
    setPrCommentsStatus(null)
    setPullingPrComments(true)
    try {
      const res = await api.pullTaskPrComments(taskName)
      setPrUrl(res.pr_url)
      setPrCommentsStatus(
        res.new_comments_count === 0
          ? 'No new PR comments.'
          : `Pulled ${res.new_comments_count} new PR comment${res.new_comments_count === 1 ? '' : 's'}.`
      )
      if (res.new_comments_count > 0) {
        await loadFeed({ incremental: true, prefetchNew: true })
      }
    } catch (e) {
      setPrError(e instanceof Error ? e.message : String(e))
    } finally {
      setPullingPrComments(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    const runId = prRehydrateRunIdRef.current + 1
    prRehydrateRunIdRef.current = runId

    setPrError(null)
    setPrCommentsStatus(null)
    api.getTaskPr(taskName)
      .then((res) => {
        if (cancelled) return
        if (prRehydrateRunIdRef.current !== runId) return
        setPrUrl(res.pr_url)
      })
      .catch((e) => {
        if (cancelled) return
        if (prRehydrateRunIdRef.current !== runId) return
        setPrError(e instanceof Error ? e.message : String(e))
      })

    return () => {
      cancelled = true
    }
  }, [taskName])

  useEffect(() => {
    loadFeed()
  }, [loadFeed])

  useEffect(() => {
    if (loading || error) return
    commentDraftLoadedRef.current = false
    api.getTaskCommentDraft(taskName).then((text) => {
      setCommentText(text)
      lastSavedCommentRef.current = text
      commentDraftLoadedRef.current = true
      setCommentDraftStatus('saved')
    }).catch(() => { /* ignore */ })
  }, [taskName, loading, error])

  useEffect(() => {
    if (!commentDraftLoadedRef.current) return
    if (lastSavedCommentRef.current !== null && commentText === lastSavedCommentRef.current) {
      setCommentDraftStatus('saved')
      return
    }
    setCommentDraftStatus('unsaved')
    const t = setTimeout(() => {
      setCommentDraftStatus('saving')
      api.setTaskCommentDraft(taskName, commentText).then(() => {
        lastSavedCommentRef.current = commentText
        setCommentDraftStatus('saved')
      }).catch(() => {
        setCommentDraftStatus('unsaved')
      })
    }, DRAFT_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [taskName, commentText])

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
      lastSavedCommentRef.current = ''
      await loadFeed({ incremental: true, prefetchNew: true })
      setScrollToBottomAfterLoad(true)
    } catch (e) {
      setPostError(e instanceof Error ? e.message : String(e))
    } finally {
      setPosting(false)
    }
  }

  const handleDoFromComment = async () => {
    const prompt = commentText.trim()
    if (!prompt) return
    setPostError(null)
    setCommandError(null)
    setStartingCommand('do')
    try {
      await api.startTaskCommand(taskName, 'do', prompt)
      await loadCommandStatus()
      setCommentText('')
      lastSavedCommentRef.current = ''
      api.setTaskCommentDraft(taskName, '').catch(() => {})
      setScrollToBottomAfterLoad(true)
    } catch (e) {
      setCommandError(e instanceof Error ? e.message : String(e))
    } finally {
      setStartingCommand(null)
    }
  }

  const PROGRAMMATIC_SCROLL_MS = 150
  const PROGRAMMATIC_SCROLL_SMOOTH_MS = 800

  useEffect(() => {
    if (!loading && feedEntries.length > 0) {
      if (scrollToBottomAfterLoad) {
        setScrollToBottomAfterLoad(false)
        const scrollToBottom = () => {
          programmaticScrollRef.current = true
          window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' })
          setTimeout(() => {
            programmaticScrollRef.current = false
          }, PROGRAMMATIC_SCROLL_MS)
        }
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            scrollToBottom()
            setTimeout(scrollToBottom, 50)
          })
        })
      } else if (!hasScrolledInitialRef.current) {
        lastCommsEntryRef.current?.scrollIntoView({ behavior: 'instant' })
        hasScrolledInitialRef.current = true
      }
    }
  }, [loading, scrollToBottomAfterLoad, feedEntries.length])

  const SCROLL_NEAR_BOTTOM_PX = 80
  const SCROLL_BEHIND_THRESHOLD_PX = 24
  const LOCKED_SCROLL_THROTTLE_MS = 80

  // Bottom lock: enter when really close to bottom, leave only when user scrolls up (ignore programmatic scrolls)
  useEffect(() => {
    const onScroll = () => {
      if (programmaticScrollRef.current) return
      const nearBottom =
        window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - SCROLL_NEAR_BOTTOM_PX
      setLockedToBottom(nearBottom)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // When locked and feed grows (e.g. command started, new log entry), scroll to bottom so we stay locked
  useEffect(() => {
    const len = feedEntries.length
    if (!lockedToBottom || len === 0) {
      feedLengthRef.current = len
      return
    }
    if (len > feedLengthRef.current) {
      feedLengthRef.current = len
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          programmaticScrollRef.current = true
          window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' })
          setTimeout(() => {
            programmaticScrollRef.current = false
          }, PROGRAMMATIC_SCROLL_MS)
        })
      })
    } else {
      feedLengthRef.current = len
    }
  }, [lockedToBottom, feedEntries.length])

  const activeLogContent = activeLogFilename ? contents[activeLogFilename] : ''

  // When streaming: if locked or near bottom, scroll to bottom (throttled + only when behind to reduce jitter)
  useEffect(() => {
    if (!activeLogFilename || !activeLogContent || feedEntries.length === 0) return
    const scrollHeight = document.documentElement.scrollHeight
    const nearBottom =
      window.scrollY + window.innerHeight >= scrollHeight - SCROLL_NEAR_BOTTOM_PX
    const behind = window.scrollY + window.innerHeight < scrollHeight - SCROLL_BEHIND_THRESHOLD_PX
    const now = Date.now()
    const throttled = now - lastLockedScrollTimeRef.current < LOCKED_SCROLL_THROTTLE_MS
    if (lockedToBottom || nearBottom) {
      if (behind && !throttled) {
        lastLockedScrollTimeRef.current = now
        programmaticScrollRef.current = true
        window.scrollTo({ top: scrollHeight, behavior: 'instant' })
        setTimeout(() => {
          programmaticScrollRef.current = false
        }, PROGRAMMATIC_SCROLL_MS)
      }
    }
  }, [activeLogFilename, activeLogContent, feedEntries.length, lockedToBottom])

  const scrollToTop = () => {
    setLockedToBottom(false)
    programmaticScrollRef.current = true
    window.scrollTo({ top: 0, behavior: 'smooth' })
    setTimeout(() => {
      programmaticScrollRef.current = false
    }, PROGRAMMATIC_SCROLL_SMOOTH_MS)
  }
  const scrollToBottomClick = () => {
    setLockedToBottom(true)
    programmaticScrollRef.current = true
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' })
    setTimeout(() => {
      programmaticScrollRef.current = false
    }, PROGRAMMATIC_SCROLL_SMOOTH_MS)
  }

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
        <div className="task-comms-header-actions">
          <button
            type="button"
            className="download-comms-zip-btn archive-btn-task-view"
            onClick={handleDownloadCommsZip}
            disabled={downloadingCommsZip}
            title="Download comms (zip)"
            aria-label="Download comms (zip)"
          >
            {downloadingCommsZip ? (
              <span className="download-comms-zip-spinner" aria-hidden />
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" x2="12" y1="15" y2="3" />
              </svg>
            )}
          </button>
          <button
            type="button"
            className="archive-btn archive-btn-task-view"
            onClick={handleArchive}
            disabled={archiving}
          >
            {archiving ? 'Archiving…' : 'Archive'}
          </button>
        </div>
      </div>
      {(archiveError || downloadCommsZipError || deleteCommsError) && (
        <p className="inline-error">{archiveError ?? downloadCommsZipError ?? deleteCommsError}</p>
      )}
      <p><Link to="/">← Back to tasks</Link></p>
      {feedEntries.length === 0 ? (
        <p className="empty">No comms or agent logs yet for this task.</p>
      ) : (
        <div className="comms-history">
          {feedEntries.map((entry, i) => {
            const entryKey = `${entry.type}:${entry.id}`
            const isLast = i === feedEntries.length - 1
            return (
              <FeedEntryRow
                key={entryKey}
                entry={entry}
                contents={contents}
                loadingContentKeys={loadingContentKeys}
                isCollapsed={collapsedKeys.has(entryKey)}
                entryKey={entryKey}
                toggleCollapsed={toggleCollapsed}
                loadEntryContent={loadEntryContent}
                activeLogFilename={activeLogFilename}
                isLast={isLast}
                lastEntryRef={lastCommsEntryRef}
                onDeleteComms={handleDeleteComms}
              />
            )
          })}
        </div>
      )}
      <div className="task-commands">
        {activeCommand ? (
          <div className="command-status-row">
            {cancelling ? (
              <p className="command-status">
                <span className="command-spinner" aria-hidden /> Cancelling…
              </p>
            ) : (
              <p className="command-status">
                <span className="command-spinner" aria-hidden /> Running: {COMMAND_LABEL[activeCommand] ?? activeCommand}
              </p>
            )}
            <button
              type="button"
              className="command-btn command-cancel-btn"
              disabled={cancelling}
              onClick={handleCancelCommand}
            >
              {cancelling ? 'Cancelling…' : 'Cancel'}
            </button>
          </div>
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
              disabled={!!startingCommand || creatingPr || pullingPrComments}
              onClick={prUrl ? handlePullPrComments : handleCreatePr}
              aria-busy={creatingPr || pullingPrComments}
            >
              {prUrl
                ? (pullingPrComments ? 'Pulling comments…' : 'Pull Comments')
                : (creatingPr ? 'Creating PR…' : 'Create PR')}
            </button>
          </div>
        )}
        {commandError && <p className="inline-error">{commandError}</p>}
        {prError && <p className="inline-error">{prError}</p>}
        {prCommentsStatus && <p>{prCommentsStatus}</p>}
        {prUrl && (
          <p className="pr-result">
            <a href={prUrl} target="_blank" rel="noopener noreferrer">Open PR</a>
          </p>
        )}
      </div>
      <form className="comms-post-form" onSubmit={handlePostComment}>
        <label className="comms-post-form-label">Add comment</label>
        <div className={`draft-status draft-status-${commentDraftStatus}`} role="status" aria-live="polite">
          {commentDraftStatus === 'saved' && 'All changes saved to draft'}
          {commentDraftStatus === 'unsaved' && 'Unsaved changes'}
          {commentDraftStatus === 'saving' && 'Saving draft…'}
        </div>
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
          <button
            type="button"
            className="do-btn command-btn"
            disabled={posting || !commentText.trim() || !!startingCommand || !!activeCommand}
            onClick={handleDoFromComment}
          >
            {startingCommand === 'do' ? 'Starting…' : 'Do'}
          </button>
        </div>
      </form>
      <div className="task-comms-scroll-buttons" aria-label="Scroll">
        <button
          type="button"
          className="task-comms-scroll-btn"
          onClick={scrollToTop}
          aria-label="Scroll to top"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="m18 15-6-6-6 6" />
          </svg>
        </button>
        <button
          type="button"
          className={`task-comms-scroll-btn task-comms-scroll-btn-bottom ${lockedToBottom ? 'task-comms-scroll-btn-locked' : ''}`}
          onClick={scrollToBottomClick}
          aria-label="Scroll to bottom"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="m6 9 6 6 6-6" />
          </svg>
        </button>
      </div>
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
