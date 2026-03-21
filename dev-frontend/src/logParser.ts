/**
 * Parse agent JSONL log into display segments (type + text or structured tool call).
 * Consecutive events of the same type are merged into one segment (except tool_call).
 * Tool call events with the same call_id are grouped into one segment with structured data.
 * System init at the beginning of the log is omitted. Empty segments are omitted.
 */

export interface ToolCallInfo {
  toolKey: string
  humanLabel: string
  args: Record<string, unknown>
  result?: unknown
  status: 'started' | 'completed'
  /** Accumulated output from progress/partial events (e.g. shell streaming). */
  partialOutput?: string
}

export interface LogSegment {
  type: string
  text: string
  toolCall?: ToolCallInfo
}

const TOOL_HUMAN_LABELS: Record<string, string> = {
  readToolCall: 'Read file',
  grepToolCall: 'Search',
  globToolCall: 'List files',
  writeToolCall: 'Write file',
  search_replaceToolCall: 'Search and replace',
  editToolCall: 'Edit file',
  run_terminal_cmdToolCall: 'Run command',
  shellToolCall: 'Run command',
  list_dirToolCall: 'List directory',
  delete_fileToolCall: 'Delete file',
  edit_notebookToolCall: 'Edit notebook',
  web_searchToolCall: 'Web search',
  webSearchToolCall: 'Web search',
  mcp_taskToolCall: 'Task',
  mcp_web_fetchToolCall: 'WEB FETCH',
  mcpWebFetchToolCall: 'WEB FETCH',
  webFetchToolCall: 'WEB FETCH',
  todo_writeToolCall: 'Update todo',
  todoWriteToolCall: 'Update todo',
}

function humanLabelForTool(toolKey: string): string {
  return TOOL_HUMAN_LABELS[toolKey] ?? toolKey.replace(/([A-Z])/g, ' $1').replace(/^./, (s) => s.toUpperCase()).trim()
}

interface ParsedEvent {
  index: number
  type: string
  subtype?: string
  text: string | null
  toolCall?: {
    call_id: string
    subtype: string
    toolKey: string
    args: Record<string, unknown>
    result?: unknown
  }
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
    case 'tool_call':
      return null // we use structured toolCall instead
    case 'system': {
      const sub = obj.subtype as string | undefined
      return sub ? `[system: ${sub}]` : '[system]'
    }
    default:
      return null
  }
}

function parseToolCall(obj: Record<string, unknown>): ParsedEvent['toolCall'] | undefined {
  const tc = obj.tool_call as Record<string, unknown> | undefined
  if (!tc || typeof tc !== 'object') return undefined
  const call_id = typeof obj.call_id === 'string' ? obj.call_id : ''
  const subtype = typeof obj.subtype === 'string' ? obj.subtype : ''
  const keys = Object.keys(tc)
  const toolKey = keys[0]
  if (!toolKey) return undefined
  const payload = tc[toolKey] as Record<string, unknown> | undefined
  const args = (payload?.args as Record<string, unknown>) ?? {}
  const result = payload?.result
  return { call_id, subtype, toolKey, args, result }
}

function parseLine(line: string, index: number): ParsedEvent | null {
  let obj: Record<string, unknown>
  try {
    obj = JSON.parse(line) as Record<string, unknown>
  } catch {
    return null
  }
  const eventType = typeof obj.type === 'string' ? obj.type : 'unknown'
  if (eventType === 'tool_call') {
    const toolCall = parseToolCall(obj)
    if (!toolCall) return null
    return { index, type: 'tool_call', subtype: toolCall.subtype, text: null, toolCall }
  }
  const text = getTextFromLine(obj)
  if (text === null || text === '') return null
  return { index, type: eventType, subtype: obj.subtype as string | undefined, text }
}

export function parseLogToSegments(raw: string): LogSegment[] {
  const lines = raw.split('\n').filter((s) => s.trim())
  const events: ParsedEvent[] = []
  for (let i = 0; i < lines.length; i++) {
    const ev = parseLine(lines[i], i)
    if (ev) events.push(ev)
  }

  const segments: LogSegment[] = []
  let onlySystemInitSoFar = true
  const toolCallGroups = new Map<string, { firstIndex: number; events: ParsedEvent[] }>()

  function getOutputFromResult(result: unknown): string {
    if (result == null) return ''
    const r = result as Record<string, unknown>
    const inner = (r.success != null ? (r.success as Record<string, unknown>) : r) as Record<string, unknown>
    if (typeof inner.output === 'string') return inner.output
    if (typeof inner.combinedOutput === 'string') return inner.combinedOutput
    if (typeof inner.interleavedOutput === 'string') return inner.interleavedOutput
    const stdout = typeof inner.stdout === 'string' ? inner.stdout : ''
    const stderr = typeof inner.stderr === 'string' ? inner.stderr : ''
    return stderr ? stdout + (stdout ? '\n' : '') + stderr : stdout
  }

  function flushToolCalls(): void {
    const order = [...toolCallGroups.entries()].sort((a, b) => a[1].firstIndex - b[1].firstIndex)
    for (const [, group] of order) {
      const evs = group.events
      const completed = evs.find((e) => e.toolCall?.subtype === 'completed')
      const started = evs.find((e) => e.toolCall?.subtype === 'started') ?? evs[0]
      const tc = (completed ?? started).toolCall!
      const status = completed ? ('completed' as const) : ('started' as const)
      const args = (started.toolCall?.args ?? {}) as Record<string, unknown>
      const result = completed?.toolCall?.result
      const humanLabel = humanLabelForTool(tc.toolKey)
      const progressEvents = evs.filter((e) => e.toolCall?.subtype === 'progress' || e.toolCall?.subtype === 'partial')
      const partialOutput = progressEvents
        .map((e) => getOutputFromResult(e.toolCall?.result))
        .filter(Boolean)
        .join('')
      segments.push({
        type: 'tool_call',
        text: '',
        toolCall: { toolKey: tc.toolKey, humanLabel, args, result, status, partialOutput: partialOutput || undefined },
      })
    }
    toolCallGroups.clear()
  }

  function hasContent(seg: LogSegment): boolean {
    if (seg.toolCall) return true
    return typeof seg.text === 'string' && seg.text.trim().length > 0
  }

  for (const ev of events) {
    if (ev.type === 'system' && ev.subtype === 'init' && onlySystemInitSoFar) {
      continue
    }
    onlySystemInitSoFar = false

    if (ev.type === 'tool_call' && ev.toolCall) {
      const id = ev.toolCall.call_id
      const existing = toolCallGroups.get(id)
      if (existing) {
        existing.events.push(ev)
      } else {
        toolCallGroups.set(id, { firstIndex: ev.index, events: [ev] })
      }
      continue
    }

    flushToolCalls()

    if (ev.type === 'thinking' || ev.type === 'assistant' || ev.type === 'user' || ev.type === 'system' || ev.type === 'unknown') {
      const last = segments[segments.length - 1]
      const text = ev.text ?? ''
      if (last && last.type === ev.type && !last.toolCall) {
        last.text += text
      } else {
        const seg: LogSegment = { type: ev.type, text }
        if (hasContent(seg)) segments.push(seg)
      }
    }
  }

  flushToolCalls()

  return segments.filter(hasContent)
}
