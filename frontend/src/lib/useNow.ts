import { useEffect, useState } from 'react'

/** Re-render every 30 s so countdowns tick without a timer per row. */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => {
      setNow(Date.now())
    }, intervalMs)
    return () => {
      window.clearInterval(id)
    }
  }, [intervalMs])
  return now
}
