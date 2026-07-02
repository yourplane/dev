import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QuestionAnswerForm } from './QuestionAnswerForm'

vi.mock('./api', () => ({
  api: {
    getQuestionAnswersDraft: vi.fn(),
    setQuestionAnswersDraft: vi.fn(),
    postQuestionAnswers: vi.fn(),
  },
}))

const payload = {
  intro: 'Please answer',
  questions: [
    { id: 'q1', text: 'Which database?', options: ['Postgres', 'SQLite'] },
  ],
}

describe('QuestionAnswerForm', () => {
  beforeEach(async () => {
    const { api } = await import('./api')
    vi.mocked(api.getQuestionAnswersDraft).mockResolvedValue({
      selections: {},
      freeText: {},
      expandedFreeText: {},
    })
    vi.mocked(api.setQuestionAnswersDraft).mockResolvedValue(undefined)
    vi.mocked(api.postQuestionAnswers).mockResolvedValue({ filename: '003-user-answers.md' })
  })

  it('disables submit until an answer is provided', async () => {
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={payload}
        persistedAnswers={null}
      />,
    )
    const submit = screen.getByRole('button', { name: 'Submit answers' })
    expect(submit).toBeDisabled()
    fireEvent.click(screen.getByLabelText('Postgres'))
    await waitFor(() => expect(submit).not.toBeDisabled())
  })

  it('shows empty-questions notice without submit UI', () => {
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={{ intro: 'Done', questions: [] }}
      />,
    )
    expect(screen.getByText('No questions from the agent')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Submit answers' })).not.toBeInTheDocument()
  })

  it('locks form after submit without unlock control', async () => {
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={payload}
        persistedAnswers={null}
      />,
    )
    fireEvent.click(screen.getByLabelText('SQLite'))
    fireEvent.click(screen.getByRole('button', { name: 'Submit answers' }))
    await waitFor(() => {
      expect(screen.getByText('SQLite')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Submit answers' })).not.toBeInTheDocument()
    })
    expect(screen.queryByText('Unlock to edit')).not.toBeInTheDocument()
    const { api } = await import('./api')
    expect(api.postQuestionAnswers).toHaveBeenCalled()
  })

  it('defaults to locked summary when persisted answers exist', async () => {
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={payload}
        persistedAnswers={{ selections: { q1: 'Postgres' }, freeText: {} }}
      />,
    )
    await waitFor(() => {
      expect(screen.getByText('Postgres')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: 'Submit answers' })).not.toBeInTheDocument()
    expect(screen.queryByText('Unlock to edit')).not.toBeInTheDocument()
  })

  it('reloads draft when persisted answers are removed', async () => {
    const { api } = await import('./api')
    vi.mocked(api.getQuestionAnswersDraft).mockResolvedValue({
      selections: { q1: 'SQLite' },
      freeText: { q1: 'notes' },
      expandedFreeText: { q1: true },
    })

    const { rerender } = render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={payload}
        persistedAnswers={{ selections: { q1: 'Postgres' }, freeText: {} }}
      />,
    )

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Submit answers' })).not.toBeInTheDocument()
    })

    rerender(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={payload}
        persistedAnswers={null}
      />,
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Submit answers' })).toBeInTheDocument()
      expect(screen.getByLabelText('SQLite')).toBeChecked()
      expect(screen.getByLabelText('Additional notes')).toHaveValue('notes')
    })
  })

  it('clears radio selection but keeps additional notes', async () => {
    const { api } = await import('./api')
    vi.mocked(api.getQuestionAnswersDraft).mockResolvedValue({
      selections: { q1: 'Postgres' },
      freeText: { q1: 'keep me' },
      expandedFreeText: { q1: true },
    })

    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={payload}
        persistedAnswers={null}
      />,
    )

    await waitFor(() => {
      expect(screen.getByLabelText('Postgres')).toBeChecked()
      expect(screen.getByLabelText('Additional notes')).toHaveValue('keep me')
    })

    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }))

    await waitFor(() => {
      expect(screen.getByLabelText('Postgres')).not.toBeChecked()
      expect(screen.getByLabelText('SQLite')).not.toBeChecked()
      expect(screen.getByLabelText('Additional notes')).toHaveValue('keep me')
    })
  })
})
