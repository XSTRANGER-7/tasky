import { animate, useMotionValue, useReducedMotion, useTransform, motion } from 'framer-motion'
import { useEffect } from 'react'

/** Rolls from the previous value to the new one (700 ms, ease-out; instant if reduced). */
export function AnimatedNumber({
  value,
  format = (n) => Math.round(n).toLocaleString(),
}: {
  value: number
  format?: (n: number) => string
}) {
  const reduce = useReducedMotion()
  const mv = useMotionValue(0)
  const text = useTransform(mv, format)

  useEffect(() => {
    if (reduce) {
      mv.set(value)
      return
    }
    const controls = animate(mv, value, { duration: 0.7, ease: [0.16, 1, 0.3, 1] })
    return () => {
      controls.stop()
    }
  }, [value, reduce, mv])

  return <motion.span className="tabular">{text}</motion.span>
}
