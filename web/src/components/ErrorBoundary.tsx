import { Component, type ReactNode } from 'react'
import i18n from '../i18n'
import { ErrorState } from './ui'
import { isStaleChunkError, reloadForStaleChunk } from '../lib/staleChunk'

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  componentDidCatch(error: Error) {
    // A lazy page from an older build was requested after a deploy: reload into the new build.
    if (isStaleChunkError(error) && reloadForStaleChunk()) return
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
