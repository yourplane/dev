/** Delimiter lines must stay in sync with `dev_sdk.comms.bash_comms_input_header`. */

export const BASH_COMMS_BODY_PREFIX = '__DEV_BASH_INPUT__\n'
export const BASH_COMMS_BODY_SUFFIX = '\n__DEV_BASH_INPUT_END__\n'

/** Recover the submitted shell command from a *-user-bash.md transcript (supports legacy `$ …` first line). */
export function extractBashCommandFromTranscript(transcript: string): string | null {
  const i = transcript.indexOf(BASH_COMMS_BODY_PREFIX)
  if (i !== -1) {
    const from = i + BASH_COMMS_BODY_PREFIX.length
    const j = transcript.indexOf(BASH_COMMS_BODY_SUFFIX, from)
    if (j === -1) return null
    const cmd = transcript.slice(from, j)
    return cmd.trim().length === 0 ? null : cmd
  }
  const line = transcript.split('\n')[0] ?? ''
  if (!line.startsWith('$ ')) return null
  const cmd = line.slice(2).trimEnd()
  return cmd === '' ? null : cmd
}

/**
 * Split transcript into shell display body (command + streamed output) and footer meta after `---`.
 */
export function bashTranscriptShellDisplayBlocks(text: string): {
  loading: boolean
  shellBody: string
  metaPart: string
} {
  const sep = '\n---\n'
  const loading = text === '(loading…)'
  if (loading) {
    return { loading: true, shellBody: text, metaPart: '' }
  }
  const idx = text.lastIndexOf(sep)
  const core = idx === -1 ? text : text.slice(0, idx)
  const metaPart = idx === -1 ? '' : text.slice(idx + sep.length).trimEnd()

  const si = core.indexOf(BASH_COMMS_BODY_PREFIX)
  if (si !== -1) {
    const from = si + BASH_COMMS_BODY_PREFIX.length
    const ei = core.indexOf(BASH_COMMS_BODY_SUFFIX, from)
    if (ei === -1) {
      return { loading: false, shellBody: core, metaPart }
    }
    const cmd = core.slice(from, ei)
    const out = core.slice(ei + BASH_COMMS_BODY_SUFFIX.length).replace(/^\n/, '')
    const shellBody = out === '' ? cmd : `${cmd}\n${out}`
    return { loading: false, shellBody, metaPart }
  }

  return { loading: false, shellBody: core, metaPart }
}
