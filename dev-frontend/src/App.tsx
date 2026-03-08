import { useState, useEffect, useCallback } from 'react'
import { api } from './api'
import './App.css'

type View = 'list' | 'create';

export default function App() {
  const [view, setView] = useState<View>('list')
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
    <div className="app">
      <header className="header">
        <h1 className="logo">Dev</h1>
        <nav>
          <button
            type="button"
            className={view === 'list' ? 'active' : ''}
            onClick={() => setView('list')}
          >
            Tasks
          </button>
          <button
            type="button"
            className={view === 'create' ? 'active' : ''}
            onClick={() => setView('create')}
          >
            New task
          </button>
        </nav>
      </header>
      <main className="main">
        {view === 'list' && (
          <TaskList
            tasks={tasks}
            loading={loading}
            error={error}
            onRefresh={loadTasks}
          />
        )}
        {view === 'create' && (
          <CreateTaskForm
            onCreated={() => {
              setView('list')
              loadTasks()
            }}
            onCancel={() => setView('list')}
          />
        )}
      </main>
    </div>
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
        <p>{error}</p>
        <p className="hint">Ensure dev-server is running (e.g. <code>uv run --project dev-server uvicorn dev_server.main:app --reload</code>).</p>
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
              <span className="task-name">{name}</span>
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
