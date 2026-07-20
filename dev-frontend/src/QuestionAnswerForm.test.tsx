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
  summary: 'Please answer',
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
        payload={{ summary: 'Done', questions: [] }}
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
    expect(api.postQuestionAnswers).toHaveBeenCalledWith('t', {
      source: '002-agent-question.md',
      answers: [{
        id: 'q1',
        text: 'Which database?',
        selected: ['SQLite'],
        free_text: '',
      }],
    })
    expect(api.setQuestionAnswersDraft).toHaveBeenCalledWith(
      't',
      '002-agent-question.md',
      { selections: {}, freeText: {}, expandedFreeText: {} },
    )
  })

  it('defaults to locked summary when persisted answers exist and no draft', async () => {
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={payload}
        persistedAnswers={{ selections: { q1: ['Postgres'] }, freeText: {} }}
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
      selections: { q1: ['SQLite'] },
      freeText: {},
      expandedFreeText: {},
      editing: true,
    })

    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={payload}
        persistedAnswers={{ selections: { q1: ['Postgres'] }, freeText: {} }}
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
        persistedAnswers={{ selections: { q1: ['Postgres'] }, freeText: {} }}
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
        expect.objectContaining({ editing: true, selections: { q1: ['Postgres'] } }),
      )
    })
  })

  it('shows examples and implications collapsibles for enriched questions', async () => {
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={{
          summary: 'Consider tradeoffs',
          questions: [{
            id: 'q1',
            text: 'Which approach?',
            examples: 'This affects service boundaries.',
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
    expect(screen.getByText('Examples')).toBeInTheDocument()
    expect(screen.getByTitle('Low complexity')).toBeInTheDocument()
    expect(screen.getByTitle('High complexity')).toBeInTheDocument()
    expect(screen.getAllByText('Architectural Implications')).toHaveLength(1)
  })

  it('keeps examples and implications visible in locked summary', async () => {
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={{
          summary: '',
          questions: [{
            id: 'q1',
            text: 'Which approach?',
            examples: 'Boundary choice.',
            options: [{
              label: 'Microservices',
              complexity: 'high',
              implications: 'More moving parts.',
            }],
          }],
        }}
        persistedAnswers={{ selections: { q1: ['Microservices'] }, freeText: {} }}
      />,
    )
    await waitFor(() => {
      expect(screen.getByText('Examples')).toBeInTheDocument()
      expect(screen.getByTitle('High complexity')).toBeInTheDocument()
      expect(screen.getByText('Architectural Implications')).toBeInTheDocument()
    })
  })

  it('renders checkboxes for multi-choice questions', () => {
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={{
          summary: '',
          questions: [{
            id: 'q1',
            text: 'Pick many?',
            multiple: true,
            options: [{ label: 'A' }, { label: 'B' }],
          }],
        }}
        persistedAnswers={null}
      />,
    )
    expect(screen.getByLabelText('A')).toHaveAttribute('type', 'checkbox')
    expect(screen.getByLabelText('B')).toHaveAttribute('type', 'checkbox')
  })

  it('clears a selected radio with the clear button', async () => {
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={payload}
        persistedAnswers={null}
      />,
    )
    fireEvent.click(screen.getByRole('radio', { name: 'Postgres' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Clear selection' })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Submit answers' })).toBeDisabled()
    })
  })

  it('shows response always visible and summary collapsed by default', () => {
    render(
      <QuestionAnswerForm
        taskName="t"
        sourceFilename="002-agent-question.md"
        payload={{
          summary: 'Hidden summary text',
          response: 'Visible response text',
          questions: [],
        }}
      />,
    )
    expect(screen.getByText('Visible response text')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Summary' })).toBeInTheDocument()
    expect(screen.queryByText('Hidden summary text')).not.toBeInTheDocument()
  })
})
