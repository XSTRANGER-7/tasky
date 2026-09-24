import { useEffect, useState } from 'react'

/** True while the CSS media query matches (updates on resize and rotation). */
export function useMediaQuery(query: string): boolean {
  const get = () => typeof window.matchMedia === 'function' && window.matchMedia(query).matches
  const [matches, setMatches] = useState(get)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const list = window.matchMedia(query)
    const onChange = () => {
      setMatches(list.matches)
    }
    onChange()
    list.addEventListener('change', onChange)
    return () => {
      list.removeEventListener('change', onChange)
    }
  }, [query])
  return matches
}

/** Phones: below Tailwind's `md` breakpoint, where the bottom tab bar is shown. */
export const PHONE = '(max-width: 767.98px)'
