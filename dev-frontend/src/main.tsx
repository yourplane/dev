import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { isCloudMode } from './cloudAuth'
import './index.css'
import App from './App'
import { registerNotificationServiceWorker } from './notificationServiceWorker'

if (isCloudMode()) {
  void registerNotificationServiceWorker()
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
