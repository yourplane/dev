import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Layout, TaskCommsPageContent } from './App'

vi.mock('./api', () => ({
  api: {
    getTasks: vi.fn(),
    getRepos: vi.fn(),
    createTask: vi.fn(),
    archiveTask: vi.fn(),
    getTaskCommsList: vi.fn(),
    postTaskComms: vi.fn(),
    getTaskCommsFile: vi.fn(),
    getTaskCommandStatus: vi.fn(),
    startTaskCommand: vi.fn(),
  },
}))

describe('App', () => {
  beforeEach(async () => {
    vi.resetModules()
    const { api } = await import('./api')
    vi.mocked(api.getTasks).mockResolvedValue({ tasks: [] })
    vi.mocked(api.getRepos).mockResolvedValue({})
    vi.mocked(api.getTaskCommsList).mockResolvedValue({ files: [] })
    vi.mocked(api.getTaskCommandStatus).mockResolvedValue({ active: false, command: null })
  })

  it('renders task list without throwing', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Layout />
      </MemoryRouter>
    )
    await expect(screen.findByRole('heading', { name: 'Tasks' })).resolves.toBeInTheDocument()
  })

  it('renders task comms page without throwing (loadComms used after definition)', async () => {
    const noop = () => {}
    const { container } = render(
      <MemoryRouter>
        <TaskCommsPageContent taskName="test-task" navigate={noop} />
      </MemoryRouter>
    )
    // Wait for effects (loadComms, etc.) to run; TDZ would throw before this resolves
    await waitFor(() => {
      expect(container.textContent?.toLowerCase()).toMatch(/comms|loading/)
    }, { timeout: 2000 })
  })
})
