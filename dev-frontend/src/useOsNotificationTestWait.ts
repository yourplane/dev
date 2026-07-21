import { useCallback, useEffect, useRef, useState } from 'react'
import type { BrowserNotificationAttemptResult } from './taskNotifications'

export const OS_NOTIFICATION_TEST_TIMEOUT_MS = 30_000

export interface UseOsNotificationTestWaitOptions {
  attemptDelivery: () => BrowserNotificationAttemptResult | Promise<BrowserNotificationAttemptResult>
  onError: (message: string) => void
  onSuccess: (message: string) => void
}

export function useOsNotificationTestWait({
  attemptDelivery,
  onError,
  onSuccess,
}: UseOsNotificationTestWaitOptions) {
  const [waiting, setWaiting] = useState(false)
  const [secondsRemaining, setSecondsRemaining] = useState(
    Math.ceil(OS_NOTIFICATION_TEST_TIMEOUT_MS / 1000),
  )
  const pendingSuccessRef = useRef(false)
  const attemptDeliveryRef = useRef(attemptDelivery)
  const onErrorRef = useRef(onError)
  const onSuccessRef = useRef(onSuccess)
  attemptDeliveryRef.current = attemptDelivery
  onErrorRef.current = onError
  onSuccessRef.current = onSuccess

  useEffect(() => {
    const onVisibility = () => {
      if (!pendingSuccessRef.current || document.hidden) return
      pendingSuccessRef.current = false
      onSuccessRef.current('OS notification sent. If you still do not see it, check Android notification settings for Chrome and any focus/Do Not Disturb modes.')
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [])

  useEffect(() => {
    if (!waiting) return

    const totalSeconds = Math.ceil(OS_NOTIFICATION_TEST_TIMEOUT_MS / 1000)
    setSecondsRemaining(totalSeconds)

    const intervalId = window.setInterval(() => {
      setSecondsRemaining((current) => Math.max(0, current - 1))
    }, 1000)

    const timeoutId = window.setTimeout(() => {
      setWaiting(false)
      onErrorRef.current('Timed out after 30 seconds. Switch to another tab or app within that window, then press Test OS notification again.')
    }, OS_NOTIFICATION_TEST_TIMEOUT_MS)

    const handleDeliveryResult = (result: BrowserNotificationAttemptResult) => {
      if (result.delivered) {
        pendingSuccessRef.current = true
      } else {
        onErrorRef.current(result.failureReason ?? 'Could not show an OS notification on this device or browser.')
      }
    }

    const onBackground = () => {
      if (!document.hidden) return
      window.clearTimeout(timeoutId)
      window.clearInterval(intervalId)
      setWaiting(false)
      try {
        const result = attemptDeliveryRef.current()
        if (result && typeof (result as Promise<BrowserNotificationAttemptResult>).then === 'function') {
          void (result as Promise<BrowserNotificationAttemptResult>).then(handleDeliveryResult)
        } else {
          handleDeliveryResult(result as BrowserNotificationAttemptResult)
        }
      } catch {
        onErrorRef.current('Could not show an OS notification on this device or browser.')
      }
    }

    document.addEventListener('visibilitychange', onBackground)
    return () => {
      window.clearTimeout(timeoutId)
      window.clearInterval(intervalId)
      document.removeEventListener('visibilitychange', onBackground)
    }
  }, [waiting])

  const cancelWait = useCallback(() => {
    pendingSuccessRef.current = false
    setWaiting(false)
  }, [])

  const startWait = useCallback(() => {
    pendingSuccessRef.current = false
    setWaiting(true)
  }, [])

  return { waiting, secondsRemaining, startWait, cancelWait }
}
