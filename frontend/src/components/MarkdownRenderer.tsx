import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'

/**
 * User-authored Markdown. rehype-sanitize strips raw HTML, scripts and javascript: URLs
 * (spec section 13), so descriptions and comments can never inject markup.
 */
export default function MarkdownRenderer({
  children,
  className = '',
}: {
  children: string
  className?: string
}) {
  return (
    <div className={`markdown ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          a: ({ href, children: text }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {text}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
