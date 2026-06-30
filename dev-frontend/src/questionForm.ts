export interface QuestionItem {
  id?: string
  text: string
  options: string[]
}

export interface QuestionPayload {
  intro: string
  questions: QuestionItem[]
}

export interface QuestionAnswersDraft {
  selections: Record<string, string>
  freeText: Record<string, string>
  expandedFreeText: Record<string, boolean>
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
