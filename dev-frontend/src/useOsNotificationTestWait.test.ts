import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useOsNotificationTestWait, OS_NOTIFICATION_TEST_TIMEOUT_MS } from './useOsNotificationTestWait'

describe('useOsNotificationTestWait', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('times out when the tab stays visible', () => {
    const onError = vi.fn()
    const onSuccess = vi.fn()
    const { result } = renderHook(() => useOsNotificationTestWait({
      attemptDelivery: () => ({ delivered: true }),
      onError,
      onSuccess,
    }))

    act(() => {
      result.current.startWait()
    })
    expect(result.current.waiting).toBe(true)

    act(() => {
      vi.advanceTimersByTime(OS_NOTIFICATION_TEST_TIMEOUT_MS)
    })

    expect(result.current.waiting).toBe(false)
    expect(onError).toHaveBeenCalledWith(expect.stringContaining('Timed out'))
  })

  it('delivers when the tab is backgrounded and confirms on return', () => {
    const onError = vi.fn()
    const onSuccess = vi.fn()
    const attemptDelivery = vi.fn(() => ({ delivered: true }))
    const { result } = renderHook(() => useOsNotificationTestWait({
      attemptDelivery,
      onError,
      onSuccess,
    }))

    act(() => {
      result.current.startWait()
    })

    act(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, value: true })
      document.dispatchEvent(new Event('visibilitychange'))
    })

    expect(attemptDelivery).toHaveBeenCalled()
    expect(result.current.waiting).toBe(false)

    act(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, value: false })
      document.dispatchEvent(new Event('visibilitychange'))
    })

    expect(onSuccess).toHaveBeenCalledWith(expect.stringContaining('OS notification sent'))
  })

  it('cancels the wait', () => {
    const onError = vi.fn()
    const { result } = renderHook(() => useOsNotificationTestWait({
      attemptDelivery: () => ({ delivered: true }),
      onError,
      onSuccess: vi.fn(),
    }))

    act(() => {
      result.current.startWait()
      result.current.cancelWait()
    })

    act(() => {
      vi.advanceTimersByTime(OS_NOTIFICATION_TEST_TIMEOUT_MS)
    })

    expect(onError).not.toHaveBeenCalled()
    expect(result.current.waiting).toBe(false)
  })
})
