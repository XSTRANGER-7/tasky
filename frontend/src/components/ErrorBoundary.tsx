import { Component, type ErrorInfo, type ReactNode } from 'react'

import { CrashCard } from './CrashCard'

interface Props {
  children: ReactNode
  /** Changing this (e.g. the route path) clears a caught error. */
  resetKey?: string
}

interface State {
  error: Error | null
}

/**
 * One per route (spec 11.4): a crash in a page keeps the shell, the nav and every other
 * page working, and shows what a bug report needs - with the request ID when an API
 * error caused it.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Page crashed', error, info.componentStack)
  }

  componentDidUpdate(prev: Props): void {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null })
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <CrashCard
        error={error}
        onRetry={() => {
          this.setState({ error: null })
        }}
      />
    )
  }
}
