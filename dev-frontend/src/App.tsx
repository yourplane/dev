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
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [addName, setAddName] = useState('')
  const [addUrl, setAddUrl] = useState('')
  const [addError, setAddError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState<string | null>(null)

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
    setSubmitting(true)
    try {
      const res = await api.createTask({
        title: title.trim(),
        repo: repo.trim(),
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
        <div className="form-actions">
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
}: {
  entry: { type: string; id: string; created_at: number }
  contents: Record<string, string>
  loadingContentKeys: Set<string>
  isCollapsed: boolean
  entryKey: string
  toggleCollapsed: (key: string) => void
  loadEntryContent: (entryId: string, type: string) => void
  activeLogFilename: string | null
  isLast: boolean
  lastEntryRef: React.RefObject<HTMLDivElement | null>
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
  const inner = (r.success != null ? (r.success as Record<string, unknown>) : r) as Record<string, unknown>
  if (typeof inner.output === 'string') return inner.output
  if (typeof inner.combinedOutput === 'string') return inner.combinedOutput
  if (typeof inner.interleavedOutput === 'string') return inner.interleavedOutput
  const stdout = typeof inner.stdout === 'string' ? inner.stdout : ''
  const stderr = typeof inner.stderr === 'string' ? inner.stderr : ''
  return stderr ? stdout + (stdout ? '\n' : '') + stderr : stdout
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

function getTodoList(result: unknown): Array<{ id?: string; content?: string; status?: string }> {
  if (result == null) return []
  const r = result as Record<string, unknown>
  const success = r.success as Record<string, unknown> | undefined
  const todos = success?.todos ?? success?.todo ?? r.todos ?? r.todo
  return Array.isArray(todos) ? todos : []
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

function getWebSearchUrl(result: unknown, args: Record<string, unknown>): string {
  if (result != null) {
    const r = result as Record<string, unknown>
    if (typeof r.url === 'string') return r.url
  }
  return typeof args.url === 'string' ? args.url : ''
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
    return (
      <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-shell">
        <pre className="feed-log-shell-block">{block || ' '}</pre>
      </div>
    )
  }

  if (toolKey === 'todo_writeToolCall') {
    const todos = getTodoList(result)
    return (
      <div className="feed-log-segment feed-log-tool-call">
        <div className="feed-log-tool-call-header">
          <span className="feed-log-segment-label">{humanLabel}</span>
        </div>
        <div className="feed-log-segment-body">
          <ul className="feed-log-tool-call-todos">
            {todos.map((t, i) => (
              <li key={t.id ?? i}>
                {[t.status, t.content].filter(Boolean).join(' – ')}
              </li>
            ))}
          </ul>
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

  if (toolKey === 'web_searchToolCall') {
    const query = typeof args.query === 'string' ? args.query : ''
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

  if (toolKey === 'mcp_web_fetchToolCall') {
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
          <a href={href} target="_blank" rel="noopener noreferrer" className="feed-log-tool-call-web-fetch-link">
            <span className="feed-log-tool-call-globe-icon" aria-hidden />
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
  const [cancelling, setCancelling] = useState(false)
  const [creatingPr, setCreatingPr] = useState(false)
  const [prUrl, setPrUrl] = useState<string | null>(null)
  const [prError, setPrError] = useState<string | null>(null)
  const [scrollToBottomAfterLoad, setScrollToBottomAfterLoad] = useState(false)
  const [lockedToBottom, setLockedToBottom] = useState(false)
  const programmaticScrollRef = useRef(false)
  const feedLengthRef = useRef(0)
  const lastLockedScrollTimeRef = useRef(0)
  const lastCommsEntryRef = useRef<HTMLDivElement | null>(null)
  const feedEntriesRef = useRef(feedEntries)
  feedEntriesRef.current = feedEntries
  const activeLogFilenameRef = useRef(activeLogFilename)
  activeLogFilenameRef.current = activeLogFilename
  const hasScrolledInitialRef = useRef(false)
  const [archiving, setArchiving] = useState(false)
  const [archiveError, setArchiveError] = useState<string | null>(null)
  const [collapsedKeys, setCollapsedKeys] = useState<Set<string>>(new Set())
  const [loadingContentKeys, setLoadingContentKeys] = useState<Set<string>>(new Set())

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
      await loadFeed({ incremental: true, prefetchNew: true })
      setScrollToBottomAfterLoad(true)
    } catch (e) {
      setPostError(e instanceof Error ? e.message : String(e))
    } finally {
      setPosting(false)
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

  // When streaming: if locked or near bottom, scroll to bottom (throttled + only when behind to reduce jitter)
  useEffect(() => {
    if (!activeLogFilename || !contents[activeLogFilename] || feedEntries.length === 0) return
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
  }, [activeLogFilename, contents[activeLogFilename], feedEntries.length, lockedToBottom])

  const scrollToTop = () => {
    programmaticScrollRef.current = true
    window.scrollTo({ top: 0, behavior: 'smooth' })
    setTimeout(() => {
      programmaticScrollRef.current = false
    }, PROGRAMMATIC_SCROLL_SMOOTH_MS)
  }
  const scrollToBottomClick = () => {
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
            className="archive-btn archive-btn-task-view"
            onClick={handleArchive}
            disabled={archiving}
          >
            {archiving ? 'Archiving…' : 'Archive'}
          </button>
        </div>
      </div>
      {archiveError && <p className="inline-error">{archiveError}</p>}
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
