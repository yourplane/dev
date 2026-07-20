import { describe, it, expect } from 'vitest'
import {
  complexityLabel,
  draftIndicatesEditing,
  findOptionByLabel,
  getPersistedAnswersForSource,
  hasAnyAnswer,
  isQuestionAnswered,
  normalizeOptions,
  normalizeQuestionIds,
  normalizeSelection,
  normalizeSelectionsRecord,
  parseAnswersMarkdown,
  submittedAnswersEqual,
  submittedAnswersSignature,
  tryParseQuestionPayload,
  userAnswersContentsKey,
} from './questionForm'

describe('questionForm', () => {
  it('parses valid question payload', () => {
    const content = JSON.stringify({
      summary: 'Hello',
      questions: [{ text: 'Pick?', options: ['A', 'B'] }],
    })
    const payload = tryParseQuestionPayload(content)
    expect(payload).not.toBeNull()
    expect(payload?.summary).toBe('Hello')
    expect(payload?.questions[0].id).toBe('q1')
    expect(payload?.questions[0].options).toEqual([
      { label: 'A' },
      { label: 'B' },
    ])
  })

  it('parses legacy intro and rationale aliases', () => {
    const content = JSON.stringify({
      intro: 'Legacy summary',
      questions: [{
        text: 'Which?',
        rationale: 'Layering matters.',
        options: ['Simple'],
      }],
    })
    const payload = tryParseQuestionPayload(content)
    expect(payload?.summary).toBe('Legacy summary')
    expect(payload?.questions[0].examples).toBe('Layering matters.')
  })

  it('parses response, examples, and multiple flags', () => {
    const content = JSON.stringify({
      summary: 'Tradeoffs',
      response: 'Prior reply.',
      questions: [{
        text: 'Which?',
        examples: 'e.g. A or B.',
        multiple: true,
        options: [
          'Simple',
          { label: 'Heavy', implications: 'New service.', complexity: 'high' },
        ],
      }],
    })
    const payload = tryParseQuestionPayload(content)
    expect(payload?.response).toBe('Prior reply.')
    expect(payload?.questions[0].examples).toBe('e.g. A or B.')
    expect(payload?.questions[0].multiple).toBe(true)
    expect(payload?.questions[0].options[1]).toEqual({
      label: 'Heavy',
      implications: 'New service.',
      complexity: 'high',
    })
  })

  it('returns null for invalid option objects', () => {
    const content = JSON.stringify({
      summary: '',
      questions: [{ text: 'Q?', options: [{ implications: 'missing label' }] }],
    })
    expect(tryParseQuestionPayload(content)).toBeNull()
  })

  it('normalizeOptions accepts strings and objects', () => {
    expect(normalizeOptions(['A', { label: 'B', complexity: 'low' }])).toEqual([
      { label: 'A' },
      { label: 'B', complexity: 'low' },
    ])
  })

  it('normalizeSelection accepts legacy strings and arrays', () => {
    expect(normalizeSelection('A')).toEqual(['A'])
    expect(normalizeSelection(['A', 'B'])).toEqual(['A', 'B'])
    expect(normalizeSelectionsRecord({ q1: 'A', q2: ['B', 'C'] })).toEqual({
      q1: ['A'],
      q2: ['B', 'C'],
    })
  })

  it('findOptionByLabel returns matching option', () => {
    const options = [{ label: 'A' }, { label: 'B', complexity: 'medium' as const }]
    expect(findOptionByLabel(options, 'B')?.complexity).toBe('medium')
  })

  it('complexityLabel maps levels to readable text', () => {
    expect(complexityLabel('high')).toBe('High complexity')
  })

  it('returns null for invalid JSON', () => {
    expect(tryParseQuestionPayload('not json')).toBeNull()
  })

  it('returns null for failed parse comms (markdown)', () => {
    expect(tryParseQuestionPayload('1. What scope?\n2. Which option?')).toBeNull()
  })

  it('hasAnyAnswer detects selections and free text', () => {
    const questions = [{ id: 'q1', text: 'Q?', options: [{ label: 'A' }] }]
    expect(hasAnyAnswer(questions, {}, {})).toBe(false)
    expect(hasAnyAnswer(questions, { q1: ['A'] }, {})).toBe(true)
    expect(hasAnyAnswer(questions, {}, { q1: 'note' })).toBe(true)
  })

  it('isQuestionAnswered allows notes-only answers', () => {
    const question = { id: 'q1', text: 'Q?', options: [{ label: 'A' }], multiple: true }
    expect(isQuestionAnswered(question, {}, { q1: 'note' })).toBe(true)
    expect(isQuestionAnswered(question, {}, {})).toBe(false)
  })

  it('normalizeQuestionIds assigns q1 q2', () => {
    const payload = normalizeQuestionIds({
      summary: '',
      questions: [{ text: 'First', options: [] }, { id: 'custom', text: 'Second', options: [] }],
    })
    expect(payload.questions[0].id).toBe('q1')
    expect(payload.questions[1].id).toBe('custom')
  })

  it('parseAnswersMarkdown reads source and single-line selections', () => {
    const md = `# Answers

Source: \`003-agent-question.md\`

## q1 — Which database?

**Selected:** Postgres

**Additional notes:**
Need pooling
`
    const parsed = parseAnswersMarkdown(md)
    expect(parsed?.source).toBe('003-agent-question.md')
    expect(parsed?.answers.selections.q1).toEqual(['Postgres'])
    expect(parsed?.answers.freeText.q1).toBe('Need pooling')
  })

  it('parseAnswersMarkdown reads bulleted multi selections', () => {
    const md = `# Answers

Source: \`004-agent-question.md\`

## q1 — Pick many?

**Selected:**
- A
- B
`
    const parsed = parseAnswersMarkdown(md)
    expect(parsed?.answers.selections.q1).toEqual(['A', 'B'])
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
    expect(answers?.selections.q1).toEqual(['B'])
  })

  it('getPersistedAnswersForSource is undefined while answers content is loading', () => {
    const feed = [{ type: 'comms', id: '004-user-answers.md' }]
    expect(getPersistedAnswersForSource('002-agent-question.md', feed, {})).toBeUndefined()
  })

  it('draftIndicatesEditing treats editing flag and in-progress answers as editable', () => {
    const questions = [{ id: 'q1', text: 'Q?', options: [{ label: 'A' }] }]
    expect(draftIndicatesEditing({ selections: {}, freeText: {}, expandedFreeText: {} }, questions)).toBe(false)
    expect(draftIndicatesEditing({ selections: {}, freeText: {}, expandedFreeText: {}, editing: true }, questions)).toBe(true)
    expect(draftIndicatesEditing({ selections: { q1: ['A'] }, freeText: {}, expandedFreeText: {} }, questions)).toBe(true)
  })

  it('userAnswersContentsKey ignores unrelated comms content changes', () => {
    const feed = [{ type: 'comms', id: '004-user-answers.md' }]
    const key1 = userAnswersContentsKey(feed, { '004-user-answers.md': 'answers' })
    const key2 = userAnswersContentsKey(feed, {
      '004-user-answers.md': 'answers',
      'agent.jsonl': 'streaming log line',
    })
    expect(key1).toBe(key2)
  })

  it('submittedAnswersSignature is stable for equal answers', () => {
    const a = { selections: { q1: ['A'] }, freeText: {} }
    const b = { selections: { q1: ['A'] }, freeText: {} }
    expect(submittedAnswersSignature(a)).toBe(submittedAnswersSignature(b))
    expect(submittedAnswersEqual(a, b)).toBe(true)
  })
})
