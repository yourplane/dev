import { Component, type ErrorInfo, type ReactNode } from 'react'

interface AppErrorBoundaryProps {
  children: ReactNode
}

interface AppErrorBoundaryState {
  error: Error | null
}

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('App render error', error, info.componentStack)
  }

  private handleReload = () => {
    window.location.reload()
  }

  private handleTryAgain = () => {
    this.setState({ error: null })
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div className="app-error-boundary">
        <div className="app-error-boundary-card">
          <h2>Something went wrong</h2>
          <p className="app-error-boundary-message">
            Dev hit an unexpected error. You can try again or reload the page.
          </p>
          <p className="app-error-boundary-detail">{this.state.error.message}</p>
          <div className="app-error-boundary-actions">
            <button type="button" className="settings-btn settings-btn-secondary" onClick={this.handleTryAgain}>
              Try again
            </button>
            <button type="button" className="settings-btn settings-btn-primary" onClick={this.handleReload}>
              Reload page
            </button>
          </div>
        </div>
      </div>
    )
  }
}
