import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { isCloudMode } from './cloudAuth'
import { useTaskList, type InAppNotification } from './useTaskListPoll'

const FLICK_DISMISS_PX = 80
const FLICK_VELOCITY_PX_MS = 0.5
const SWIPE_START_PX = 8

function NotificationCard({
  notification,
  onDismiss,
  onOpen,
}: {
  notification: InAppNotification
  onDismiss: (id: string) => void
  onOpen: (notification: InAppNotification) => void
}) {
  const [offsetX, setOffsetX] = useState(0)
  const [dragging, setDragging] = useState(false)
  const startXRef = useRef(0)
  const startTimeRef = useRef(0)
  const offsetXRef = useRef(0)
  const draggingRef = useRef(false)

  const handleTouchStart = (e: React.TouchEvent) => {
    startXRef.current = e.touches[0]?.clientX ?? 0
    startTimeRef.current = Date.now()
    offsetXRef.current = 0
    draggingRef.current = false
    setDragging(false)
    setOffsetX(0)
  }

  const handleTouchMove = (e: React.TouchEvent) => {
    const currentX = e.touches[0]?.clientX ?? startXRef.current
    const deltaX = currentX - startXRef.current
    if (!draggingRef.current && Math.abs(deltaX) <= SWIPE_START_PX) return

    draggingRef.current = true
    setDragging(true)
    e.preventDefault()

    offsetXRef.current = deltaX
    setOffsetX(deltaX)
  }

  const handleTouchEnd = () => {
    const elapsed = Math.max(Date.now() - startTimeRef.current, 1)
    const velocity = Math.abs(offsetXRef.current) / elapsed
    const shouldDismiss = draggingRef.current && (
      Math.abs(offsetXRef.current) >= FLICK_DISMISS_PX ||
      velocity >= FLICK_VELOCITY_PX_MS
    )
    draggingRef.current = false
    setDragging(false)
    if (shouldDismiss) {
      onDismiss(notification.id)
    }
    offsetXRef.current = 0
    setOffsetX(0)
  }

  const dragOpacity = offsetX !== 0
    ? Math.max(0.35, 1 - Math.abs(offsetX) / 160)
    : undefined

  return (
    <div
      className={`task-notification-banner${dragging ? ' task-notification-banner--dragging' : ''}`}
      style={offsetX !== 0 ? { transform: `translateX(${offsetX}px)`, opacity: dragOpacity } : undefined}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
      onTouchCancel={handleTouchEnd}
    >
      <button
        type="button"
        className="task-notification-banner-main"
        onClick={() => onOpen(notification)}
      >
        {notification.title}
      </button>
      <button
        type="button"
        className="task-notification-dismiss-btn"
        aria-label="Dismiss notification"
        onClick={() => onDismiss(notification.id)}
      >
        ×
      </button>
    </div>
  )
}

export function TaskNotificationBanner() {
  const ctx = useTaskList()
  const navigate = useNavigate()
  if (!isCloudMode() || ctx.inAppNotifications.length === 0) return null

  const { inAppNotifications, dismissInAppNotification } = ctx

  const handleOpen = (notification: InAppNotification) => {
    dismissInAppNotification(notification.id)
    navigate(`/task/${encodeURIComponent(notification.taskName)}`)
  }

  const stack = (
    <div className="task-notification-stack" role="region" aria-label="Task notifications">
      <div className="task-notification-stack-inner">
        {inAppNotifications.map((notification) => (
          <NotificationCard
            key={notification.id}
            notification={notification}
            onDismiss={dismissInAppNotification}
            onOpen={handleOpen}
          />
        ))}
      </div>
    </div>
  )

  return createPortal(stack, document.body)
}
