import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AppErrorBoundary } from './AppErrorBoundary'

function BrokenChild(): null {
  throw new Error('boom')
}

describe('AppErrorBoundary', () => {
  it('shows recoverable UI when a child throws', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <AppErrorBoundary>
        <BrokenChild />
      </AppErrorBoundary>,
    )
    expect(screen.getByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument()
    expect(screen.getByText('boom')).toBeInTheDocument()
    consoleError.mockRestore()
  })
})
