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

  it('locks form and shows unlock after submit', async () => {
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={payload}
      />,
    )
    fireEvent.click(screen.getByLabelText('SQLite'))
    fireEvent.click(screen.getByRole('button', { name: 'Submit answers' }))
    await waitFor(() => {
      expect(screen.getByText('Unlock to edit')).toBeInTheDocument()
    })
    const { api } = await import('./api')
    expect(api.postQuestionAnswers).toHaveBeenCalled()
  })
})
