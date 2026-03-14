import { useState, useEffect, useCallback } from 'react'
import { BrowserRouter, Link, Routes, Route, useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { api, apiBaseUrl } from './api'
import './App.css'

function Layout() {
  return (
    <div className="app">
      <header className="header">
        <h1 className="logo"><Link to="/">Dev</Link></h1>
        <nav>
          <Link to="/" className="nav-link">Tasks</Link>
          <Link to="/new" className="nav-link">New task</Link>
        </nav>
      </header>
      <main className="main">
        <Routes>
          <Route index element={<TaskListPage />} />
          <Route path="new" element={<CreateTaskPage />} />
          <Route path="task/:taskName" element={<TaskCommsPage />} />
        </Routes>
      </main>
    </div>
  )
}

function TaskListPage() {
  const [tasks, setTasks] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

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

  return (
    <TaskList
      tasks={tasks}
      loading={loading}
      error={error}
      onRefresh={loadTasks}
    />
  )
}

function TaskList({
  tasks,
  loading,
  error,
  onRefresh,
}: {
  tasks: string[]
  loading: boolean
  error: string | null
  onRefresh: () => void
}) {
  const [archiving, setArchiving] = useState<string | null>(null)
  const [archiveError, setArchiveError] = useState<string | null>(null)

  const handleArchive = async (taskName: string) => {
    if (!confirm(`Archive task "${taskName}"?`)) return
    setArchiveError(null)
    setArchiving(taskName)
    try {
      await api.archiveTask(taskName)
      onRefresh()
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
  return (
    <CreateTaskForm
      onCreated={(taskName) => navigate(`/task/${encodeURIComponent(taskName)}`)}
      onCancel={() => navigate('/')}
    />
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

function TaskCommsPage() {
  const { taskName } = useParams<{ taskName: string }>()
  const navigate = useNavigate()

  if (!taskName) {
    navigate('/')
    return null
  }

  const [files, setFiles] = useState<string[]>([])
  const [contents, setContents] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [commentText, setCommentText] = useState('')
  const [posting, setPosting] = useState(false)
  const [postError, setPostError] = useState<string | null>(null)
  const [activeCommand, setActiveCommand] = useState<string | null>(null)
  const [commandError, setCommandError] = useState<string | null>(null)
  const [startingCommand, setStartingCommand] = useState<string | null>(null)
  const [archiving, setArchiving] = useState(false)
  const [archiveError, setArchiveError] = useState<string | null>(null)

  const handleArchive = async () => {
    if (!confirm(`Archive task "${taskName}"?`)) return
    setArchiveError(null)
    setArchiving(true)
    try {
      await api.archiveTask(taskName)
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
    } catch {
      // ignore; task might not exist yet
    }
  }, [taskName])

  useEffect(() => {
    loadCommandStatus()
  }, [loadCommandStatus])

  useEffect(() => {
    const interval = setInterval(loadCommandStatus, 3000)
    return () => clearInterval(interval)
  }, [loadCommandStatus])

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

  const loadComms = useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const res = await api.getTaskCommsList(taskName)
      setFiles(res.files)
      const pairs = await Promise.all(
        res.files.map((filename) =>
          api.getTaskCommsFile(taskName, filename).then((text) => ({ filename, text }))
        )
      )
      const map: Record<string, string> = {}
      for (const { filename, text } of pairs) {
        map[filename] = text
      }
      setContents(map)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [taskName])

  useEffect(() => {
    loadComms()
  }, [loadComms])

  const handlePostComment = async (e: React.FormEvent) => {
    e.preventDefault()
    const content = commentText.trim()
    if (!content) return
    setPostError(null)
    setPosting(true)
    try {
      await api.postTaskComms(taskName, content)
      setCommentText('')
      await loadComms()
    } catch (e) {
      setPostError(e instanceof Error ? e.message : String(e))
    } finally {
      setPosting(false)
    }
  }

  if (loading) return <p className="status">Loading comms…</p>
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
        <h2>Comms: {taskName}</h2>
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
      {files.length === 0 ? (
        <p className="empty">No comms yet for this task.</p>
      ) : (
        <div className="comms-history">
          {files.map((filename) => (
            <div key={filename} className="comms-entry">
              <div className="comms-filename">{filename}</div>
              <div className="comms-content">
                <ReactMarkdown>{contents[filename] ?? '(loading…)'}</ReactMarkdown>
              </div>
            </div>
          ))}
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
          </div>
        )}
        {commandError && <p className="inline-error">{commandError}</p>}
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
