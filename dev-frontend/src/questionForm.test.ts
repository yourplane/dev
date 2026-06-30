import { describe, it, expect } from 'vitest'
import {
  draftIndicatesEditing,
  getPersistedAnswersForSource,
  hasAnyAnswer,
  normalizeQuestionIds,
  parseAnswersMarkdown,
  tryParseQuestionPayload,
} from './questionForm'

describe('questionForm', () => {
  it('parses valid question payload', () => {
    const content = JSON.stringify({
      intro: 'Hello',
      questions: [{ text: 'Pick?', options: ['A', 'B'] }],
    })
    const payload = tryParseQuestionPayload(content)
    expect(payload).not.toBeNull()
    expect(payload?.intro).toBe('Hello')
    expect(payload?.questions[0].id).toBe('q1')
  })

  it('returns null for invalid JSON', () => {
    expect(tryParseQuestionPayload('not json')).toBeNull()
  })

  it('returns null for failed parse comms (markdown)', () => {
    expect(tryParseQuestionPayload('1. What scope?\n2. Which option?')).toBeNull()
  })

  it('hasAnyAnswer detects selections and free text', () => {
    const questions = [{ id: 'q1', text: 'Q?', options: ['A'] }]
    expect(hasAnyAnswer(questions, {}, {})).toBe(false)
    expect(hasAnyAnswer(questions, { q1: 'A' }, {})).toBe(true)
    expect(hasAnyAnswer(questions, {}, { q1: 'note' })).toBe(true)
  })

  it('normalizeQuestionIds assigns q1 q2', () => {
    const payload = normalizeQuestionIds({
      intro: '',
      questions: [{ text: 'First', options: [] }, { id: 'custom', text: 'Second', options: [] }],
    })
    expect(payload.questions[0].id).toBe('q1')
    expect(payload.questions[1].id).toBe('custom')
  })

  it('parseAnswersMarkdown reads source and selections', () => {
    const md = `# Answers

Source: \`003-agent-question.md\`

## q1 — Which database?

**Selected:** Postgres

**Additional notes:**
Need pooling
`
    const parsed = parseAnswersMarkdown(md)
    expect(parsed?.source).toBe('003-agent-question.md')
    expect(parsed?.answers.selections.q1).toBe('Postgres')
    expect(parsed?.answers.freeText.q1).toBe('Need pooling')
  })

  it('getPersistedAnswersForSource returns latest matching answers', () => {
    const feed = [
      { type: 'comms', id: '004-user-answers.md' },
      { type: 'comms', id: '006-user-answers.md' },
    ]
    const contents = {
      '004-user-answers.md': 'Source: `002-agent-question.md`\n\n## q1 — Q\n\n**Selected:** A\n',
      '006-user-answers.md': 'Source: `002-agent-question.md`\n\n## q1 — Q\n\n**Selected:** B\n',
    }
    const answers = getPersistedAnswersForSource('002-agent-question.md', feed, contents)
    expect(answers?.selections.q1).toBe('B')
  })

  it('getPersistedAnswersForSource is undefined while answers content is loading', () => {
    const feed = [{ type: 'comms', id: '004-user-answers.md' }]
    expect(getPersistedAnswersForSource('002-agent-question.md', feed, {})).toBeUndefined()
  })

  it('draftIndicatesEditing treats editing flag and in-progress answers as editable', () => {
    const questions = [{ id: 'q1', text: 'Q?', options: ['A'] }]
    expect(draftIndicatesEditing({ selections: {}, freeText: {}, expandedFreeText: {} }, questions)).toBe(false)
    expect(draftIndicatesEditing({ selections: {}, freeText: {}, expandedFreeText: {}, editing: true }, questions)).toBe(true)
    expect(draftIndicatesEditing({ selections: { q1: 'A' }, freeText: {}, expandedFreeText: {} }, questions)).toBe(true)
  })
})
