const SW_URL = '/notification-sw.js'
const SW_SCOPE = '/'

export async function registerNotificationServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!('serviceWorker' in navigator)) return null
  try {
    const registration = await navigator.serviceWorker.register(SW_URL, { scope: SW_SCOPE })
    await navigator.serviceWorker.ready
    return registration
  } catch {
    return null
  }
}

export async function showServiceWorkerNotification(
  title: string,
  taskName: string,
  clickUrl?: string,
): Promise<boolean> {
  if (!('serviceWorker' in navigator)) return false
  try {
    const registration = await navigator.serviceWorker.ready
    await registration.showNotification(title, {
      tag: `dev-task-${taskName}`,
      icon: '/icons/notification-icon-192.png',
      badge: '/icons/notification-icon-192.png',
      data: {
        taskName,
        url: clickUrl ?? `/task/${encodeURIComponent(taskName)}`,
      },
    })
    return true
  } catch {
    return false
  }
}
