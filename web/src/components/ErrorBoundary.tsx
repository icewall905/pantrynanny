import { Component, type ReactNode } from 'react'
import i18n from '../i18n'
import { ErrorState } from './ui'

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  componentDidCatch(error: Error) {
    console.error(error)
  }
  render() {
    if (this.state.error) {
      return (
        <div className="p-6" aria-label={i18n.t('error.title')}>
          <ErrorState error={this.state.error} onRetry={() => this.setState({ error: null })} />
        </div>
      )
    }
    return this.props.children
  }
}
