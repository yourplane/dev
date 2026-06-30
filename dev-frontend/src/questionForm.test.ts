import { describe, it, expect } from 'vitest'
import {
  hasAnyAnswer,
  normalizeQuestionIds,
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
})
