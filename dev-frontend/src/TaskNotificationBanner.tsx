import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { isCloudMode } from './cloudAuth'
import { useTaskList, type InAppNotification } from './useTaskListPoll'

const SWIPE_DISMISS_PX = 72
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
  const [offsetY, setOffsetY] = useState(0)
  const [dragging, setDragging] = useState(false)
  const startYRef = useRef(0)
  const offsetYRef = useRef(0)
  const draggingRef = useRef(false)

  const handleTouchStart = (e: React.TouchEvent) => {
    startYRef.current = e.touches[0]?.clientY ?? 0
    offsetYRef.current = 0
    draggingRef.current = false
    setDragging(false)
    setOffsetY(0)
  }

  const handleTouchMove = (e: React.TouchEvent) => {
    const currentY = e.touches[0]?.clientY ?? startYRef.current
    const deltaY = currentY - startYRef.current
    if (!draggingRef.current && deltaY <= SWIPE_START_PX) return

    draggingRef.current = true
    setDragging(true)
    e.preventDefault()

    const nextOffset = Math.max(0, deltaY)
    offsetYRef.current = nextOffset
    setOffsetY(nextOffset)
  }

  const handleTouchEnd = () => {
    const shouldDismiss = draggingRef.current && offsetYRef.current >= SWIPE_DISMISS_PX
    draggingRef.current = false
    setDragging(false)
    if (shouldDismiss) {
      onDismiss(notification.id)
    }
    offsetYRef.current = 0
    setOffsetY(0)
  }

  return (
    <div
      className={`task-notification-banner${dragging ? ' task-notification-banner--dragging' : ''}`}
      style={offsetY > 0 ? { transform: `translateY(${offsetY}px)`, opacity: Math.max(0.35, 1 - offsetY / 160) } : undefined}
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
