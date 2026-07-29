import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { TaskListProvider, useTaskList } from './useTaskListPoll'
import { BROWSER_NOTIFICATIONS_KEY, INAPP_NOTIFICATIONS_KEY } from './taskNotifications'

vi.mock('./api', () => ({
  api: {
    getTasks: vi.fn(),
  },
}))

vi.mock('./cloudAuth', () => ({
  isCloudMode: vi.fn(() => false),
}))

function TaskListProbe() {
  const { tasks, loading } = useTaskList()
  return (
    <div>
      <p data-testid="loading">{loading ? 'loading' : 'ready'}</p>
      <ul>
        {tasks.map((task) => (
          <li key={task.name}>{task.name}</li>
        ))}
      </ul>
    </div>
  )
}

function NavigateBackHarness() {
  const navigate = useNavigate()
  return (
    <>
      <button type="button" onClick={() => navigate('/task/foo')}>Open task</button>
      <button type="button" onClick={() => navigate('/')}>Back to tasks</button>
      <TaskListProbe />
    </>
  )
}

function renderWithRouter(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <TaskListProvider>
        <Routes>
          <Route path="/" element={<NavigateBackHarness />} />
          <Route path="/task/:taskName" element={<NavigateBackHarness />} />
        </Routes>
      </TaskListProvider>
    </MemoryRouter>,
  )
}

describe('TaskListProvider refresh/loading', () => {
  beforeEach(async () => {
    localStorage.clear()
    vi.clearAllMocks()
    const { api } = await import('./api')
    vi.mocked(api.getTasks).mockResolvedValue({
      tasks: [{ name: 'foo', status: 'idle' }],
    })
    const { isCloudMode } = await import('./cloudAuth')
    vi.mocked(isCloudMode).mockReturnValue(false)
  })

  it('clears loading after getTasks even when cloud notifications are slow', async () => {
    const { isCloudMode } = await import('./cloudAuth')
    vi.mocked(isCloudMode).mockReturnValue(true)
    localStorage.setItem(BROWSER_NOTIFICATIONS_KEY, 'true')
    localStorage.setItem(INAPP_NOTIFICATIONS_KEY, 'true')

    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: {
        ready: new Promise(() => {}),
      },
    })

    const { api } = await import('./api')
    vi.mocked(api.getTasks).mockResolvedValue({
      tasks: [{ name: 'foo', status: 'running' }],
    })

    renderWithRouter('/')

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('ready')
    })
    expect(screen.getByText('foo')).toBeInTheDocument()
  })

  it('keeps cached tasks visible when navigating back from a task detail page', async () => {
    const { api } = await import('./api')
    let resolveSecondFetch: ((value: { tasks: Array<{ name: string; status: 'idle' }> }) => void) | undefined
    vi.mocked(api.getTasks)
      .mockResolvedValueOnce({ tasks: [{ name: 'foo', status: 'idle' }] })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSecondFetch = resolve
          }),
      )

    renderWithRouter('/')

    await waitFor(() => {
      expect(screen.getByText('foo')).toBeInTheDocument()
    })

    screen.getByRole('button', { name: 'Open task' }).click()
    await waitFor(() => {
      expect(screen.getByText('foo')).toBeInTheDocument()
    })

    screen.getByRole('button', { name: 'Back to tasks' }).click()

    expect(screen.getByTestId('loading')).toHaveTextContent('ready')
    expect(screen.getByText('foo')).toBeInTheDocument()
    expect(screen.queryByText('loading')).not.toBeInTheDocument()

    resolveSecondFetch?.({ tasks: [{ name: 'foo', status: 'idle' }] })
    await waitFor(() => {
      expect(vi.mocked(api.getTasks)).toHaveBeenCalledTimes(2)
    })
  })

  it('surfaces fetch errors instead of staying on Loading tasks forever', async () => {
    const { api } = await import('./api')
    vi.mocked(api.getTasks).mockRejectedValue(new Error('Request timed out after 30s'))

    renderWithRouter('/')

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('ready')
    })
  })

  it('clears loading when initial fetch completes after a silent poll superseded its generation', async () => {
    vi.useFakeTimers()
    try {
      const { isCloudMode } = await import('./cloudAuth')
      vi.mocked(isCloudMode).mockReturnValue(true)

      const { api } = await import('./api')
      let resolveInitialFetch:
        | ((value: { tasks: Array<{ name: string; status: 'idle' }> }) => void)
        | undefined
      vi.mocked(api.getTasks)
        .mockImplementationOnce(
          () =>
            new Promise((resolve) => {
              resolveInitialFetch = resolve
            }),
        )
        .mockResolvedValue({ tasks: [{ name: 'foo', status: 'idle' }] })

      renderWithRouter('/')
      expect(screen.getByTestId('loading')).toHaveTextContent('loading')

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000)
      })
      expect(vi.mocked(api.getTasks)).toHaveBeenCalledTimes(2)
      expect(screen.getByTestId('loading')).toHaveTextContent('loading')

      await act(async () => {
        resolveInitialFetch?.({ tasks: [{ name: 'foo', status: 'idle' }] })
        await Promise.resolve()
      })
      expect(screen.getByTestId('loading')).toHaveTextContent('ready')
      expect(screen.getByText('foo')).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })
})
