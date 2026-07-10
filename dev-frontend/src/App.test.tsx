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
    getArchive: vi.fn(),
    unarchiveTask: vi.fn(),
    copyFromArchive: vi.fn(),
    getTaskCommsList: vi.fn(),
    getTaskFeed: vi.fn(),
    getTaskFeedDeletable: vi.fn(),
    getTaskWorkspace: vi.fn(),
    getTaskCommentDraft: vi.fn(),
    setTaskCommentDraft: vi.fn(),
    getTaskBashDraft: vi.fn(),
    setTaskBashDraft: vi.fn(),
    getQuestionAnswersDraft: vi.fn(),
    setQuestionAnswersDraft: vi.fn(),
    postQuestionAnswers: vi.fn(),
    getTaskCommsFile: vi.fn(),
    getTaskLogFile: vi.fn(),
    postTaskComms: vi.fn(),
    getTaskCommandStatus: vi.fn(),
    openTaskLogStream: vi.fn(),
    connectTaskStream: vi.fn(() => ({ close: vi.fn() })),
    startTaskCommand: vi.fn(),
    cancelTaskCommand: vi.fn(),
    createTaskPr: vi.fn(),
    getTaskPr: vi.fn(),
    pullTaskPrComments: vi.fn(),
  },
}))

describe('App', () => {
  beforeEach(async () => {
    Element.prototype.scrollIntoView = vi.fn()
    vi.resetModules()
    const { api } = await import('./api')
    vi.mocked(api.getTasks).mockResolvedValue({ tasks: [] })
    vi.mocked(api.getRepos).mockResolvedValue({})
    vi.mocked(api.getNewTaskDraft).mockResolvedValue({})
    vi.mocked(api.setNewTaskDraft).mockResolvedValue(undefined)
    vi.mocked(api.getArchive).mockResolvedValue({ entries: [], total: 0, next_offset: null })
    vi.mocked(api.unarchiveTask).mockResolvedValue({ restored_task_name: 'restored-task' })
    vi.mocked(api.copyFromArchive).mockResolvedValue({ task_name: 'copied-task', task_dir: '/tmp/copied-task' })
    vi.mocked(api.getTaskCommsList).mockResolvedValue({ files: [] })
    vi.mocked(api.getTaskFeed).mockResolvedValue({
      entries: [],
      total: 0,
      has_older: false,
      oldest_cursor: null,
    })
    vi.mocked(api.getTaskFeedDeletable).mockResolvedValue({})
    vi.mocked(api.getTaskWorkspace).mockResolvedValue({
      repo_label: 'https://github.com/acme/repo.git',
    })
    vi.mocked(api.getTaskPr).mockResolvedValue({ pr_url: null })
    vi.mocked(api.getTaskCommentDraft).mockResolvedValue('')
    vi.mocked(api.setTaskCommentDraft).mockResolvedValue(undefined)
    vi.mocked(api.getTaskBashDraft).mockResolvedValue('')
    vi.mocked(api.setTaskBashDraft).mockResolvedValue(undefined)
    vi.mocked(api.getQuestionAnswersDraft).mockResolvedValue({
      selections: {},
      freeText: {},
      expandedFreeText: {},
    })
    vi.mocked(api.setQuestionAnswersDraft).mockResolvedValue(undefined)
    vi.mocked(api.postQuestionAnswers).mockResolvedValue({ filename: '003-user-answers.md' })
    vi.mocked(api.getTaskCommandStatus).mockResolvedValue({
      active: false,
      command: null,
      active_log_filename: null,
      active_bash_comms_filename: null,
      command_error: null,
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

  it('clicking Post comment clears textarea and deletes persisted draft', async () => {
    const noop = () => {}
    const { api } = await import('./api')
    vi.mocked(api.postTaskComms).mockResolvedValue({ filename: '003-user.md' })

    render(
      <MemoryRouter>
        <TaskCommsPageContent taskName="test-task" navigate={noop} />
      </MemoryRouter>
    )

    const textarea = await screen.findByPlaceholderText('Write a comment…')
    const postButton = await screen.findByRole('button', { name: 'Post comment' })

    fireEvent.change(textarea, { target: { value: 'MY-COMMENT' } })
    await waitFor(() => {
      expect((postButton as HTMLButtonElement).disabled).toBe(false)
    })
    fireEvent.click(postButton)

    await waitFor(() => {
      expect(vi.mocked(api.postTaskComms)).toHaveBeenCalledWith('test-task', 'MY-COMMENT')
    })

    await waitFor(() => {
      expect((textarea as HTMLTextAreaElement).value).toBe('')
    })

    await waitFor(() => {
      expect(vi.mocked(api.setTaskCommentDraft)).toHaveBeenCalledWith('test-task', '')
    })
  })

  it('defaults to Question in the agent command split button', async () => {
    const noop = () => {}
    const { api } = await import('./api')
    vi.mocked(api.getTaskWorkspace).mockResolvedValue({ repo_label: null })
    localStorage.removeItem('dev_last_agent_command')

    render(
      <MemoryRouter>
        <TaskCommsPageContent taskName="test-task" navigate={noop} />
      </MemoryRouter>,
    )

    await waitFor(() => {
      const questionBtn = screen.getByRole('button', { name: 'Question' })
      expect((questionBtn as HTMLButtonElement).disabled).toBe(false)
    })
    expect(screen.queryByRole('button', { name: 'Plan' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Implement' })).toBeNull()
  })

  it('shows Implement in agent command menu when a repo is cloned', async () => {
    const noop = () => {}
    const { api } = await import('./api')
    vi.mocked(api.getTaskWorkspace).mockResolvedValue({
      repo_label: 'https://github.com/acme/repo.git',
    })
    localStorage.removeItem('dev_last_agent_command')

    render(
      <MemoryRouter>
        <TaskCommsPageContent taskName="test-task" navigate={noop} />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Question' })).toBeTruthy()
    })
    fireEvent.click(screen.getByRole('button', { name: 'Choose agent command' }))
    expect(screen.getByRole('menuitem', { name: 'Implement' })).toBeTruthy()
    expect(screen.getByRole('menuitem', { name: 'Merge from main' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Merge from main' })).toBeNull()
  })

  it('starts merge-from-main from the agent command menu', async () => {
    const noop = () => {}
    const { api } = await import('./api')
    vi.mocked(api.getTaskWorkspace).mockResolvedValue({
      repo_label: 'https://github.com/acme/repo.git',
    })
    vi.mocked(api.startTaskCommand).mockResolvedValue({ command: 'merge-from-main', status: 'running' })
    localStorage.removeItem('dev_last_agent_command')

    render(
      <MemoryRouter>
        <TaskCommsPageContent taskName="test-task" navigate={noop} />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Choose agent command' })).toBeTruthy()
    })
    fireEvent.click(screen.getByRole('button', { name: 'Choose agent command' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Merge from main' }))

    await waitFor(() => {
      expect(vi.mocked(api.startTaskCommand)).toHaveBeenCalledWith('test-task', 'merge-from-main')
    })
  })

  it('bash mode submits shell input and clears bash draft', async () => {
    const noop = () => {}
    const { api } = await import('./api')
    vi.mocked(api.startTaskCommand).mockResolvedValue({ command: 'bash', status: 'running' })

    render(
      <MemoryRouter>
        <TaskCommsPageContent taskName="test-task" navigate={noop} />
      </MemoryRouter>
    )

    await screen.findByPlaceholderText('Write a comment…')
    fireEvent.click(screen.getByRole('button', { name: 'Bash' }))

    const terminal = await screen.findByRole('textbox')
    fireEvent.change(terminal, { target: { value: 'echo OK' } })
    fireEvent.click(screen.getByRole('button', { name: 'Run bash' }))

    await waitFor(() => {
      expect(vi.mocked(api.startTaskCommand)).toHaveBeenCalledWith('test-task', 'bash', 'echo OK')
    })
    await waitFor(() => {
      expect((terminal as HTMLTextAreaElement).value).toBe('')
    })
    await waitFor(() => {
      expect(vi.mocked(api.setTaskBashDraft).mock.calls.some((c) => c[0] === 'test-task' && c[1] === '')).toBe(true)
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

  it('shows archive entries in API order and includes last modified label', async () => {
    const { api } = await import('./api')
    vi.mocked(api.getArchive).mockResolvedValue({
      entries: [
        {
          archived_name: 'same-mar-14-aaaaaa',
          task_name: 'same',
          archived_date: 'mar-14',
          archived_at: '2026-03-14T12:01:00+00:00',
          last_modified_at: '2026-03-14T12:01:30+00:00',
        },
        {
          archived_name: 'same-mar-14-bbbbbb',
          task_name: 'same',
          archived_date: 'mar-14',
          archived_at: '2026-03-14T12:00:00+00:00',
          last_modified_at: '2026-03-14T12:00:10+00:00',
        },
      ],
      total: 2,
      next_offset: null,
    })

    render(
      <MemoryRouter initialEntries={['/archive']}>
        <Layout />
      </MemoryRouter>
    )

    const taskNames = await screen.findAllByText('same')
    expect(taskNames).toHaveLength(2)
    const rows = taskNames.map((el) => el.closest('.task-row'))
    const firstModified = new Date('2026-03-14T12:01:30+00:00').toLocaleString()
    const secondModified = new Date('2026-03-14T12:00:10+00:00').toLocaleString()
    expect(rows[0]?.textContent).toContain(firstModified)
    expect(rows[1]?.textContent).toContain(secondModified)
    expect(screen.getAllByText(/Last modified/i)).toHaveLength(2)
  })

  it('loads additional archive entries when clicking Load more', async () => {
    const { api } = await import('./api')
    vi.mocked(api.getArchive)
      .mockResolvedValueOnce({
        entries: [
          {
            archived_name: 'task-one-mar-14-aaaaaa',
            task_name: 'task-one',
            archived_date: 'mar-14',
            archived_at: '2026-03-14T12:01:00+00:00',
            last_modified_at: '2026-03-14T12:01:30+00:00',
          },
        ],
        total: 2,
        next_offset: 1,
      })
      .mockResolvedValueOnce({
        entries: [
          {
            archived_name: 'task-two-mar-13-bbbbbb',
            task_name: 'task-two',
            archived_date: 'mar-13',
            archived_at: '2026-03-13T12:00:00+00:00',
            last_modified_at: '2026-03-13T12:00:10+00:00',
          },
        ],
        total: 2,
        next_offset: null,
      })

    render(
      <MemoryRouter initialEntries={['/archive']}>
        <Layout />
      </MemoryRouter>
    )

    await expect(screen.findByText('task-one')).resolves.toBeInTheDocument()
    const loadMore = await screen.findByRole('button', { name: /Load more/i })
    fireEvent.click(loadMore)

    await expect(screen.findByText('task-two')).resolves.toBeInTheDocument()
    expect(vi.mocked(api.getArchive)).toHaveBeenCalledWith({ limit: 50, offset: 0 })
    expect(vi.mocked(api.getArchive)).toHaveBeenCalledWith({ limit: 50, offset: 1 })
  })

  it('collapses non-live agent logs by default; expands only the active stream log', async () => {
    const noop = () => {}
    const { api } = await import('./api')
    const fakeStream = { close: vi.fn() }
    vi.mocked(api.connectTaskStream).mockReturnValue(fakeStream)
    vi.mocked(api.getTaskFeed).mockResolvedValue({
      entries: [
        { type: 'log', id: '001-old.jsonl', created_at: 1 },
        { type: 'log', id: '002-live.jsonl', created_at: 2 },
      ],
    })
    vi.mocked(api.getTaskCommandStatus).mockResolvedValue({
      active: true,
      command: 'implement',
      active_log_filename: '002-live.jsonl',
      active_bash_comms_filename: null,
      command_error: null,
    })

    render(
      <MemoryRouter>
        <TaskCommsPageContent taskName="test-task" navigate={noop} />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Agent log: 001-old\.jsonl$/ })).toHaveAttribute('aria-expanded', 'false')
      expect(screen.getByRole('button', { name: /Agent log: 002-live\.jsonl \(live\)/ })).toHaveAttribute(
        'aria-expanded',
        'true',
      )
    })
  })

  it('collapses all agent logs when no command is active', async () => {
    const noop = () => {}
    const { api } = await import('./api')
    vi.mocked(api.getTaskFeed).mockResolvedValue({
      entries: [
        { type: 'log', id: 'a.jsonl', created_at: 1 },
        { type: 'log', id: 'b.jsonl', created_at: 2 },
      ],
    })
    vi.mocked(api.getTaskCommandStatus).mockResolvedValue({
      active: false,
      command: null,
      active_log_filename: null,
      active_bash_comms_filename: null,
      command_error: null,
    })

    render(
      <MemoryRouter>
        <TaskCommsPageContent taskName="test-task" navigate={noop} />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Agent log: a\.jsonl/ })).toHaveAttribute('aria-expanded', 'false')
      expect(screen.getByRole('button', { name: /Agent log: b\.jsonl/ })).toHaveAttribute('aria-expanded', 'false')
    })
  })

  it('leaves comms entries expanded by default while agent logs start collapsed', async () => {
    const noop = () => {}
    const { api } = await import('./api')
    vi.mocked(api.getTaskCommsFile).mockResolvedValue('# hello')
    vi.mocked(api.getTaskFeed).mockResolvedValue({
      entries: [
        { type: 'comms', id: '001-user.md', created_at: 1, deletable: false },
        { type: 'log', id: 'agent.jsonl', created_at: 2 },
      ],
    })

    render(
      <MemoryRouter>
        <TaskCommsPageContent taskName="test-task" navigate={noop} />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '001-user.md' })).toHaveAttribute('aria-expanded', 'true')
      expect(screen.getByRole('button', { name: /Agent log: agent\.jsonl/ })).toHaveAttribute('aria-expanded', 'false')
    })
  })

  it('shows Load older when the feed outline has older pages', async () => {
    const noop = () => {}
    const { api } = await import('./api')
    vi.mocked(api.getTaskFeed).mockResolvedValue({
      entries: [{ type: 'comms', id: '051-user.md', created_at: 51, deletable: true }],
      total: 100,
      has_older: true,
      oldest_cursor: { created_at: 51, id: '051-user.md' },
    })

    render(
      <MemoryRouter>
        <TaskCommsPageContent taskName="test-task" navigate={noop} />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Load older \(1\/100\)/ })).toBeInTheDocument()
    })
  })
})
