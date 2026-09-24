/** A quiet hint, not a gate: the server's only rule is 8 to 128 characters. */
function scorePassword(password: string): 0 | 1 | 2 | 3 | 4 {
  if (password.length < 8) return password ? 1 : 0
  let score = 1
  if (password.length >= 12) score += 1
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 1
  if (/\d/.test(password) && /[^A-Za-z0-9]/.test(password)) score += 1
  return Math.min(score, 4) as 1 | 2 | 3 | 4
}

const LABELS = ['', 'Too short', 'Okay', 'Good', 'Strong'] as const
const TONES = ['', 'bg-danger', 'bg-priority-medium', 'bg-status-resolved', 'bg-status-resolved']

export function PasswordStrength({ password }: { password: string }) {
  const score = scorePassword(password)
  if (score === 0) return null
  return (
    <div className="mt-2 flex items-center gap-2" aria-live="polite">
      <div className="flex flex-1 gap-1" aria-hidden>
        {[1, 2, 3, 4].map((i) => (
          <span
            key={i}
            className={`h-1 flex-1 rounded-full transition-colors duration-fast ${i <= score ? TONES[score] : 'bg-fg-muted/20'}`}
          />
        ))}
      </div>
      <span className="w-16 text-right text-xs text-fg-muted">{LABELS[score]}</span>
    </div>
  )
}
