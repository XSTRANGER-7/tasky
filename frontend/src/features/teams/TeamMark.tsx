/** A team's initials in a tinted tile: the team's avatar throughout the app. */
export function TeamMark({ name, size = 40 }: { name: string; size?: number }) {
  const letters = name
    .split(/\s+/)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
  return (
    <span
      aria-hidden
      className="flex shrink-0 items-center justify-center rounded-control bg-accent/15 font-semibold text-accent"
      style={{ width: size, height: size, fontSize: size * 0.36 }}
    >
      {letters || '?'}
    </span>
  )
}
