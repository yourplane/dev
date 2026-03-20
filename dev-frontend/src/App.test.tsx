import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Layout, TaskCommsPageContent } from './App'

vi.mock('./api', () => ({
  api: {
    getTasks: vi.fn(),
    getRepos: vi.fn(),
    createTask: vi.fn(),
    archiveTask: vi.fn(),
    getTaskCommsList: vi.fn(),
    getTaskFeed: vi.fn(),
    getTaskCommentDraft: vi.fn(),
    setTaskCommentDraft: vi.fn(),
    getTaskCommsFile: vi.fn(),
    getTaskLogFile: vi.fn(),
    postTaskComms: vi.fn(),
    getTaskCommandStatus: vi.fn(),
    openTaskLogStream: vi.fn(),
    startTaskCommand: vi.fn(),
    createTaskPr: vi.fn(),
    getTaskPr: vi.fn(),
  },
}))

describe('App', () => {
  beforeEach(async () => {
    vi.resetModules()
    const { api } = await import('./api')
    vi.mocked(api.getTasks).mockResolvedValue({ tasks: [] })
    vi.mocked(api.getRepos).mockResolvedValue({})
    vi.mocked(api.getTaskCommsList).mockResolvedValue({ files: [] })
    vi.mocked(api.getTaskFeed).mockResolvedValue({ entries: [] })
    vi.mocked(api.getTaskPr).mockResolvedValue({ pr_url: null })
    vi.mocked(api.getTaskCommentDraft).mockResolvedValue('')
    vi.mocked(api.setTaskCommentDraft).mockResolvedValue(undefined)
    vi.mocked(api.getTaskCommandStatus).mockResolvedValue({
      active: false,
      command: null,
      active_log_filename: null,
    })
  })

  it('renders task list without throwing', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Layout />
      </MemoryRouter>
    )
    await expect(screen.findByRole('heading', { name: 'Tasks' })).resolves.toBeInTheDocument()
  })

  it('renders task comms page without throwing (loadFeed used after definition)', async () => {
    const noop = () => {}
    const { container } = render(
      <MemoryRouter>
        <TaskCommsPageContent taskName="test-task" navigate={noop} />
      </MemoryRouter>
    )
    // Wait for effects (loadFeed, etc.) to run; TDZ would throw before this resolves
    await waitFor(() => {
      expect(container.textContent?.toLowerCase()).toMatch(/comms|loading/)
    }, { timeout: 2000 })
  })

  it('clicking Do runs do command with textarea prompt and clears textarea', async () => {
    const noop = () => {}
    const { api } = await import('./api')
    vi.mocked(api.startTaskCommand).mockResolvedValue({ command: 'do', status: 'running' })

    render(
      <MemoryRouter>
        <TaskCommsPageContent taskName="test-task" navigate={noop} />
      </MemoryRouter>
    )

    const textarea = await screen.findByPlaceholderText('Write a comment…')
    const doButton = await screen.findByRole('button', { name: 'Do' })

    fireEvent.change(textarea, { target: { value: 'DO-PROMPT' } })
    await waitFor(() => {
      expect((doButton as HTMLButtonElement).disabled).toBe(false)
    })
    fireEvent.click(doButton)

    await waitFor(() => {
      expect(vi.mocked(api.startTaskCommand)).toHaveBeenCalledWith('test-task', 'do', 'DO-PROMPT')
    })

    await waitFor(() => {
      expect((textarea as HTMLTextAreaElement).value).toBe('')
    })

    await waitFor(() => {
      expect(vi.mocked(api.setTaskCommentDraft)).toHaveBeenCalledWith('test-task', '')
    })
  })
})
