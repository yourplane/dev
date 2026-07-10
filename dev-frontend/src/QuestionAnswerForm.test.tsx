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
    {
      id: 'q1',
      text: 'Which database?',
      options: [{ label: 'Postgres' }, { label: 'SQLite' }],
    },
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

  it('locks form and shows unlock after submit', async () => {
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
      expect(screen.getByText('Unlock to edit')).toBeInTheDocument()
    })
    const { api } = await import('./api')
    expect(api.postQuestionAnswers).toHaveBeenCalled()
    expect(api.setQuestionAnswersDraft).toHaveBeenCalledWith(
      't',
      '002-agent-question.md',
      {},
    )
  })

  it('defaults to locked summary when persisted answers exist and no draft', async () => {
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={payload}
        persistedAnswers={{ selections: { q1: 'Postgres' }, freeText: {} }}
      />,
    )
    await waitFor(() => {
      expect(screen.getByText('Unlock to edit')).toBeInTheDocument()
      expect(screen.getByText('Postgres')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: 'Submit answers' })).not.toBeInTheDocument()
  })

  it('restores editable draft over persisted answers when editing flag is set', async () => {
    const { api } = await import('./api')
    vi.mocked(api.getQuestionAnswersDraft).mockResolvedValue({
      selections: { q1: 'SQLite' },
      freeText: {},
      expandedFreeText: {},
      editing: true,
    })

    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={payload}
        persistedAnswers={{ selections: { q1: 'Postgres' }, freeText: {} }}
      />,
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Submit answers' })).toBeInTheDocument()
      expect(screen.getByLabelText('SQLite')).toBeChecked()
    })
    expect(screen.queryByText('Unlock to edit')).not.toBeInTheDocument()
  })

  it('unlock saves editing draft immediately', async () => {
    const { api } = await import('./api')
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={payload}
        persistedAnswers={{ selections: { q1: 'Postgres' }, freeText: {} }}
      />,
    )
    await waitFor(() => {
      expect(screen.getByText('Unlock to edit')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('Unlock to edit'))
    await waitFor(() => {
      expect(api.setQuestionAnswersDraft).toHaveBeenCalledWith(
        't',
        '002-agent-question.md',
        expect.objectContaining({ editing: true, selections: { q1: 'Postgres' } }),
      )
    })
  })

  it('shows rationale and implications collapsibles for enriched questions', async () => {
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={{
          intro: 'Consider tradeoffs',
          questions: [{
            id: 'q1',
            text: 'Which approach?',
            rationale: 'This affects service boundaries.',
            options: [
              { label: 'Monolith', complexity: 'low' },
              {
                label: 'Microservices',
                complexity: 'high',
                implications: 'Adds deployment and observability overhead.',
              },
            ],
          }],
        }}
        persistedAnswers={null}
      />,
    )
    expect(screen.getByText('Why am I asking this?')).toBeInTheDocument()
    expect(screen.getByTitle('Low complexity')).toBeInTheDocument()
    expect(screen.getByTitle('High complexity')).toBeInTheDocument()
    expect(screen.getAllByText('Architectural Implications')).toHaveLength(1)
  })

  it('keeps rationale and implications visible in locked summary', async () => {
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={{
          intro: '',
          questions: [{
            id: 'q1',
            text: 'Which approach?',
            rationale: 'Boundary choice.',
            options: [{
              label: 'Microservices',
              complexity: 'high',
              implications: 'More moving parts.',
            }],
          }],
        }}
        persistedAnswers={{ selections: { q1: 'Microservices' }, freeText: {} }}
      />,
    )
    await waitFor(() => {
      expect(screen.getByText('Why am I asking this?')).toBeInTheDocument()
      expect(screen.getByTitle('High complexity')).toBeInTheDocument()
      expect(screen.getByText('Architectural Implications')).toBeInTheDocument()
    })
  })
})
