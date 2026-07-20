export type ComplexityLevel = 'low' | 'medium' | 'high'

export interface QuestionOption {
  label: string
  implications?: string
  complexity?: ComplexityLevel
}

export interface QuestionItem {
  id?: string
  text: string
  examples?: string
  multiple?: boolean
  options: QuestionOption[]
}

export interface QuestionPayload {
  summary: string
  response?: string
  questions: QuestionItem[]
}

export interface SubmittedAnswers {
  selections: Record<string, string[]>
  freeText: Record<string, string>
}

export interface QuestionAnswersDraft {
  selections: Record<string, string[]>
  freeText: Record<string, string>
  expandedFreeText: Record<string, boolean>
  /** True when the user unlocked a submitted form for re-editing. */
  editing?: boolean
}

export interface ParsedAnswersMarkdown {
  source: string
  answers: SubmittedAnswers
}

export function normalizeSelection(value: string | string[] | undefined): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => item.trim()).filter(Boolean)
  }
  if (typeof value === 'string' && value.trim()) {
    return [value.trim()]
  }
  return []
}

export function normalizeSelectionsRecord(
  raw: Record<string, string | string[]> | undefined,
): Record<string, string[]> {
  const selections: Record<string, string[]> = {}
  for (const [id, value] of Object.entries(raw ?? {})) {
    selections[id] = normalizeSelection(value)
  }
  return selections
}

export function normalizeOptions(raw: unknown[]): QuestionOption[] {
  const options: QuestionOption[] = []
  for (const item of raw) {
    if (typeof item === 'string') {
      options.push({ label: item })
      continue
    }
    if (typeof item !== 'object' || item === null) continue
    const obj = item as Record<string, unknown>
    if (typeof obj.label !== 'string') continue
    const option: QuestionOption = { label: obj.label }
    if (typeof obj.implications === 'string' && obj.implications.trim()) {
      option.implications = obj.implications
    }
    if (obj.complexity === 'low' || obj.complexity === 'medium' || obj.complexity === 'high') {
      option.complexity = obj.complexity
    }
    options.push(option)
  }
  return options
}

export function findOptionByLabel(
  options: QuestionOption[],
  label: string,
): QuestionOption | undefined {
  return options.find((o) => o.label === label)
}

function parseSelectedSection(body: string): string[] {
  const match = body.match(/\*\*Selected:\*\*\s*([\s\S]*?)(?=\n\*\*Additional notes:\*\*|\n## |\s*$)/)
  if (!match) return []
  const content = match[1].trim()
  if (!content) return []
  const lines = content.split('\n').map((line) => line.trim()).filter(Boolean)
  if (lines.length === 1 && !lines[0].startsWith('- ')) {
    return [lines[0]]
  }
  return lines
    .map((line) => (line.startsWith('- ') ? line.slice(2).trim() : line))
    .filter(Boolean)
}

export function parseAnswersMarkdown(content: string): ParsedAnswersMarkdown | null {
  const sourceMatch = content.match(/^Source:\s*`([^`]+)`/m)
  if (!sourceMatch) return null
  const source = sourceMatch[1]
  const selections: Record<string, string[]> = {}
  const freeText: Record<string, string> = {}
  const sections = content.split(/^## /m).slice(1)
  for (const section of sections) {
    const headerEnd = section.indexOf('\n')
    if (headerEnd < 0) continue
    const header = section.slice(0, headerEnd)
    const body = section.slice(headerEnd + 1)
    const idMatch = header.match(/^(\S+)\s*—/)
    const id = idMatch?.[1] ?? ''
    const selectedItems = parseSelectedSection(body)
    if (selectedItems.length > 0) selections[id] = selectedItems
    const notesMatch = body.match(/\*\*Additional notes:\*\*\s*\n([\s\S]*?)(?=\n## |\s*$)/)
    if (notesMatch) freeText[id] = notesMatch[1].trim()
  }
  return { source, answers: { selections, freeText } }
}

export function draftIndicatesEditing(
  draft: QuestionAnswersDraft,
  questions: QuestionItem[] = [],
): boolean {
  if (draft.editing) return true
  return hasAnyAnswer(questions, draft.selections ?? {}, draft.freeText ?? {})
}

export function getPersistedAnswersForSource(
  sourceFilename: string,
  feedEntries: Array<{ type: string; id: string }>,
  contents: Record<string, string>,
): SubmittedAnswers | null | undefined {
  let latest: SubmittedAnswers | null = null
  for (const entry of feedEntries) {
    if (entry.type !== 'comms' || !entry.id.endsWith('-user-answers.md')) continue
    const content = contents[entry.id]
    if (content === undefined) return undefined
    if (!content || content === '(loading…)') continue
    const parsed = parseAnswersMarkdown(content)
    if (!parsed || parsed.source !== sourceFilename) continue
    latest = parsed.answers
  }
  return latest
}

/** Stable fingerprint of user-answers comms content for memoization. */
export function userAnswersContentsKey(
  feedEntries: Array<{ type: string; id: string }>,
  contents: Record<string, string>,
): string {
  const parts: string[] = []
  for (const entry of feedEntries) {
    if (entry.type !== 'comms' || !entry.id.endsWith('-user-answers.md')) continue
    parts.push(`${entry.id}\0${contents[entry.id] ?? '\x01missing'}`)
  }
  return parts.join('\n')
}

export function submittedAnswersSignature(
  answers: SubmittedAnswers | null | undefined,
): string {
  if (answers === undefined) return '\x00loading'
  if (answers === null) return '\x00none'
  return JSON.stringify(answers)
}

export function submittedAnswersEqual(
  a: SubmittedAnswers | null,
  b: SubmittedAnswers | null,
): boolean {
  return submittedAnswersSignature(a) === submittedAnswersSignature(b)
}

export function normalizeQuestionIds(payload: QuestionPayload): QuestionPayload {
  const questions = payload.questions.map((q, i) => ({
    ...q,
    id: q.id?.trim() || `q${i + 1}`,
  }))
  return { summary: payload.summary, response: payload.response, questions }
}

export function tryParseQuestionPayload(content: string): QuestionPayload | null {
  try {
    const data = JSON.parse(content.trim()) as unknown
    if (typeof data !== 'object' || data === null) return null
    const obj = data as Record<string, unknown>
    const summaryRaw = obj.summary ?? obj.intro
    if (typeof summaryRaw !== 'string') return null
    if (!Array.isArray(obj.questions)) return null
    const questions: QuestionItem[] = []
    for (const q of obj.questions) {
      if (typeof q !== 'object' || q === null) return null
      const item = q as Record<string, unknown>
      if (typeof item.text !== 'string') return null
      if (!Array.isArray(item.options)) return null
      const options = normalizeOptions(item.options)
      if (options.length !== item.options.length) return null
      const question: QuestionItem = {
        text: item.text,
        options,
      }
      if (typeof item.id === 'string' && item.id.trim()) {
        question.id = item.id.trim()
      }
      const examplesRaw = item.examples ?? item.rationale
      if (typeof examplesRaw === 'string' && examplesRaw.trim()) {
        question.examples = examplesRaw
      }
      if (item.multiple === true) {
        question.multiple = true
      }
      questions.push(question)
    }
    const payload: QuestionPayload = {
      summary: summaryRaw,
      questions,
    }
    if (typeof obj.response === 'string' && obj.response.trim()) {
      payload.response = obj.response
    }
    return normalizeQuestionIds(payload)
  } catch {
    return null
  }
}

export function isQuestionAnswered(
  question: QuestionItem,
  selections: Record<string, string[]>,
  freeText: Record<string, string>,
): boolean {
  const id = question.id ?? ''
  if ((freeText[id] ?? '').trim()) return true
  return (selections[id] ?? []).length > 0
}

export function hasAnyAnswer(
  questions: QuestionItem[],
  selections: Record<string, string[]>,
  freeText: Record<string, string>,
): boolean {
  return questions.some((q) => isQuestionAnswered(q, selections, freeText))
}

export function complexityLabel(level: ComplexityLevel): string {
  switch (level) {
    case 'low':
      return 'Low complexity'
    case 'medium':
      return 'Medium complexity'
    case 'high':
      return 'High complexity'
  }
}
