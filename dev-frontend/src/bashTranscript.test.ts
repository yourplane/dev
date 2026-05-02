import { describe, it, expect } from 'vitest'
import { extractBashCommandFromTranscript, bashTranscriptShellDisplayBlocks } from './bashTranscript'

describe('extractBashCommandFromTranscript', () => {
  it('reads multi-line command between delimiters', () => {
    const transcript = `__DEV_BASH_INPUT__
echo 1
echo 2
__DEV_BASH_INPUT_END__
1
2

---
Exit code: 0
`
    expect(extractBashCommandFromTranscript(transcript)).toBe(`echo 1
echo 2`)
  })

  it('returns null until delimiter block is complete', () => {
    expect(
      extractBashCommandFromTranscript(`__DEV_BASH_INPUT__
still streaming`),
    ).toBe(null)
  })

  it('supports legacy first-line $ prompt', () => {
    expect(extractBashCommandFromTranscript('$ echo hi\nhi\n\n---\n')).toBe('echo hi')
  })
})

describe('bashTranscriptShellDisplayBlocks', () => {
  it('strips delimiter markers from shell body for display', () => {
    const text = `__DEV_BASH_INPUT__
echo x
__DEV_BASH_INPUT_END__
x

---
Exit code: 0
`
    const { shellBody, metaPart } = bashTranscriptShellDisplayBlocks(text)
    expect(shellBody.trimEnd()).toBe(`echo x
x`)
    expect(metaPart).toContain('Exit code')
  })

  it('shows legacy transcript as-is before footer', () => {
    const text = `$ echo y\ny\n\n---\nExit code: 0\n`
    const { shellBody } = bashTranscriptShellDisplayBlocks(text)
    expect(shellBody).toContain('$ echo y')
  })
})
