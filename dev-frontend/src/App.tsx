import { useState, useEffect, useCallback } from 'react'
import { BrowserRouter, Link, Routes, Route, useNavigate, useParams } from 'react-router-dom'
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
          Ensure dev-server is running from the dev repo root: <code>uv run --project dev-server uvicorn dev_server.main:app --reload</code>.
          The client uses <code>{apiBaseUrl}</code> (set via <code>VITE_DEV_SERVER_URL</code> in <code>.env</code> if needed).
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
      onCreated={() => navigate('/')}
      onCancel={() => navigate('/')}
    />
  )
}

function CreateTaskForm({
  onCreated,
  onCancel,
}: {
  onCreated: () => void
  onCancel: () => void
}) {
  const [repos, setRepos] = useState<Record<string, string>>({})
  const [reposLoading, setReposLoading] = useState(true)
  const [title, setTitle] = useState('')
  const [repo, setRepo] = useState('')
  const [repoCustom, setRepoCustom] = useState('')
  const [comment, setComment] = useState('')
  const [taskName, setTaskName] = useState('')
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
      await api.createTask({
        title: title.trim(),
        repo: repoValue.trim(),
        comment: comment.trim() || undefined,
        task_name: taskName.trim() || undefined,
      })
      onCreated()
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
          Title <span className="required">*</span>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Task title"
            required
          />
        </label>
        <label>
          Repo <span className="required">*</span>
          {reposLoading ? (
            <span className="hint">Loading shorthands…</span>
          ) : (
            <>
              <select
                value={repo}
                onChange={(e) => setRepo(e.target.value)}
              >
                <option value="">Select or use custom below</option>
                {Object.entries(repos).map(([name, url]) => (
                  <option key={name} value={name}>{name} — {url}</option>
                ))}
                <option value="__custom__">Custom URL…</option>
              </select>
              {repo === '__custom__' && (
                <input
                  type="text"
                  value={repoCustom}
                  onChange={(e) => setRepoCustom(e.target.value)}
                  placeholder="https://github.com/user/repo.git"
                  className="repo-custom"
                />
              )}
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
        <label>
          Task directory name (optional)
          <input
            type="text"
            value={taskName}
            onChange={(e) => setTaskName(e.target.value)}
            placeholder="Default: slug from title"
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

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.getTaskCommsList(taskName)
      .then((res) => {
        if (cancelled) return
        setFiles(res.files)
        return Promise.all(
          res.files.map((filename) =>
            api.getTaskCommsFile(taskName, filename).then((text) => ({ filename, text }))
          )
        )
      })
      .then((pairs) => {
        if (cancelled || !pairs) return
        const map: Record<string, string> = {}
        for (const { filename, text } of pairs) {
          map[filename] = text
        }
        setContents(map)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [taskName])

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
      <h2>Comms: {taskName}</h2>
      <p><Link to="/">← Back to tasks</Link></p>
      {files.length === 0 ? (
        <p className="empty">No comms yet for this task.</p>
      ) : (
        <div className="comms-history">
          {files.map((filename) => (
            <div key={filename} className="comms-entry">
              <div className="comms-filename">{filename}</div>
              <pre className="comms-content">{contents[filename] ?? '(loading…)'}</pre>
            </div>
          ))}
        </div>
      )}
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
