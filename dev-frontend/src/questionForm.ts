export interface QuestionItem {
  id?: string
  text: string
  options: string[]
}

export interface QuestionPayload {
  intro: string
  questions: QuestionItem[]
}

export interface SubmittedAnswers {
  selections: Record<string, string>
  freeText: Record<string, string>
}

export interface QuestionAnswersDraft {
  selections: Record<string, string>
  freeText: Record<string, string>
  expandedFreeText: Record<string, boolean>
  /** True when the user unlocked a submitted form for re-editing. */
  editing?: boolean
}

export interface ParsedAnswersMarkdown {
  source: string
  answers: SubmittedAnswers
}

export function parseAnswersMarkdown(content: string): ParsedAnswersMarkdown | null {
  const sourceMatch = content.match(/^Source:\s*`([^`]+)`/m)
  if (!sourceMatch) return null
  const source = sourceMatch[1]
  const selections: Record<string, string> = {}
  const freeText: Record<string, string> = {}
  const sections = content.split(/^## /m).slice(1)
  for (const section of sections) {
    const headerEnd = section.indexOf('\n')
    if (headerEnd < 0) continue
    const header = section.slice(0, headerEnd)
    const body = section.slice(headerEnd + 1)
    const idMatch = header.match(/^(\S+)\s*—/)
    const id = idMatch?.[1] ?? ''
    const selectedMatch = body.match(/\*\*Selected:\*\*\s*(.+)/)
    if (selectedMatch) selections[id] = selectedMatch[1].trim()
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

export function normalizeQuestionIds(payload: QuestionPayload): QuestionPayload {
  const questions = payload.questions.map((q, i) => ({
    ...q,
    id: q.id?.trim() || `q${i + 1}`,
  }))
  return { intro: payload.intro, questions }
}

export function tryParseQuestionPayload(content: string): QuestionPayload | null {
  try {
    const data = JSON.parse(content.trim()) as unknown
    if (typeof data !== 'object' || data === null) return null
    const obj = data as Record<string, unknown>
    if (typeof obj.intro !== 'string') return null
    if (!Array.isArray(obj.questions)) return null
    for (const q of obj.questions) {
      if (typeof q !== 'object' || q === null) return null
      const item = q as Record<string, unknown>
      if (typeof item.text !== 'string') return null
      if (!Array.isArray(item.options)) return null
      if (!item.options.every((o) => typeof o === 'string')) return null
    }
    return normalizeQuestionIds({
      intro: obj.intro,
      questions: obj.questions as QuestionItem[],
    })
  } catch {
    return null
  }
}

export function hasAnyAnswer(
  questions: QuestionItem[],
  selections: Record<string, string>,
  freeText: Record<string, string>,
): boolean {
  for (const q of questions) {
    const id = q.id ?? ''
    if ((selections[id] ?? '').trim()) return true
    if ((freeText[id] ?? '').trim()) return true
  }
  return false
}
