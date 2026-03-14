/**
 * Parse agent JSONL log into display segments (type + text).
 * Consecutive events of the same type are merged into one segment.
 */

export interface LogSegment {
  type: string
  text: string
}

function getTextFromLine(obj: Record<string, unknown>): string | null {
  const eventType = typeof obj.type === 'string' ? obj.type : ''
  switch (eventType) {
    case 'thinking': {
      const t = obj.text
      return typeof t === 'string' ? t : null
    }
    case 'assistant':
    case 'user': {
      const msg = obj.message as Record<string, unknown> | undefined
      const content = Array.isArray(msg?.content) ? msg.content : []
      const parts = content
        .filter((c): c is Record<string, unknown> => c && typeof c === 'object')
        .filter((c) => c.type === 'text' && typeof c.text === 'string')
        .map((c) => c.text as string)
      return parts.length ? parts.join('') : null
    }
    case 'tool_call': {
      const tc = obj.tool_call as Record<string, unknown> | undefined
      if (!tc || typeof tc !== 'object') return null
      const subtype = typeof obj.subtype === 'string' ? obj.subtype : ''
      const keys = Object.keys(tc)
      const name = keys[0] // e.g. readToolCall, grepToolCall
      if (!name) return subtype ? `[${subtype}]` : null
      const argObj = (tc[name] as Record<string, unknown>)?.args as Record<string, unknown> | undefined
      const argStr =
        argObj && typeof argObj === 'object'
          ? Object.entries(argObj)
              .map(([k, v]) => (v !== undefined && v !== null ? `${k}=${JSON.stringify(v)}` : k))
              .join(' ')
          : ''
      return `$ ${name} ${argStr}`.trim()
    }
    case 'system': {
      const sub = obj.subtype as string | undefined
      return sub ? `[system: ${sub}]` : '[system]'
    }
    default:
      return null
  }
}

export function parseLogToSegments(raw: string): LogSegment[] {
  const segments: LogSegment[] = []
  const lines = raw.split('\n').filter((s) => s.trim())

  for (const line of lines) {
    let obj: Record<string, unknown>
    try {
      obj = JSON.parse(line) as Record<string, unknown>
    } catch {
      continue
    }
    const eventType = typeof obj.type === 'string' ? obj.type : 'unknown'
    const text = getTextFromLine(obj)
    if (text === null || text === '') continue
    if (segments.length > 0 && segments[segments.length - 1].type === eventType) {
      segments[segments.length - 1].text += text
    } else {
      segments.push({ type: eventType, text })
    }
  }

  return segments
}
