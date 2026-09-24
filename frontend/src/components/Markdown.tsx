import { lazy, Suspense } from 'react'

// react-markdown + GFM + the sanitiser are ~150 kB: load them on first use, showing the
// raw text meanwhile so layout does not jump.
const MarkdownRenderer = lazy(() => import('./MarkdownRenderer'))

export function Markdown({ children, className = '' }: { children: string; className?: string }) {
  return (
    <Suspense
      fallback={<div className={`markdown whitespace-pre-wrap ${className}`}>{children}</div>}
    >
      <MarkdownRenderer className={className}>{children}</MarkdownRenderer>
    </Suspense>
  )
}
