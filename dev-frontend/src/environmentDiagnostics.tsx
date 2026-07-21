import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  api,
  type ControlPlaneErrorEntry,
  type EnvironmentDiagnosticsResponse,
  type EnvironmentErrorEntry,
  type TelemetryPoint,
} from './api'

const ENV_REFRESH_MS = 30_000
const CP_ERRORS_REFRESH_MS = 60_000

function metricValue(point: TelemetryPoint, key: string): number {
  const raw = point.metrics[key]
  if (typeof raw === 'number') return raw
  if (typeof raw === 'string') return Number(raw) || 0
  return 0
}

function formatBytes(value: number): string {
  if (value < 1024) return `${Math.round(value)} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString()
}

function formatOfflineSince(ts: number): string {
  return new Date(ts * 1000).toLocaleString()
}

function MetricChart({
  title,
  points,
  valueKey,
  unit = '',
  formatValue,
}: {
  title: string
  points: TelemetryPoint[]
  valueKey: string
  unit?: string
  formatValue?: (value: number) => string
}) {
  const values = points.map((p) => metricValue(p, valueKey))
  const latest = values.length ? values[values.length - 1] : 0
  const max = Math.max(...values, 1)
  const width = 280
  const height = 60
  const coords = values.map((v, i) => {
    const x = values.length <= 1 ? width / 2 : (i / (values.length - 1)) * width
    const y = height - (v / max) * (height - 4) - 2
    return `${x},${y}`
  })
  const display = formatValue ? formatValue(latest) : `${latest.toFixed(1)}${unit}`

  return (
    <div className="diag-chart">
      <div className="diag-chart-header">
        <span className="diag-chart-title">{title}</span>
        <span className="diag-chart-latest">{display}</span>
      </div>
      {values.length > 1 ? (
        <svg viewBox={`0 0 ${width} ${height}`} className="diag-chart-svg" aria-hidden="true">
          <polyline points={coords.join(' ')} fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      ) : (
        <p className="hint diag-chart-empty">Waiting for history…</p>
      )}
    </div>
  )
}

function SnapshotGrid({ metrics }: { metrics: Record<string, unknown> }) {
  const items = [
    ['CPU', `${Number(metrics.cpu_percent ?? 0).toFixed(1)}%`],
    ['Memory', `${Number(metrics.memory_percent ?? 0).toFixed(1)}%`],
    ['Storage', `${Number(metrics.storage_used_percent ?? 0).toFixed(1)}%`],
    ['Poll loop', `${Number(metrics.poll_loop_utilization ?? 0).toFixed(1)}%`],
    ['Worker threads', String(metrics.worker_threads ?? 0)],
    ['Upload backlog', formatBytes(Number(metrics.upload_backlog_bytes ?? 0))],
    ['BG sync queue', String(metrics.bg_sync_queue_depth ?? 0)],
    ['Stream upload threads', String(metrics.stream_upload_threads ?? 0)],
  ]
  return (
    <div className="diag-snapshot-grid">
      {items.map(([label, value]) => (
        <div key={label} className="diag-snapshot-item">
          <span className="diag-snapshot-label">{label}</span>
          <span className="diag-snapshot-value">{value}</span>
        </div>
      ))}
    </div>
  )
}

function ErrorLog({ errors }: { errors: EnvironmentErrorEntry[] }) {
  if (!errors.length) return <p className="hint">No errors in the retention window.</p>
  return (
    <ul className="diag-error-list">
      {errors.map((err, idx) => (
        <li key={`${err.ts}-${idx}`} className={`diag-error-item diag-error-${err.level}`}>
          <div className="diag-error-meta">
            <span>{formatTime(err.ts)}</span>
            <span>{err.category}</span>
            {err.task_name && <span>{err.task_name}</span>}
          </div>
          <div className="diag-error-message">{err.message}</div>
          {err.detail && <pre className="diag-error-detail">{err.detail}</pre>}
        </li>
      ))}
    </ul>
  )
}

function TaskSection({
  taskName,
  points,
  snapshot,
}: {
  taskName: string
  points: TelemetryPoint[]
  snapshot?: Record<string, unknown>
}) {
  const dwell = (snapshot?.phase_dwell as Record<string, number | null> | undefined) ?? {}
  return (
    <details className="diag-task-section">
      <summary className="diag-task-summary">
        <span>{taskName}</span>
        {snapshot?.active_command ? <span className="settings-badge settings-badge-online">active</span> : null}
      </summary>
      <div className="diag-task-body">
        <div className="diag-task-dwell">
          {dwell.claimed_sec != null && <span>Claimed: {dwell.claimed_sec}s</span>}
          {dwell.started_sec != null && <span>Started: {dwell.started_sec}s</span>}
          {snapshot?.sync_health === 'unhealthy' && <span className="diag-unhealthy">Sync unhealthy</span>}
        </div>
        <div className="diag-chart-grid">
          <MetricChart title="Stream backlog" points={points} valueKey="stream_backlog_bytes" formatValue={formatBytes} />
          <MetricChart title="Comms lag (epochs)" points={points} valueKey="comms_epoch_lag" />
          <MetricChart title="Log silence (s)" points={points} valueKey="log_silence_sec" unit="s" />
          <MetricChart title="Sync failures" points={points} valueKey="sync_failures" />
        </div>
      </div>
    </details>
  )
}

export function EnvironmentDiagnosticsPage() {
  const { environmentId = '' } = useParams()
  const [data, setData] = useState<EnvironmentDiagnosticsResponse | null>(null)
  const [errors, setErrors] = useState<EnvironmentErrorEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!environmentId) return
    setError(null)
    try {
      const [diag, errResp] = await Promise.all([
        api.getEnvironmentDiagnostics(environmentId),
        api.getEnvironmentErrors(environmentId),
      ])
      setData(diag)
      setErrors(errResp.errors)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [environmentId])

  useEffect(() => {
    document.title = 'Dev – Environment diagnostics'
    void load()
    const id = window.setInterval(() => { void load() }, ENV_REFRESH_MS)
    return () => {
      window.clearInterval(id)
      document.title = 'Dev – Task management'
    }
  }, [load])

  const snapshotByTask = useMemo(() => {
    const map = new Map<string, Record<string, unknown>>()
    for (const task of data?.snapshot?.task_metrics ?? []) {
      const name = String(task.task_name ?? '')
      if (name) map.set(name, task)
    }
    return map
  }, [data])

  if (loading && !data) return <p className="hint">Loading environment diagnostics…</p>
  if (error && !data) return <p className="inline-error" role="alert">{error}</p>
  if (!data) return null

  const env = data.environment
  const envMetrics = data.snapshot?.env_metrics ?? {}
  const taskNames = Object.keys(data.task_series)

  return (
    <section className="diag-page">
      <p className="diag-back">
        <Link to="/settings">← Settings</Link>
      </p>
      <div className="diag-header">
        <h2>{env.display_name}</h2>
        <span className={`settings-badge ${env.online ? 'settings-badge-online' : 'settings-badge-offline'}`}>
          {env.online ? 'online' : 'offline'}
        </span>
      </div>
      {!env.online && (
        <div className="diag-offline-banner" role="status">
          Offline since {formatOfflineSince(env.last_heartbeat)} — showing last-known metrics and errors.
        </div>
      )}
      {error && <p className="inline-error settings-error" role="alert">{error}</p>}

      <div className="settings-section">
        <h3>Latest snapshot</h3>
        {data.snapshot ? (
          <>
            <p className="settings-hint">Updated {formatTime(data.snapshot.sample_ts)}</p>
            <SnapshotGrid metrics={envMetrics} />
          </>
        ) : (
          <p className="hint">No telemetry received yet.</p>
        )}
      </div>

      <div className="settings-section">
        <h3>Environment metrics (3h)</h3>
        <div className="diag-chart-grid">
          <MetricChart title="CPU" points={data.env_series} valueKey="cpu_percent" unit="%" />
          <MetricChart title="Memory" points={data.env_series} valueKey="memory_percent" unit="%" />
          <MetricChart title="Storage" points={data.env_series} valueKey="storage_used_percent" unit="%" />
          <MetricChart title="Poll loop utilization" points={data.env_series} valueKey="poll_loop_utilization" unit="%" />
          <MetricChart title="Worker threads" points={data.env_series} valueKey="worker_threads" />
          <MetricChart title="Upload backlog" points={data.env_series} valueKey="upload_backlog_bytes" formatValue={formatBytes} />
        </div>
      </div>

      {taskNames.length > 0 && (
        <div className="settings-section">
          <h3>Tasks</h3>
          {taskNames.map((taskName) => (
            <TaskSection
              key={taskName}
              taskName={taskName}
              points={data.task_series[taskName] ?? []}
              snapshot={snapshotByTask.get(taskName)}
            />
          ))}
        </div>
      )}

      <div className="settings-section">
        <h3>Error log (3h)</h3>
        <ErrorLog errors={errors} />
      </div>
    </section>
  )
}

export function ControlPlaneErrorsPage() {
  const [entries, setEntries] = useState<ControlPlaneErrorEntry[]>([])
  const [status, setStatus] = useState<string>('Loading')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const resp = await api.getControlPlaneErrors()
      setEntries(resp.entries)
      setStatus(resp.query_status)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    document.title = 'Dev – Control plane errors'
    void load()
    const id = window.setInterval(() => { void load() }, CP_ERRORS_REFRESH_MS)
    return () => {
      window.clearInterval(id)
      document.title = 'Dev – Task management'
    }
  }, [load])

  return (
    <section className="diag-page">
      <p className="diag-back">
        <Link to="/settings">← Settings</Link>
      </p>
      <h2>Control plane errors</h2>
      <p className="settings-hint">
        CloudWatch Logs Insights — last 3 hours, ERROR and WARNING. Auto-refreshes every 60s.
        {status !== 'Complete' && status !== 'Loading' ? ` Query status: ${status}.` : ''}
      </p>
      {loading && !entries.length ? <p className="hint">Running CloudWatch query…</p> : null}
      {error && <p className="inline-error settings-error" role="alert">{error}</p>}
      {!entries.length && !loading && !error ? (
        <p className="hint">No matching log entries in the last 3 hours.</p>
      ) : (
        <ul className="diag-error-list">
          {entries.map((entry, idx) => (
            <li key={`${entry.timestamp ?? idx}-${idx}`} className="diag-error-item diag-error-error">
              <div className="diag-error-meta">
                <span>{entry.timestamp ?? 'unknown time'}</span>
                {entry.log_stream && <span>{entry.log_stream}</span>}
              </div>
              <pre className="diag-error-detail">{entry.message}</pre>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
