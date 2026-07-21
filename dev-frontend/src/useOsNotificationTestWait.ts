import { useCallback, useEffect, useRef, useState } from 'react'
import type { BrowserNotificationAttemptResult } from './taskNotifications'

export const OS_NOTIFICATION_TEST_TIMEOUT_MS = 30_000

export interface UseOsNotificationTestWaitOptions {
  attemptDelivery: () => BrowserNotificationAttemptResult
  onError: (message: string) => void
  onSuccess: (message: string) => void
}

export function useOsNotificationTestWait({
  attemptDelivery,
  onError,
  onSuccess,
}: UseOsNotificationTestWaitOptions) {
  const [waiting, setWaiting] = useState(false)
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

    const timeoutId = window.setTimeout(() => {
      setWaiting(false)
      onErrorRef.current('Timed out after 30 seconds. Switch to another tab or app within that window, then press Test OS notification again.')
    }, OS_NOTIFICATION_TEST_TIMEOUT_MS)

    const onBackground = () => {
      if (!document.hidden) return
      window.clearTimeout(timeoutId)
      setWaiting(false)
      const result = attemptDeliveryRef.current()
      if (result.delivered) {
        pendingSuccessRef.current = true
      } else {
        onErrorRef.current(result.failureReason ?? 'Could not show an OS notification on this device or browser.')
      }
    }

    document.addEventListener('visibilitychange', onBackground)
    return () => {
      window.clearTimeout(timeoutId)
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

  return { waiting, startWait, cancelWait }
}
