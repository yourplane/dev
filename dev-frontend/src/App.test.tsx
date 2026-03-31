import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Layout, TaskCommsPageContent } from './App'

vi.mock('./api', () => ({
  api: {
    getTasks: vi.fn(),
    getRepos: vi.fn(),
    getNewTaskDraft: vi.fn(),
    setNewTaskDraft: vi.fn(),
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
    pullTaskPrComments: vi.fn(),
  },
}))

describe('App', () => {
  beforeEach(async () => {
    vi.resetModules()
    const { api } = await import('./api')
    vi.mocked(api.getTasks).mockResolvedValue({ tasks: [] })
    vi.mocked(api.getRepos).mockResolvedValue({})
    vi.mocked(api.getNewTaskDraft).mockResolvedValue({})
    vi.mocked(api.setNewTaskDraft).mockResolvedValue(undefined)
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

  it('shows Pull Comments and triggers pull when PR exists', async () => {
    const noop = () => {}
    const { api } = await import('./api')
    vi.mocked(api.getTaskPr).mockResolvedValue({ pr_url: 'https://github.com/acme/repo/pull/12' })
    vi.mocked(api.pullTaskPrComments).mockResolvedValue({
      pr_url: 'https://github.com/acme/repo/pull/12',
      new_comments_count: 2,
      comms_filename: '005-agent-pr-comments.md',
    })

    render(
      <MemoryRouter>
        <TaskCommsPageContent taskName="test-task" navigate={noop} />
      </MemoryRouter>
    )

    const pullBtn = await screen.findByRole('button', { name: 'Pull Comments' })
    fireEvent.click(pullBtn)

    await waitFor(() => {
      expect(vi.mocked(api.pullTaskPrComments)).toHaveBeenCalledWith('test-task')
    })
    await expect(screen.findByText('Pulled 2 new PR comments.')).resolves.toBeInTheDocument()
  })

  it('shows spinner status from createTask progress callback', async () => {
    const { api } = await import('./api')
    vi.mocked(api.getRepos).mockResolvedValue({ desk: 'https://github.com/acme/repo.git' })
    // Leave the request pending so navigation does not unmount the form before we assert.
    vi.mocked(api.createTask).mockImplementation((_body, onProgress) => {
      onProgress?.('Comms directory ready.')
      return new Promise(() => {})
    })

    render(
      <MemoryRouter initialEntries={['/new']}>
        <Layout />
      </MemoryRouter>
    )

    const titleInput = await screen.findByPlaceholderText('Task title')
    fireEvent.change(titleInput, { target: { value: 'my task' } })
    fireEvent.click(await screen.findByRole('radio', { name: /desk/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }))

    await expect(screen.findByText('Comms directory ready.')).resolves.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Creating…' })).toBeDisabled()
  })
})
