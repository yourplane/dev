import { describe, it, expect } from 'vitest'
import { parseLogToSegments } from './logParser'

describe('parseLogToSegments', () => {
  it('drops system init only at the beginning of the log', () => {
    const raw = [
      '{"type":"system","subtype":"init","session_id":"x"}',
      '{"type":"system","subtype":"init","session_id":"y"}',
      '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Hi"}]}}',
      '{"type":"system","subtype":"init","session_id":"z"}',
    ].join('\n')
    const segments = parseLogToSegments(raw)
    expect(segments.map((s) => s.type)).toEqual(['user', 'system'])
    expect(segments[0].text).toContain('Hi')
    expect(segments[1].text).toContain('[system: init]')
  })

  it('groups tool_call events by call_id and produces one segment with structured data', () => {
    const raw = [
      '{"type":"tool_call","subtype":"started","call_id":"tool_1","tool_call":{"readToolCall":{"args":{"path":"/foo"}}}}',
      '{"type":"tool_call","subtype":"completed","call_id":"tool_1","tool_call":{"readToolCall":{"args":{"path":"/foo"},"result":{"success":{"content":"hello"}}}}}',
    ].join('\n')
    const segments = parseLogToSegments(raw)
    expect(segments).toHaveLength(1)
    expect(segments[0].type).toBe('tool_call')
    expect(segments[0].toolCall).toBeDefined()
    expect(segments[0].toolCall?.toolKey).toBe('readToolCall')
    expect(segments[0].toolCall?.humanLabel).toBe('Read file')
    expect(segments[0].toolCall?.status).toBe('completed')
    expect(segments[0].toolCall?.args).toEqual({ path: '/foo' })
    expect(segments[0].toolCall?.result).toEqual({ success: { content: 'hello' } })
  })

  it('does not duplicate assistant text when the same string appears twice in content blocks', () => {
    const raw =
      '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello"},{"type":"text","text":"Hello"}]}}'
    const segments = parseLogToSegments(raw)
    expect(segments).toHaveLength(1)
    expect(segments[0].text).toBe('Hello')
  })

  it('uses latest cumulative assistant line instead of concatenating full snapshots', () => {
    const raw = [
      '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello"}]}}',
      '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello world"}]}}',
    ].join('\n')
    const segments = parseLogToSegments(raw)
    expect(segments).toHaveLength(1)
    expect(segments[0].text).toBe('Hello world')
  })

  it('omits segments with empty or whitespace-only text', () => {
    const raw = [
      '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"\n\n"}]}}',
      '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hi"}]}}',
    ].join('\n')
    const segments = parseLogToSegments(raw)
    expect(segments).toHaveLength(1)
    expect(segments[0].text).toContain('Hi')
  })

  it('preserves order: tool calls and other segments interleaved', () => {
    const raw = [
      '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Go"}]}}',
      '{"type":"tool_call","subtype":"started","call_id":"t1","tool_call":{"readToolCall":{"args":{"path":"/a"}}}}',
      '{"type":"tool_call","subtype":"completed","call_id":"t1","tool_call":{"readToolCall":{"args":{"path":"/a"},"result":{}}}}',
      '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Done"}]}}',
    ].join('\n')
    const segments = parseLogToSegments(raw)
    expect(segments.map((s) => (s.toolCall ? `tool:${s.toolCall.humanLabel}` : `${s.type}:${s.text.slice(0, 10)}`))).toEqual([
      'user:Go',
      'tool:Read file',
      'assistant:Done',
    ])
  })

  it('uses human-readable label for known tools and formats unknown tool keys', () => {
    const raw = '{"type":"tool_call","subtype":"completed","call_id":"x","tool_call":{"customToolCall":{"args":{}}}}'
    const segments = parseLogToSegments(raw)
    expect(segments[0].toolCall?.humanLabel).toBe('Custom Tool Call')
  })

  it('recognizes updateTodosToolCall with a fixed human label', () => {
    const raw =
      '{"type":"tool_call","subtype":"completed","call_id":"td1","tool_call":{"updateTodosToolCall":{"args":{"merge":false,"todos":[{"id":"a","content":"Task","status":"TODO_STATUS_COMPLETED"}]},"result":{"success":true}}}}'
    const segments = parseLogToSegments(raw)
    expect(segments).toHaveLength(1)
    expect(segments[0].toolCall?.toolKey).toBe('updateTodosToolCall')
    expect(segments[0].toolCall?.humanLabel).toBe('Update todos')
  })

  it('accumulates partialOutput from progress/partial tool_call events for same call_id', () => {
    const raw = [
      '{"type":"tool_call","subtype":"started","call_id":"sh1","tool_call":{"shellToolCall":{"args":{"command":"echo hi"}}}}',
      '{"type":"tool_call","subtype":"progress","call_id":"sh1","tool_call":{"shellToolCall":{"result":{"output":"hi\\n"}}}}',
      '{"type":"tool_call","subtype":"progress","call_id":"sh1","tool_call":{"shellToolCall":{"result":{"output":" there"}}}}',
    ].join('\n')
    const segments = parseLogToSegments(raw)
    expect(segments).toHaveLength(1)
    expect(segments[0].toolCall?.status).toBe('started')
    // In JSON "hi\\n" is newline; joined with " there" gives "hi\n there"
    expect(segments[0].toolCall?.partialOutput).toBe('hi\n there')
  })

  it('extracts stdout/stderr from failed shell result (top-level when success is false)', () => {
    const raw = [
      '{"type":"tool_call","subtype":"started","call_id":"sh1","tool_call":{"shellToolCall":{"args":{"command":"false"}}}}',
      '{"type":"tool_call","subtype":"completed","call_id":"sh1","tool_call":{"shellToolCall":{"args":{"command":"false"},"result":{"success":false,"stdout":"out","stderr":"err","exitCode":1}}}}',
    ].join('\n')
    const segments = parseLogToSegments(raw)
    expect(segments).toHaveLength(1)
    expect(segments[0].toolCall?.status).toBe('completed')
    expect(segments[0].toolCall?.result).toEqual({
      success: false,
      stdout: 'out',
      stderr: 'err',
      exitCode: 1,
    })
    // Parser uses getOutputFromResult for partialOutput; for completed we use result in UI.
    // Verify we didn't break completed-with-success result shape
    const successRaw = [
      '{"type":"tool_call","subtype":"started","call_id":"sh2","tool_call":{"shellToolCall":{"args":{"command":"echo ok"}}}}',
      '{"type":"tool_call","subtype":"completed","call_id":"sh2","tool_call":{"shellToolCall":{"args":{},"result":{"success":{"output":"ok\\n"}}}}}',
    ].join('\n')
    const successSegments = parseLogToSegments(successRaw)
    expect(successSegments).toHaveLength(1)
    expect(successSegments[0].toolCall?.result).toEqual({ success: { output: 'ok\n' } })
  })
})
