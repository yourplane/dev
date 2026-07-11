import { useState, useEffect, useCallback, useRef, useMemo, memo } from 'react'
import { BrowserRouter, Link, Routes, Route, useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, apiBaseUrl, type TaskWorkspaceInfo, type EnvironmentInfo } from './api'
import { bashTranscriptShellDisplayBlocks, extractBashCommandFromTranscript } from './bashTranscript'
import {
  buildFeedNavTargets,
  findCurrentNavIndex,
  isNearPageBottom,
  navTargetId,
  scrollToNavTarget,
  type FeedNavTarget,
} from './feedScrollNav'
import { isCloudMode, getIdToken, signIn, signOut, completeNewPassword, restoreCloudSession } from './cloudAuth'
import { parseLogToSegments, type LogSegment, type ToolCallInfo } from './logParser'
import { QuestionAnswerForm } from './QuestionAnswerForm'
import { getPersistedAnswersForSource, tryParseQuestionPayload, userAnswersContentsKey, type SubmittedAnswers } from './questionForm'
import './App.css'

const markdownComponents: Partial<Components> = {
  table: ({ children, ...props }) => (
    <div className="markdown-table-scroll">
      <table {...props}>{children}</table>
    </div>
  ),
}

function MarkdownText({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {children}
    </ReactMarkdown>
  )
}

const FEED_POLL_INTERVAL_MS = 15000
const FEED_PAGE_SIZE = 50
const ARCHIVE_PAGE_SIZE = 50

export function Layout() {
  return (
    <div className="app">
      <header className="header">
        <h1 className="logo"><Link to="/">Dev</Link></h1>
        <nav>
          <Link to="/" className="nav-link">Tasks</Link>
          <Link to="/new" className="nav-link">New task</Link>
          <Link to="/archive" className="nav-link">Archive</Link>
          {isCloudMode() && <Link to="/settings" className="nav-link">Settings</Link>}
        </nav>
      </header>
      <main className="main">
        <Routes>
          <Route index element={<TaskListPage />} />
          <Route path="new" element={<CreateTaskPage />} />
          <Route path="archive" element={<ArchivePage />} />
          {isCloudMode() && <Route path="settings" element={<SettingsPage />} />}
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

function formatTimestampLabel(timestamp: string): string {
  if (!timestamp) return 'Unknown'
  const parsed = new Date(timestamp)
  if (Number.isNaN(parsed.getTime())) return 'Unknown'
  return parsed.toLocaleString()
}

function ArchivePage() {
  const [entries, setEntries] = useState<Array<{
    archived_name: string
    task_name: string
    archived_date: string
    archived_at: string
    last_modified_at: string
  }>>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [unarchiving, setUnarchiving] = useState<string | null>(null)
  const [unarchiveError, setUnarchiveError] = useState<string | null>(null)
  const [restoredTask, setRestoredTask] = useState<string | null>(null)
  const [copyFromArchiveLoading, setCopyFromArchiveLoading] = useState<string | null>(null)
  const [copyFromArchiveError, setCopyFromArchiveError] = useState<string | null>(null)
  const [copiedTask, setCopiedTask] = useState<string | null>(null)
  const [archiveTotal, setArchiveTotal] = useState(0)
  const [nextOffset, setNextOffset] = useState<number | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)

  const loadArchive = useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const res = await api.getArchive({ limit: ARCHIVE_PAGE_SIZE, offset: 0 })
      setEntries(res.entries)
      setArchiveTotal(res.total)
      setNextOffset(res.next_offset)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const loadMoreArchive = useCallback(async () => {
    if (nextOffset == null) return
    setError(null)
    setLoadingMore(true)
    try {
      const res = await api.getArchive({ limit: ARCHIVE_PAGE_SIZE, offset: nextOffset })
      setEntries((prev) => [...prev, ...res.entries])
      setArchiveTotal(res.total)
      setNextOffset(res.next_offset)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoadingMore(false)
    }
  }, [nextOffset])

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
  const dateOrder = Object.keys(byDate)

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
                    <div className="archive-task-meta">
                      <span className="task-name">{e.task_name}</span>
                      <span className="archive-task-subtext">Last modified {formatTimestampLabel(e.last_modified_at)}</span>
                    </div>
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
          {nextOffset != null && (
            <div className="archive-pagination">
              <button
                type="button"
                className="archive-load-more-btn"
                onClick={loadMoreArchive}
                disabled={loadingMore}
              >
                {loadingMore ? 'Loading…' : `Load more (${entries.length}/${archiveTotal})`}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  )
}

const DRAFT_DEBOUNCE_MS = 400

/** Sentinel radio value for “no repository” (draft/API use JSON null). */
const CREATE_TASK_NO_REPO = '__no_repo__'

function CreateTaskForm({
  onCreated,
  onCancel,
}: {
  onCreated: (taskName: string) => void
  onCancel: () => void
}) {
  const [repos, setRepos] = useState<Record<string, string>>({})
  const [environments, setEnvironments] = useState<EnvironmentInfo[]>([])
  const [environmentId, setEnvironmentId] = useState('')
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
  const lastSavedSnapshotRef = useRef<{
    title: string
    repo: string
    comment: string
  } | null>(null)

  const loadRepos = useCallback(() => {
    return api.getRepos().then(setRepos)
  }, [])

  useEffect(() => {
    let cancelled = false
    const loads: Promise<unknown>[] = [api.getRepos().then((r) => { if (!cancelled) setRepos(r) })]
    if (isCloudMode()) {
      loads.push(
        api.getEnvironments().then((r) => {
          if (cancelled) return
          setEnvironments(r.environments)
          const online = r.environments.find((e) => e.online)
          if (online) setEnvironmentId(online.environment_id)
          else if (r.environments[0]) setEnvironmentId(r.environments[0].environment_id)
        }),
      )
    }
    Promise.all(loads).finally(() => {
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
      const loadedRepo = d.repo === null ? CREATE_TASK_NO_REPO : (typeof d.repo === 'string' ? d.repo : '')
      const loadedComment = d.comment ?? ''
      setTitle(loadedTitle)
      setRepo(loadedRepo)
      setComment(loadedComment)
      lastSavedSnapshotRef.current = {
        title: loadedTitle,
        repo: loadedRepo,
        comment: loadedComment,
      }
      draftLoadedRef.current = true
      setDraftStatus('saved')
    }).catch(() => { /* ignore */ })
    return () => { cancelled = true }
  }, [reposLoading])

  useEffect(() => {
    if (!draftLoadedRef.current) return
    const snapshot = lastSavedSnapshotRef.current
    if (
      snapshot
      && title === snapshot.title
      && repo === snapshot.repo
      && comment === snapshot.comment
    ) {
      setDraftStatus('saved')
      return
    }
    setDraftStatus('unsaved')
    const t = setTimeout(() => {
      const payload = { title, repo: repo === CREATE_TASK_NO_REPO ? null : repo, comment }
      const empty = !title.trim() && !comment.trim() && repo !== CREATE_TASK_NO_REPO && !repo.trim()
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
    if (repo !== CREATE_TASK_NO_REPO && !repo.trim()) { setError('Select a repo'); return }
    if (isCloudMode() && !environmentId) { setError('Select an environment'); return }
    setCreateStatusMessage(null)
    setSubmitting(true)
    try {
      const res = await api.createTask(
        {
          title: title.trim(),
          repo: repo === CREATE_TASK_NO_REPO ? null : repo.trim(),
          comment: comment.trim() || undefined,
          environment_id: isCloudMode() ? environmentId : undefined,
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
        {isCloudMode() && (
          <label>
            <span>Environment <span className="required">*</span></span>
            {environments.length === 0 ? (
              <span className="hint">No environments registered yet. Start a worker on your server.</span>
            ) : (
              <select value={environmentId} onChange={(e) => setEnvironmentId(e.target.value)} required>
                {environments.map((env) => (
                  <option key={env.environment_id} value={env.environment_id}>
                    {env.display_name} {env.online ? '(online)' : '(offline)'}
                  </option>
                ))}
              </select>
            )}
          </label>
        )}
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
            <>
            <div className="repo-radio-group" role="radiogroup" aria-label="Repository">
              <div className="repo-radio-option repo-radio-row">
                <label className="repo-radio-label">
                  <input
                    type="radio"
                    name="repo"
                    value={CREATE_TASK_NO_REPO}
                    checked={repo === CREATE_TASK_NO_REPO}
                    onChange={() => setRepo(CREATE_TASK_NO_REPO)}
                  />
                  <span>No repository (CLI: <code>--no-repo</code>)</span>
                </label>
              </div>
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
            {Object.keys(repos).length === 0 && (
              <p className="hint">No saved shorthands yet. Add one below, or choose “No repository”.</p>
            )}
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
  'create-task': 'Create task',
  question: 'Question',
  'plan-implement': 'Plan',
  implement: 'Implement',
  do: 'Do',
  bash: 'Bash',
  'merge-from-main': 'Merge from main',
}

type AgentModeCommand = 'question' | 'plan-implement' | 'implement'
type AgentMenuCommand = AgentModeCommand | 'merge-from-main'

const AGENT_MODE_DEFAULT: AgentModeCommand = 'question'
const LAST_AGENT_CMD_STORAGE_KEY = 'dev_last_agent_command'

function readLastAgentCommand(): AgentModeCommand {
  try {
    const stored = localStorage.getItem(LAST_AGENT_CMD_STORAGE_KEY)
    if (stored === 'question' || stored === 'plan-implement' || stored === 'implement') {
      return stored
    }
  } catch {
    // ignore
  }
  return AGENT_MODE_DEFAULT
}

function writeLastAgentCommand(cmd: AgentModeCommand) {
  try {
    localStorage.setItem(LAST_AGENT_CMD_STORAGE_KEY, cmd)
  } catch {
    // ignore
  }
}

function AgentCommandSplitButton({
  selectedCommand,
  onSelectCommand,
  onRunCommand,
  startingCommand,
  disabled,
  hasRepo,
}: {
  selectedCommand: AgentModeCommand
  onSelectCommand: (cmd: AgentModeCommand) => void
  onRunCommand: (cmd: AgentMenuCommand) => void
  startingCommand: string | null
  disabled: boolean
  hasRepo: boolean
}) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const agentCommands: AgentModeCommand[] = hasRepo
    ? ['question', 'plan-implement', 'implement']
    : ['question', 'plan-implement']

  const menuItems: AgentMenuCommand[] = hasRepo
    ? [...agentCommands, 'merge-from-main']
    : agentCommands

  const effectiveSelected = agentCommands.includes(selectedCommand)
    ? selectedCommand
    : AGENT_MODE_DEFAULT

  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  const label = startingCommand === effectiveSelected
    ? 'Starting…'
    : (COMMAND_LABEL[effectiveSelected] ?? effectiveSelected)

  return (
    <div className="command-split" ref={containerRef}>
      <div className="command-split-control">
        <button
          type="button"
          className="command-btn command-split-main"
          disabled={disabled}
          onClick={() => onRunCommand(effectiveSelected)}
        >
          {label}
        </button>
        <span className="command-split-divider" aria-hidden />
        <button
          type="button"
          className="command-btn command-split-toggle"
          disabled={disabled}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label="Choose agent command"
          onClick={(e) => {
            e.stopPropagation()
            setOpen((v) => !v)
          }}
        >
          <span className="command-split-chevron" aria-hidden>▾</span>
        </button>
      </div>
      {open && (
        <ul className="command-split-menu" role="menu">
          {menuItems.map((cmd) => (
            <li key={cmd} role="none">
              <button
                type="button"
                role="menuitem"
                className={
                  cmd === effectiveSelected
                    ? 'command-split-menu-item command-split-menu-item-active'
                    : 'command-split-menu-item'
                }
                onClick={() => {
                  if (cmd !== 'merge-from-main') {
                    onSelectCommand(cmd)
                  }
                  onRunCommand(cmd)
                  setOpen(false)
                }}
              >
                {COMMAND_LABEL[cmd]}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function isBashCommsEntry(entryId: string): boolean {
  return entryId.endsWith('-user-bash.md')
}

/** Bash transcript: dark shell block for command+output; footer after `---` shown separately (016-user). */
function BashCommsFeedBody({ text }: { text: string }) {
  const { loading, shellBody, metaPart } = bashTranscriptShellDisplayBlocks(text)
  if (loading) {
    return (
      <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-shell">
        <pre className="feed-log-shell-block">{text}</pre>
      </div>
    )
  }
  return (
    <>
      <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-shell">
        <pre className="feed-log-shell-block">{shellBody}</pre>
      </div>
      {metaPart !== '' ? (
        <div className="feed-comms-bash-meta-outside">
          <pre className="feed-comms-bash-meta-outside-pre">{metaPart}</pre>
        </div>
      ) : null}
    </>
  )
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
  taskName,
  onFeedRefresh,
  persistedAnswers,
}: {
  entry: { type: string; id: string; created_at: number; deletable?: boolean | null }
  contents: Record<string, string>
  loadingContentKeys: Set<string>
  isCollapsed: boolean
  entryKey: string
  toggleCollapsed: (entry: { type: string; id: string; created_at: number; deletable?: boolean | null }, key: string) => void
  loadEntryContent: (entryId: string, type: string) => void
  activeLogFilename: string | null
  isLast: boolean
  lastEntryRef: React.RefObject<HTMLDivElement>
  onDeleteComms?: (filename: string) => void
  taskName: string
  onFeedRefresh?: () => void
  persistedAnswers?: SubmittedAnswers | null
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

  const rawContent = contents[entry.id] ?? '(loading…)'
  const questionPayload =
    entry.type === 'comms' && entry.id.endsWith('-agent-question.md') && rawContent !== '(loading…)'
      ? tryParseQuestionPayload(rawContent)
      : null

  return (
    <div
      ref={isLast ? lastEntryRef : undefined}
      className={entry.type === 'log' ? 'feed-entry feed-log-entry' : 'comms-entry'}
    >
      <div className="feed-entry-header-row">
        <button
          type="button"
          className="feed-entry-header"
          data-feed-nav-type="header"
          data-feed-nav-key={entryKey}
          onClick={() => toggleCollapsed(entry, entryKey)}
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
          ) : isBashCommsEntry(entry.id) ? (
            <BashCommsFeedBody text={rawContent} />
          ) : questionPayload ? (
            <QuestionAnswerForm
              taskName={taskName}
              sourceFilename={entry.id}
              payload={questionPayload}
              persistedAnswers={persistedAnswers}
              onSubmitted={onFeedRefresh}
            />
          ) : (
            <MarkdownText>{rawContent}</MarkdownText>
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
    return (
      <div className="feed-log-segment feed-log-tool-call feed-log-tool-call-shell">
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
          <MarkdownText>{text.trim() || '\u00a0'}</MarkdownText>
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
        <MarkdownText>{text.trim() || '\u00a0'}</MarkdownText>
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

type FeedCollapseState = {
  collapsedKeys: Set<string>
  logCollapseTouchedKeys: Set<string>
}

function createInitialFeedCollapseState(): FeedCollapseState {
  return {
    collapsedKeys: new Set(),
    logCollapseTouchedKeys: new Set(),
  }
}

type FeedOutlineEntry = {
  type: string
  id: string
  created_at: number
  deletable?: boolean | null
}

type FeedOutlineCache = {
  entries: FeedOutlineEntry[]
  feedTotal: number
  hasOlder: boolean
  oldestCursor: { created_at: number; id: string } | null
}

function feedOutlineCacheKey(taskName: string) {
  return `dev_feed_outline_${taskName}`
}

function readFeedOutlineCache(taskName: string): FeedOutlineCache | null {
  try {
    const raw = sessionStorage.getItem(feedOutlineCacheKey(taskName))
    if (!raw) return null
    return JSON.parse(raw) as FeedOutlineCache
  } catch {
    return null
  }
}

function writeFeedOutlineCache(taskName: string, cache: FeedOutlineCache) {
  try {
    sessionStorage.setItem(feedOutlineCacheKey(taskName), JSON.stringify(cache))
  } catch {
    // ignore quota errors
  }
}

export function TaskCommsPageContent({
  taskName,
  navigate,
}: {
  taskName: string
  navigate: (to: string) => void
}) {
  const [feedEntries, setFeedEntries] = useState<FeedOutlineEntry[]>([])
  const [feedTotal, setFeedTotal] = useState(0)
  const [hasOlder, setHasOlder] = useState(false)
  const [oldestCursor, setOldestCursor] = useState<{ created_at: number; id: string } | null>(null)
  const [contents, setContents] = useState<Record<string, string>>({})
  const [feedReady, setFeedReady] = useState(false)
  const [feedRefreshing, setFeedRefreshing] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [entryMode, setEntryMode] = useState<'prompt' | 'bash'>('prompt')
  const [commentText, setCommentText] = useState('')
  const [shellInput, setShellInput] = useState('')
  const [posting, setPosting] = useState(false)
  const [postError, setPostError] = useState<string | null>(null)
  const [activeCommand, setActiveCommand] = useState<string | null>(null)
  const [pendingCommand, setPendingCommand] = useState<string | null>(null)
  const [pendingCommandState, setPendingCommandState] = useState<'syncing' | 'worker_offline' | null>(null)
  const [createProgress, setCreateProgress] = useState<string[]>([])
  const [activeLogFilename, setActiveLogFilename] = useState<string | null>(null)
  const [commandError, setCommandError] = useState<string | null>(null)
  const [lastAgentCommand, setLastAgentCommand] = useState<AgentModeCommand>(readLastAgentCommand)
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
  const prevActiveCommandRef = useRef<string | null>(null)
  const [archiving, setArchiving] = useState(false)
  const [archiveError, setArchiveError] = useState<string | null>(null)
  const [downloadingCommsZip, setDownloadingCommsZip] = useState(false)
  const [downloadCommsZipError, setDownloadCommsZipError] = useState<string | null>(null)
  const [deleteCommsError, setDeleteCommsError] = useState<string | null>(null)
  const [feedCollapse, setFeedCollapse] = useState<FeedCollapseState>(createInitialFeedCollapseState)
  const [loadingContentKeys, setLoadingContentKeys] = useState<Set<string>>(new Set())
  const [commentDraftStatus, setCommentDraftStatus] = useState<'saved' | 'unsaved' | 'saving'>('saved')
  const commentDraftLoadedRef = useRef(false)
  const lastSavedCommentRef = useRef<string | null>(null)
  const [bashDraftStatus, setBashDraftStatus] = useState<'saved' | 'unsaved' | 'saving'>('saved')
  const bashDraftLoadedRef = useRef(false)
  const lastSavedBashRef = useRef<string | null>(null)
  const [bashHistoryBrowseIdx, setBashHistoryBrowseIdx] = useState<number | null>(null)
  const [bashHistoryPicker, setBashHistoryPicker] = useState('')
  const [activeBashCommsFilename, setActiveBashCommsFilename] = useState<string | null>(null)
  const [workspaceInfo, setWorkspaceInfo] = useState<TaskWorkspaceInfo | null>(null)
  const tabVisibleRef = useRef(!document.hidden)
  const oldestCursorRef = useRef(oldestCursor)
  oldestCursorRef.current = oldestCursor
  const feedTotalRef = useRef(feedTotal)
  feedTotalRef.current = feedTotal
  const hasOlderRef = useRef(hasOlder)
  hasOlderRef.current = hasOlder
  const pendingNavAfterLoadRef = useRef<{ prevFirstId: string } | null>(null)
  const loadingOlderRef = useRef(loadingOlder)
  loadingOlderRef.current = loadingOlder

  const bashHistory = useMemo(() => {
    const cmds: string[] = []
    for (const e of feedEntries) {
      if (e.type !== 'comms' || !isBashCommsEntry(e.id)) continue
      const text = contents[e.id]
      if (text === undefined || text === '(loading…)') continue
      const cmd = extractBashCommandFromTranscript(text)
      if (cmd !== null) cmds.push(cmd)
    }
    return cmds
  }, [feedEntries, contents])

  const bashHistoryRef = useRef<string[]>([])
  bashHistoryRef.current = bashHistory
  const activeBashCommsFilenameRef = useRef<string | null>(null)
  activeBashCommsFilenameRef.current = activeBashCommsFilename

  const getEntryCollapsed = useCallback(
    (entry: { type: string; id: string }, entryKey: string) => {
      if (entry.type === 'log') {
        if (feedCollapse.logCollapseTouchedKeys.has(entryKey)) {
          return feedCollapse.collapsedKeys.has(entryKey)
        }
        if (activeLogFilename === null) return true
        return entry.id !== activeLogFilename
      }
      return feedCollapse.collapsedKeys.has(entryKey)
    },
    [feedCollapse, activeLogFilename],
  )

  const toggleCollapsed = useCallback(
    (entry: { type: string; id: string }, entryKey: string) => {
      if (entry.type !== 'log') {
        setFeedCollapse((s) => {
          const nextCollapsed = new Set(s.collapsedKeys)
          if (nextCollapsed.has(entryKey)) nextCollapsed.delete(entryKey)
          else nextCollapsed.add(entryKey)
          return { ...s, collapsedKeys: nextCollapsed }
        })
        return
      }
      setFeedCollapse((s) => {
        const nextTouched = new Set(s.logCollapseTouchedKeys)
        const wasTouched = nextTouched.has(entryKey)
        nextTouched.add(entryKey)
        const nextCollapsed = new Set(s.collapsedKeys)
        if (wasTouched) {
          if (nextCollapsed.has(entryKey)) nextCollapsed.delete(entryKey)
          else nextCollapsed.add(entryKey)
        } else {
          const defaultCollapsed = entry.id !== activeLogFilename
          const newCollapsed = !defaultCollapsed
          if (newCollapsed) nextCollapsed.add(entryKey)
          else nextCollapsed.delete(entryKey)
        }
        return { collapsedKeys: nextCollapsed, logCollapseTouchedKeys: nextTouched }
      })
    },
    [activeLogFilename],
  )

  useEffect(() => {
    let cancelled = false
    setWorkspaceInfo(null)
    api
      .getTaskWorkspace(taskName)
      .then((ws) => {
        if (!cancelled) setWorkspaceInfo(ws)
      })
      .catch(() => {
        if (!cancelled) {
          setWorkspaceInfo({ repo_label: '—' })
        }
      })
    return () => {
      cancelled = true
    }
  }, [taskName])

  useEffect(() => {
    if (workspaceInfo?.repo_label === null) {
      setCommandError(null)
    }
  }, [workspaceInfo?.repo_label])

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
      const running = Boolean(res.active && res.command)
      const pending = Boolean(!res.active && res.command)
      setActiveCommand(running ? res.command : null)
      setPendingCommand(pending ? res.command : null)
      setPendingCommandState(res.pending_state ?? (pending ? 'syncing' : null))
      setCreateProgress(res.create_progress ?? [])
      setCancelling(Boolean(res.cancelling))
      setActiveLogFilename(res.active && res.active_log_filename ? res.active_log_filename : null)
      setActiveBashCommsFilename(
        res.active && res.active_bash_comms_filename ? res.active_bash_comms_filename : null,
      )
      if (running || pending) {
        setCommandError(null)
      } else if (res.command_error) {
        setCommandError(res.command_error)
      }
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
      if (type === 'comms' && entryId === activeBashCommsFilenameRef.current) {
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

  const prefetchedUserAnswersRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    prefetchedUserAnswersRef.current = new Set()
  }, [taskName])

  const answersContentsKey = userAnswersContentsKey(feedEntries, contents)

  const persistedAnswersBySource = useMemo(() => {
    const out: Record<string, SubmittedAnswers | null | undefined> = {}
    for (const entry of feedEntries) {
      if (entry.type !== 'comms' || !entry.id.endsWith('-agent-question.md')) continue
      out[entry.id] = getPersistedAnswersForSource(entry.id, feedEntries, contents)
    }
    return out
  }, [feedEntries, answersContentsKey])

  useEffect(() => {
    for (const entry of feedEntries) {
      if (entry.type !== 'comms' || !entry.id.endsWith('-user-answers.md')) continue
      if (contents[entry.id] !== undefined || prefetchedUserAnswersRef.current.has(entry.id)) continue
      prefetchedUserAnswersRef.current.add(entry.id)
      void loadEntryContent(entry.id, 'comms')
    }
  }, [feedEntries, loadEntryContent])

  const applyFeedPage = useCallback(
    (
      res: {
        entries: FeedOutlineEntry[]
        total?: number | null
        has_older?: boolean | null
        oldest_cursor?: { created_at: number; id: string } | null
      },
      mode: 'replace' | 'prepend',
    ) => {
      const total = res.total ?? res.entries.length
      const nextHasOlder = res.has_older ?? false
      const nextOldest = res.oldest_cursor ?? null
      setFeedTotal(total)
      setHasOlder(nextHasOlder)
      setOldestCursor(nextOldest)
      setFeedEntries((prev) => {
        let next: FeedOutlineEntry[]
        if (mode === 'replace') {
          next = res.entries
        } else {
          const keys = new Set(prev.map((e) => `${e.type}:${e.id}`))
          const toPrepend = res.entries.filter((e) => !keys.has(`${e.type}:${e.id}`))
          next = toPrepend.length ? [...toPrepend, ...prev] : prev
        }
        writeFeedOutlineCache(taskName, {
          entries: next,
          feedTotal: total,
          hasOlder: nextHasOlder,
          oldestCursor: nextOldest,
        })
        return next
      })
    },
    [taskName],
  )

  const patchCommsDeletable = useCallback(async () => {
    try {
      const deletable = await api.getTaskFeedDeletable(taskName)
      setFeedEntries((prev) => {
        const next = prev.map((e) =>
          e.type === 'comms' && deletable[e.id] !== undefined ? { ...e, deletable: deletable[e.id] } : e,
        )
        writeFeedOutlineCache(taskName, {
          entries: next,
          feedTotal: feedTotalRef.current,
          hasOlder: hasOlderRef.current,
          oldestCursor: oldestCursorRef.current,
        })
        return next
      })
    } catch {
      // non-fatal; deletable flags may be stale until next full load
    }
  }, [taskName])

  const loadFeedTail = useCallback(async () => {
    const hasVisibleEntries = feedEntriesRef.current.length > 0
    if (!hasVisibleEntries) setFeedRefreshing(true)
    setError(null)
    try {
      const res = await api.getTaskFeed(taskName, { limit: FEED_PAGE_SIZE })
      applyFeedPage(res, 'replace')
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
    } catch (e) {
      if (!hasVisibleEntries) {
        setError(e instanceof Error ? e.message : String(e))
      }
    } finally {
      setFeedRefreshing(false)
      setFeedReady(true)
    }
  }, [taskName, applyFeedPage])

  const loadOlderFeed = useCallback(async () => {
    const cursor = oldestCursorRef.current
    if (!cursor || loadingOlder) return
    setLoadingOlder(true)
    setError(null)
    try {
      const res = await api.getTaskFeed(taskName, { limit: FEED_PAGE_SIZE, before: cursor })
      applyFeedPage(res, 'prepend')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoadingOlder(false)
    }
  }, [taskName, applyFeedPage, loadingOlder])

  const SCROLL_NEAR_BOTTOM_PX = 80
  const SCROLL_BEHIND_THRESHOLD_PX = 24
  const LOCKED_SCROLL_THROTTLE_MS = 80
  const PROGRAMMATIC_SCROLL_MS = 150
  const PROGRAMMATIC_SCROLL_SMOOTH_MS = 800

  const buildNavTargets = useCallback((): FeedNavTarget[] => {
    return buildFeedNavTargets(feedEntries, (entryKey, entry) => getEntryCollapsed(entry, entryKey))
  }, [feedEntries, getEntryCollapsed])

  const runProgrammaticScroll = useCallback((durationMs: number, fn: () => void) => {
    programmaticScrollRef.current = true
    fn()
    setTimeout(() => {
      programmaticScrollRef.current = false
    }, durationMs)
  }, [])

  const applyLockAfterNavStep = useCallback(
    (direction: 'up' | 'down') => {
      if (direction === 'up') {
        setLockedToBottom(false)
      } else if (isNearPageBottom(SCROLL_NEAR_BOTTOM_PX)) {
        setLockedToBottom(true)
      }
    },
    [],
  )

  const scrollToNavTargetWithLock = useCallback(
    (target: FeedNavTarget, direction: 'up' | 'down') => {
      runProgrammaticScroll(PROGRAMMATIC_SCROLL_SMOOTH_MS, () => {
        scrollToNavTarget(target, 'smooth')
        setTimeout(() => applyLockAfterNavStep(direction), PROGRAMMATIC_SCROLL_SMOOTH_MS)
      })
    },
    [applyLockAfterNavStep, runProgrammaticScroll],
  )

  const scrollOneEntry = useCallback(
    async (direction: 'up' | 'down') => {
      const targets = buildNavTargets()
      if (targets.length === 0) return

      let currentIdx = findCurrentNavIndex(targets, SCROLL_NEAR_BOTTOM_PX)
      if (currentIdx < 0) currentIdx = direction === 'down' ? -1 : 0

      if (direction === 'up') {
        if (currentIdx <= 0 && hasOlderRef.current && !loadingOlderRef.current) {
          pendingNavAfterLoadRef.current = { prevFirstId: navTargetId(targets[0]) }
          await loadOlderFeed()
          return
        }
        const nextIdx = Math.max(0, currentIdx - 1)
        if (nextIdx === currentIdx) return
        scrollToNavTargetWithLock(targets[nextIdx], direction)
        return
      }

      const nextIdx = Math.min(targets.length - 1, currentIdx + 1)
      if (nextIdx === currentIdx) return
      scrollToNavTargetWithLock(targets[nextIdx], direction)
    },
    [buildNavTargets, loadOlderFeed, scrollToNavTargetWithLock],
  )

  const scrollOneEntryUp = () => {
    void scrollOneEntry('up')
  }
  const scrollOneEntryDown = () => {
    void scrollOneEntry('down')
  }

  const pollFeedIncremental = useCallback(
    async (opts?: { prefetchNew?: boolean }) => {
      const current = feedEntriesRef.current
      if (current.length === 0) {
        await loadFeedTail()
        return
      }
      try {
        const after = Math.max(...current.map((e) => e.created_at))
        const res = await api.getTaskFeed(taskName, { after })
        const existingKeys = new Set(current.map((e) => `${e.type}:${e.id}`))
        const newEntries = res.entries.filter((e) => !existingKeys.has(`${e.type}:${e.id}`))
        if (newEntries.length === 0) return
        if (newEntries.some((e) => e.type === 'log')) {
          await patchCommsDeletable()
        }
        setFeedEntries((prev) => {
          const keys = new Set(prev.map((e) => `${e.type}:${e.id}`))
          const toAdd = newEntries.filter((e) => !keys.has(`${e.type}:${e.id}`))
          if (!toAdd.length) return prev
          const next = [...prev, ...toAdd]
          writeFeedOutlineCache(taskName, {
            entries: next,
            feedTotal: Math.max(feedTotalRef.current, next.length),
            hasOlder: hasOlderRef.current,
            oldestCursor: oldestCursorRef.current,
          })
          return next
        })
        if (opts?.prefetchNew && newEntries.length > 0) {
          const activeLog = activeLogFilenameRef.current
          const toFetch = newEntries.filter((entry) => !(entry.type === 'log' && entry.id === activeLog))
          const texts = await Promise.all(
            toFetch.map((entry) =>
              entry.type === 'comms'
                ? api.getTaskCommsFile(taskName, entry.id)
                : api.getTaskLogFile(taskName, entry.id),
            ),
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
      } catch {
        // ignore transient poll errors
      }
    },
    [taskName, loadFeedTail, patchCommsDeletable],
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
    const interval = setInterval(() => {
      if (tabVisibleRef.current) loadCommandStatus()
    }, 1000)
    return () => clearInterval(interval)
  }, [loadCommandStatus])

  useEffect(() => {
    const onVisibility = () => {
      tabVisibleRef.current = !document.hidden
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [])

  useEffect(() => {
    if (!import.meta.env.DEV) return
    const onPageShow = (event: PageTransitionEvent) => {
      console.debug('[dev-ui] pageshow persisted=', event.persisted)
    }
    window.addEventListener('pageshow', onPageShow)
    return () => window.removeEventListener('pageshow', onPageShow)
  }, [])

  const commandInFlight = activeCommand ?? pendingCommand

  useEffect(() => {
    if (prevActiveCommandRef.current !== null && activeCommand === null) {
      // Command completion may remove empty logs, so reload feed tail to drop stale entries.
      loadFeedTail()
    }
    prevActiveCommandRef.current = activeCommand
  }, [activeCommand, loadFeedTail])

  useEffect(() => {
    const interval = setInterval(() => {
      if (tabVisibleRef.current) {
        pollFeedIncremental({ prefetchNew: true })
      }
    }, FEED_POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [pollFeedIncremental])

  // When a command becomes active with an active log, reload feed so the new log entry appears
  useEffect(() => {
    if (activeCommand && activeLogFilename) {
      pollFeedIncremental({ prefetchNew: true })
    }
  }, [activeCommand, activeLogFilename, pollFeedIncremental])

  useEffect(() => {
    if (activeBashCommsFilename && activeCommand) {
      pollFeedIncremental({ prefetchNew: true })
    }
  }, [activeCommand, activeBashCommsFilename, pollFeedIncremental])

  // Stream active agent log and bash comms via multiplexed SSE while command is running
  useEffect(() => {
    if (!activeCommand) return
    const stream = api.connectTaskStream(taskName, {
      onLog: (chunk) => {
        if (!activeLogFilename) return
        setContents((prev) => ({
          ...prev,
          [activeLogFilename]: (prev[activeLogFilename] ?? '') + chunk,
        }))
      },
      onBash: (chunk) => {
        if (!activeBashCommsFilename) return
        setContents((prev) => ({
          ...prev,
          [activeBashCommsFilename]: (prev[activeBashCommsFilename] ?? '') + chunk,
        }))
      },
    })
    return () => {
      stream.close()
    }
  }, [taskName, activeCommand, activeLogFilename, activeBashCommsFilename])

  const handleStartCommand = async (command: string) => {
    setCommandError(null)
    setStartingCommand(command)
    try {
      await api.startTaskCommand(taskName, command)
      if (command === 'question' || command === 'plan-implement' || command === 'implement') {
        const agentCmd = command as AgentModeCommand
        setLastAgentCommand(agentCmd)
        writeLastAgentCommand(agentCmd)
      }
      await loadCommandStatus()
    } catch (e) {
      setCommandError(e instanceof Error ? e.message : String(e))
    } finally {
      setStartingCommand(null)
    }
  }

  const handleCancelCommand = async () => {
    setCommandError(null)
    try {
      await api.cancelTaskCommand(taskName)
      await loadCommandStatus()
    } catch (e) {
      setCommandError(e instanceof Error ? e.message : String(e))
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
        await pollFeedIncremental({ prefetchNew: true })
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
    hasScrolledInitialRef.current = false
    setBashHistoryBrowseIdx(null)
    setFeedCollapse(createInitialFeedCollapseState())
    setFeedReady(false)
    setError(null)
    setContents({})

    const cached = readFeedOutlineCache(taskName)
    if (cached) {
      setFeedEntries(cached.entries)
      setFeedTotal(cached.feedTotal)
      setHasOlder(cached.hasOlder)
      setOldestCursor(cached.oldestCursor)
      setFeedReady(true)
    } else {
      setFeedEntries([])
      setFeedTotal(0)
      setHasOlder(false)
      setOldestCursor(null)
    }

    void loadFeedTail()
  }, [taskName, loadFeedTail])

  useEffect(() => {
    if (!feedReady || error) return
    commentDraftLoadedRef.current = false
    bashDraftLoadedRef.current = false
    api.getTaskCommentDraft(taskName).then((text) => {
      setCommentText(text)
      lastSavedCommentRef.current = text
      commentDraftLoadedRef.current = true
      setCommentDraftStatus('saved')
    }).catch(() => { /* ignore */ })
    api.getTaskBashDraft(taskName).then((text) => {
      setShellInput(text)
      lastSavedBashRef.current = text
      bashDraftLoadedRef.current = true
      setBashDraftStatus('saved')
    }).catch(() => { /* ignore */ })
  }, [taskName, feedReady, error])

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
    if (!bashDraftLoadedRef.current) return
    if (lastSavedBashRef.current !== null && shellInput === lastSavedBashRef.current) {
      setBashDraftStatus('saved')
      return
    }
    setBashDraftStatus('unsaved')
    const t = setTimeout(() => {
      setBashDraftStatus('saving')
      api.setTaskBashDraft(taskName, shellInput).then(() => {
        lastSavedBashRef.current = shellInput
        setBashDraftStatus('saved')
      }).catch(() => {
        setBashDraftStatus('unsaved')
      })
    }, DRAFT_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [taskName, shellInput])

  useEffect(() => {
    document.title = `Dev – ${taskName}`
    return () => { document.title = DEFAULT_TAB_TITLE }
  }, [taskName])

  const bashHistoryOlder = useCallback(() => {
    const hist = bashHistoryRef.current
    if (hist.length === 0) return
    setBashHistoryBrowseIdx((prevIdx) => {
      const nextIdx = prevIdx === null ? hist.length - 1 : Math.max(0, prevIdx - 1)
      setShellInput(hist[nextIdx])
      return nextIdx
    })
  }, [])

  const bashHistoryNewer = useCallback(() => {
    const hist = bashHistoryRef.current
    setBashHistoryBrowseIdx((prevIdx) => {
      if (prevIdx === null) return null
      if (prevIdx >= hist.length - 1) {
        setShellInput('')
        return null
      }
      const nextIdx = prevIdx + 1
      setShellInput(hist[nextIdx])
      return nextIdx
    })
  }, [])

  const runShellCommand = useCallback(async () => {
    const cmd = shellInput.trim()
    if (!cmd) return
    setPostError(null)
    setCommandError(null)
    setStartingCommand('bash')
    try {
      await api.startTaskCommand(taskName, 'bash', cmd)
      await loadCommandStatus()
      setShellInput('')
      lastSavedBashRef.current = ''
      setBashDraftStatus('saved')
      setBashHistoryBrowseIdx(null)
      api.setTaskBashDraft(taskName, '').catch(() => {})
      setScrollToBottomAfterLoad(true)
    } catch (err) {
      setCommandError(err instanceof Error ? err.message : String(err))
    } finally {
      setStartingCommand(null)
    }
  }, [taskName, shellInput, loadCommandStatus])

  const handlePostComment = async (e: React.FormEvent) => {
    e.preventDefault()
    if (entryMode === 'bash') {
      await runShellCommand()
      return
    }
    const content = commentText.trim()
    if (!content) return
    setPostError(null)
    setPosting(true)
    try {
      await api.postTaskComms(taskName, content)
      setCommentText('')
      lastSavedCommentRef.current = ''
      await pollFeedIncremental({ prefetchNew: true })
      setScrollToBottomAfterLoad(true)
    } catch (err) {
      setPostError(err instanceof Error ? err.message : String(err))
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

  useEffect(() => {
    if (feedReady && feedEntries.length > 0) {
      const scrollToBottom = () => {
        programmaticScrollRef.current = true
        window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' })
        setTimeout(() => {
          programmaticScrollRef.current = false
        }, PROGRAMMATIC_SCROLL_MS)
      }
      if (scrollToBottomAfterLoad) {
        setScrollToBottomAfterLoad(false)
        setLockedToBottom(true)
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            scrollToBottom()
            setTimeout(scrollToBottom, 50)
          })
        })
      } else if (!hasScrolledInitialRef.current) {
        setLockedToBottom(true)
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            scrollToBottom()
            setTimeout(scrollToBottom, 50)
            setTimeout(scrollToBottom, 200)
          })
        })
        hasScrolledInitialRef.current = true
      }
    }
  }, [feedReady, scrollToBottomAfterLoad, feedEntries.length])

  useEffect(() => {
    const pending = pendingNavAfterLoadRef.current
    if (!pending || loadingOlder) return
    pendingNavAfterLoadRef.current = null
    const targets = buildNavTargets()
    if (targets.length === 0) return
    const oldIdx = targets.findIndex((t) => navTargetId(t) === pending.prevFirstId)
    if (oldIdx <= 0) return
    scrollToNavTargetWithLock(targets[oldIdx - 1], 'up')
  }, [feedEntries, feedCollapse, loadingOlder, buildNavTargets, scrollToNavTargetWithLock])

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

  // When locked, keep pinned to bottom as async content expands the page (e.g. initial load).
  useEffect(() => {
    if (!lockedToBottom || !feedReady || feedEntries.length === 0) return
    const scrollHeight = document.documentElement.scrollHeight
    const behind = window.scrollY + window.innerHeight < scrollHeight - SCROLL_BEHIND_THRESHOLD_PX
    if (!behind) return
    programmaticScrollRef.current = true
    window.scrollTo({ top: scrollHeight, behavior: 'instant' })
    setTimeout(() => {
      programmaticScrollRef.current = false
    }, PROGRAMMATIC_SCROLL_MS)
  }, [lockedToBottom, feedReady, feedEntries.length, contents])

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

  const activeBashCommsContent = activeBashCommsFilename ? (contents[activeBashCommsFilename] ?? '') : ''
  useEffect(() => {
    if (!activeBashCommsFilename || feedEntries.length === 0) return
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
  }, [activeBashCommsFilename, activeBashCommsContent, feedEntries.length, lockedToBottom])

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

  if (error && feedEntries.length === 0 && feedReady) {
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
        <div className="task-comms-header-title">
          <h2>{taskName}</h2>
          {workspaceInfo && (
            <p className="task-repo-meta">
              {workspaceInfo.repo_label != null ? (
                <>
                  Repository: <code>{workspaceInfo.repo_label}</code>
                </>
              ) : (
                'No repository cloned for this task.'
              )}
            </p>
          )}
        </div>
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
      {(archiveError || downloadCommsZipError || deleteCommsError || (error && feedEntries.length > 0)) && (
        <p className="inline-error">{archiveError ?? downloadCommsZipError ?? deleteCommsError ?? error}</p>
      )}
      {feedRefreshing && <p className="status">Updating feed…</p>}
      <p><Link to="/">← Back to tasks</Link></p>
      {feedEntries.length === 0 && feedReady ? (
        <p className="empty">No comms or agent logs yet for this task.</p>
      ) : feedEntries.length > 0 ? (
        <div className="comms-history">
          {hasOlder && (
            <button
              type="button"
              className="load-older-feed-btn"
              onClick={() => void loadOlderFeed()}
              disabled={loadingOlder}
            >
              {loadingOlder ? 'Loading…' : `Load older (${feedEntries.length}/${feedTotal})`}
            </button>
          )}
          {feedEntries.map((entry, i) => {
            const entryKey = `${entry.type}:${entry.id}`
            const isLast = i === feedEntries.length - 1
            const persistedAnswers =
              entry.type === 'comms' && entry.id.endsWith('-agent-question.md')
                ? persistedAnswersBySource[entry.id]
                : undefined
            return (
              <FeedEntryRow
                key={entryKey}
                entry={entry}
                contents={contents}
                loadingContentKeys={loadingContentKeys}
                isCollapsed={getEntryCollapsed(entry, entryKey)}
                entryKey={entryKey}
                toggleCollapsed={toggleCollapsed}
                loadEntryContent={loadEntryContent}
                activeLogFilename={activeLogFilename}
                isLast={isLast}
                lastEntryRef={lastCommsEntryRef}
                onDeleteComms={handleDeleteComms}
                taskName={taskName}
                onFeedRefresh={() => void loadFeedTail()}
                persistedAnswers={persistedAnswers}
              />
            )
          })}
        </div>
      ) : feedRefreshing ? (
        <p className="status">Updating feed…</p>
      ) : null}
      <div className="task-commands">
        {activeCommand ? (
          <div className="command-status-block">
            <div className="command-status-row">
              {cancelling ? (
                <p className="command-status">
                  <span className="command-spinner" aria-hidden /> Cancelling…
                </p>
              ) : pendingCommandState === 'worker_offline' ? (
                <p className="command-status">
                  <span className="command-spinner" aria-hidden /> Worker offline — command interrupted, waiting for worker
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
            {activeCommand === 'create-task' && createProgress.length > 0 && (
              <ul className="create-task-progress-list" aria-live="polite">
                {createProgress.map((msg, i) => (
                  <li key={`${i}-${msg}`}>{msg}</li>
                ))}
              </ul>
            )}
          </div>
        ) : pendingCommand ? (
          <div className="command-status-block">
            <div className="command-status-row">
              <p className="command-status">
                <span className="command-spinner" aria-hidden />{' '}
                {pendingCommandState === 'worker_offline'
                  ? 'Worker offline — command queued'
                  : 'Syncing to worker…'}
              </p>
              <button
                type="button"
                className="command-btn command-cancel-btn"
                disabled={cancelling}
                onClick={handleCancelCommand}
              >
                Cancel
              </button>
            </div>
            {pendingCommand === 'create-task' && createProgress.length > 0 && (
              <ul className="create-task-progress-list" aria-live="polite">
                {createProgress.map((msg, i) => (
                  <li key={`${i}-${msg}`}>{msg}</li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <div className="command-buttons">
            <AgentCommandSplitButton
              selectedCommand={lastAgentCommand}
              onSelectCommand={setLastAgentCommand}
              onRunCommand={(cmd) => void handleStartCommand(cmd)}
              startingCommand={startingCommand}
              disabled={!!startingCommand}
              hasRepo={workspaceInfo?.repo_label != null}
            />
            {(!workspaceInfo || workspaceInfo.repo_label != null) && (
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
            )}
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
        <div className="comms-entry-mode-row">
          <span className="comms-entry-mode-label" id="entry-mode-label">Input mode</span>
          <div className="comms-entry-mode-toggle" role="group" aria-labelledby="entry-mode-label">
            <button
              type="button"
              className={`comms-entry-mode-btn${entryMode === 'prompt' ? ' comms-entry-mode-btn-active' : ''}`}
              onClick={() => setEntryMode('prompt')}
              disabled={!!commandInFlight}
            >
              Prompt
            </button>
            <button
              type="button"
              className={`comms-entry-mode-btn${entryMode === 'bash' ? ' comms-entry-mode-btn-active' : ''}`}
              onClick={() => setEntryMode('bash')}
              disabled={!!commandInFlight}
            >
              Bash
            </button>
          </div>
        </div>
        <label className="comms-post-form-label">
          {entryMode === 'prompt' ? 'Add comment' : 'Bash (task directory)'}
        </label>
        {entryMode === 'prompt' ? (
          <div className={`draft-status draft-status-${commentDraftStatus}`} role="status" aria-live="polite">
            {commentDraftStatus === 'saved' && 'All changes saved to draft'}
            {commentDraftStatus === 'unsaved' && 'Unsaved changes'}
            {commentDraftStatus === 'saving' && 'Saving draft…'}
          </div>
        ) : (
          <div className={`draft-status draft-status-${bashDraftStatus}`} role="status" aria-live="polite">
            {bashDraftStatus === 'saved' && 'Bash draft saved'}
            {bashDraftStatus === 'unsaved' && 'Unsaved bash draft'}
            {bashDraftStatus === 'saving' && 'Saving bash draft…'}
          </div>
        )}
        {entryMode === 'prompt' ? (
          <textarea
            className="comms-post-form-textarea"
            value={commentText}
            onChange={(e) => setCommentText(e.target.value)}
            placeholder="Write a comment…"
            rows={3}
            disabled={posting || !!commandInFlight}
          />
        ) : (
          <>
            <p className="comms-shell-hint hint">Runs as <code>bash -c</code> with cwd set to the task folder. Use “Run bash” to execute; Enter inserts a newline.</p>
            <div className="comms-bash-history-row">
              <label htmlFor="bash-history-select" className="comms-bash-history-label">Recent</label>
              <select
                id="bash-history-select"
                className="comms-bash-history-select"
                aria-label="Insert a recent bash command"
                value={bashHistoryPicker}
                disabled={bashHistory.length === 0 || !!commandInFlight || !!startingCommand}
                onChange={(e) => {
                  const v = e.target.value
                  setBashHistoryPicker('')
                  if (v === '') return
                  const origIdx = parseInt(v, 10)
                  if (Number.isNaN(origIdx) || origIdx < 0 || origIdx >= bashHistory.length) return
                  const cmd = bashHistory[origIdx]
                  setShellInput(cmd)
                  setBashHistoryBrowseIdx(origIdx)
                }}
              >
                <option value="">Select…</option>
                {[...bashHistory].reverse().map((cmd, revIdx) => {
                  const origIdx = bashHistory.length - 1 - revIdx
                  const label = cmd.length > 96 ? `${cmd.slice(0, 96)}…` : cmd
                  return (
                    <option key={origIdx} value={String(origIdx)}>
                      {label}
                    </option>
                  )
                })}
              </select>
              <button
                type="button"
                className="comms-bash-history-arrow"
                aria-label="Older bash command"
                title="Older command"
                disabled={bashHistory.length === 0 || !!commandInFlight || !!startingCommand}
                onClick={bashHistoryOlder}
              >
                ↑
              </button>
              <button
                type="button"
                className="comms-bash-history-arrow"
                aria-label="Newer bash command"
                title="Newer command"
                disabled={bashHistoryBrowseIdx === null || !!commandInFlight || !!startingCommand}
                onClick={bashHistoryNewer}
              >
                ↓
              </button>
            </div>
            <textarea
              className="comms-post-form-textarea comms-post-form-textarea-terminal"
              value={shellInput}
              onChange={(e) => {
                setBashHistoryBrowseIdx(null)
                setShellInput(e.target.value)
              }}
              placeholder="$ "
              rows={4}
              disabled={!!commandInFlight || !!startingCommand}
              spellCheck={false}
              autoCapitalize="none"
              autoCorrect="off"
              autoComplete="off"
            />
          </>
        )}
        {postError && <p className="inline-error">{postError}</p>}
        <div className="form-actions">
          <button
            type="submit"
            disabled={
              entryMode === 'prompt'
                ? posting || !commentText.trim() || !!commandInFlight
                : !shellInput.trim() || !!startingCommand || !!commandInFlight
            }
          >
            {entryMode === 'prompt'
              ? (posting ? 'Posting…' : 'Post comment')
              : (startingCommand === 'bash' ? 'Running…' : 'Run bash')}
          </button>
          {entryMode === 'prompt' && (
            <button
              type="button"
              className="do-btn command-btn"
              disabled={posting || !commentText.trim() || !!startingCommand || !!commandInFlight}
              onClick={handleDoFromComment}
            >
              {startingCommand === 'do' ? 'Starting…' : 'Do'}
            </button>
          )}
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
            <path d="m17 11-5-5-5 5" />
            <path d="m17 18-5-5-5 5" />
          </svg>
        </button>
        <button
          type="button"
          className="task-comms-scroll-btn task-comms-scroll-btn-step"
          onClick={scrollOneEntryUp}
          aria-label="Scroll up one entry"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="m18 15-6-6-6 6" />
          </svg>
        </button>
        <button
          type="button"
          className="task-comms-scroll-btn task-comms-scroll-btn-step"
          onClick={scrollOneEntryDown}
          aria-label="Scroll down one entry"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="m6 9 6 6 6-6" />
          </svg>
        </button>
        <button
          type="button"
          className={`task-comms-scroll-btn task-comms-scroll-btn-bottom ${lockedToBottom ? 'task-comms-scroll-btn-locked' : ''}`}
          onClick={scrollToBottomClick}
          aria-label="Scroll to bottom"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="m7 6 5 5 5-5" />
            <path d="m7 13 5 5 5-5" />
          </svg>
        </button>
      </div>
    </section>
  )
}

function SettingsPage() {
  const [repos, setRepos] = useState<Record<string, string>>({})
  const [bots, setBots] = useState<Array<{ org: string; secret: string }>>([])
  const [environments, setEnvironments] = useState<EnvironmentInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [addName, setAddName] = useState('')
  const [addUrl, setAddUrl] = useState('')
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState<string | null>(null)
  const [deletingEnv, setDeletingEnv] = useState<string | null>(null)

  useEffect(() => {
    document.title = 'Dev – Settings'
    return () => { document.title = DEFAULT_TAB_TITLE }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [r, b, e] = await Promise.all([api.getRepos(), api.getBots(), api.getEnvironments()])
      setRepos(r)
      setBots(b.bots)
      setEnvironments(e.environments)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const saveBots = async () => {
    setSaving(true)
    setError(null)
    try {
      await api.setBots(bots)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  const handleAddRepo = async (e: React.FormEvent) => {
    e.preventDefault()
    const n = addName.trim()
    const u = addUrl.trim()
    if (!n || !u) {
      setError('Repo name and URL are required.')
      return
    }
    setAdding(true)
    setError(null)
    try {
      await api.addRepo(n, u)
      setAddName('')
      setAddUrl('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setAdding(false)
    }
  }

  const handleRemoveRepo = async (name: string) => {
    if (!confirm(`Remove "${name}" from your repo list?`)) return
    setRemoving(name)
    setError(null)
    try {
      await api.removeRepo(name)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setRemoving(null)
    }
  }

  const handleDeleteEnvironment = async (env: EnvironmentInfo) => {
    if (!confirm(`Remove environment "${env.display_name}"?`)) return
    setDeletingEnv(env.environment_id)
    setError(null)
    try {
      await api.deleteEnvironment(env.environment_id)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setDeletingEnv(null)
    }
  }

  if (loading) return <p className="hint">Loading settings…</p>

  return (
    <section className="settings-page">
      <h2>Cloud settings</h2>
      {error && <p className="inline-error settings-error" role="alert">{error}</p>}

      <div className="settings-section">
        <h3>Environments</h3>
        <p className="settings-hint">Workers register automatically when they poll the control plane.</p>
        {environments.length === 0 ? (
          <p className="hint">No environments registered yet.</p>
        ) : (
          <ul className="settings-list">
            {environments.map((env) => (
              <li key={env.environment_id} className="settings-list-row">
                <div className="settings-list-main">
                  <span className="settings-list-title">{env.display_name}</span>
                  <span className={`settings-badge ${env.online ? 'settings-badge-online' : 'settings-badge-offline'}`}>
                    {env.online ? 'online' : 'offline'}
                  </span>
                </div>
                <button
                  type="button"
                  className="settings-btn settings-btn-danger"
                  disabled={deletingEnv !== null}
                  onClick={() => handleDeleteEnvironment(env)}
                >
                  {deletingEnv === env.environment_id ? 'Removing…' : 'Remove'}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="settings-section">
        <h3>Repos</h3>
        {Object.keys(repos).length === 0 ? (
          <p className="hint">No repos configured.</p>
        ) : (
          <ul className="settings-list">
            {Object.entries(repos).map(([name, url]) => (
              <li key={name} className="settings-list-row">
                <div className="settings-list-main">
                  <span className="settings-list-title">{name}</span>
                  <span className="settings-list-sub">{url}</span>
                </div>
                <button
                  type="button"
                  className="settings-btn settings-btn-danger"
                  disabled={removing !== null}
                  onClick={() => handleRemoveRepo(name)}
                >
                  {removing === name ? 'Removing…' : 'Remove'}
                </button>
              </li>
            ))}
          </ul>
        )}
        <form className="settings-add-form" onSubmit={handleAddRepo}>
          <label className="settings-field">
            <span>Shorthand</span>
            <input value={addName} onChange={(e) => setAddName(e.target.value)} placeholder="my-repo" />
          </label>
          <label className="settings-field">
            <span>URL</span>
            <input value={addUrl} onChange={(e) => setAddUrl(e.target.value)} placeholder="https://github.com/org/repo.git" />
          </label>
          <button type="submit" className="settings-btn settings-btn-primary" disabled={adding}>
            {adding ? 'Adding…' : 'Add repo'}
          </button>
        </form>
      </div>

      <div className="settings-section">
        <h3>GitHub bots</h3>
        <p className="settings-hint">Map GitHub orgs to Secrets Manager secret names for PR actions.</p>
        {bots.map((b, i) => (
          <div key={i} className="settings-bots-row">
            <input
              className="settings-input"
              placeholder="org"
              value={b.org}
              onChange={(e) => {
                const next = [...bots]
                next[i] = { ...b, org: e.target.value }
                setBots(next)
              }}
            />
            <input
              className="settings-input"
              placeholder="secret name"
              value={b.secret}
              onChange={(e) => {
                const next = [...bots]
                next[i] = { ...b, secret: e.target.value }
                setBots(next)
              }}
            />
          </div>
        ))}
        <div className="settings-actions">
          <button type="button" className="settings-btn settings-btn-secondary" onClick={() => setBots([...bots, { org: '', secret: '' }])}>
            Add bot
          </button>
          <button type="button" className="settings-btn settings-btn-primary" onClick={saveBots} disabled={saving}>
            {saving ? 'Saving…' : 'Save bots'}
          </button>
        </div>
      </div>

      <div className="settings-section">
        <h3>Account</h3>
        <p className="settings-hint">End your cloud session on this device.</p>
        <button
          type="button"
          className="settings-btn settings-btn-danger"
          onClick={() => {
            signOut()
            window.location.href = '/'
          }}
        >
          Sign out
        </button>
      </div>
    </section>
  )
}

function CloudLoginGate({ children }: { children: React.ReactNode }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [challengeSession, setChallengeSession] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [authReady, setAuthReady] = useState(!isCloudMode())
  const [token, setToken] = useState<string | null>(() => (isCloudMode() ? null : getIdToken()))

  useEffect(() => {
    if (!isCloudMode()) return
    let cancelled = false
    void restoreCloudSession().then((ok) => {
      if (!cancelled) {
        setToken(ok ? getIdToken() : null)
        setAuthReady(true)
      }
    })
    return () => {
      cancelled = true
    }
  }, [])

  if (!isCloudMode()) return <>{children}</>
  if (!authReady) {
    return (
      <div className="cloud-login-page">
        <div className="cloud-login-card">
          <p className="cloud-login-subtitle">Restoring session…</p>
        </div>
      </div>
    )
  }
  if (token) {
    return <>{children}</>
  }

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const result = await signIn(email, password)
      if (result.type === 'new_password_required') {
        setChallengeSession(result.session)
        setNewPassword('')
        setConfirmPassword('')
        return
      }
      setToken(getIdToken())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const handleNewPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (newPassword.length < 12) {
      setError('Password must be at least 12 characters.')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    if (!challengeSession) {
      setError('Session expired. Sign in again.')
      return
    }
    setSubmitting(true)
    try {
      await completeNewPassword(challengeSession, email, newPassword)
      setToken(getIdToken())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="cloud-login-page">
      <div className="cloud-login-card">
        <div className="cloud-login-brand">
          <h1 className="cloud-login-title">Dev</h1>
          <p className="cloud-login-subtitle">Cloud task management</p>
        </div>

        {challengeSession ? (
          <form className="cloud-login-form" onSubmit={handleNewPassword}>
            <h2 className="cloud-login-heading">Set a new password</h2>
            <p className="cloud-login-hint">
              Your account requires a permanent password before you can continue.
            </p>
            {error && <p className="inline-error cloud-login-error" role="alert">{error}</p>}
            <label className="cloud-login-field">
              <span>New password</span>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
                minLength={12}
                required
              />
            </label>
            <label className="cloud-login-field">
              <span>Confirm password</span>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
                minLength={12}
                required
              />
            </label>
            <button type="submit" className="cloud-login-submit" disabled={submitting}>
              {submitting ? 'Saving…' : 'Continue'}
            </button>
            <button
              type="button"
              className="cloud-login-back"
              onClick={() => {
                setChallengeSession(null)
                setError(null)
                setNewPassword('')
                setConfirmPassword('')
              }}
            >
              Back to sign in
            </button>
          </form>
        ) : (
          <form className="cloud-login-form" onSubmit={handleLogin}>
            <h2 className="cloud-login-heading">Sign in</h2>
            <p className="cloud-login-hint">
              Use the email and password from your Cognito account.
            </p>
            {error && <p className="inline-error cloud-login-error" role="alert">{error}</p>}
            <label className="cloud-login-field">
              <span>Email</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                placeholder="you@example.com"
                required
              />
            </label>
            <label className="cloud-login-field">
              <span>Password</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <button type="submit" className="cloud-login-submit" disabled={submitting}>
              {submitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <CloudLoginGate>
        <Layout />
      </CloudLoginGate>
    </BrowserRouter>
  )
}
