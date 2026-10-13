import { useRef, useState } from 'react'
import {
  motion,
  useAnimationFrame,
  useMotionValue,
  useTransform,
} from 'framer-motion'

interface ShinyTextProps {
  text: string
  /** Base text color */
  color?: string
  /** Color of the sweeping highlight */
  shineColor?: string
  /** Seconds for one full left-to-right sweep */
  speed?: number
  /** Gradient angle in degrees */
  spread?: number
  disabled?: boolean
  className?: string
}

export default function ShinyText({
  text,
  color = '#64CEFB',
  shineColor = '#ffffff',
  speed = 3,
  spread = 100,
  disabled = false,
  className = '',
}: ShinyTextProps) {
  const [isPaused] = useState(false)
  const progress = useMotionValue(0) // 0 -> 100, loops
  const elapsedRef = useRef(0)
  const lastTimeRef = useRef<number | null>(null)
  const duration = speed * 1000

  useAnimationFrame((time) => {
    if (disabled || isPaused) {
      lastTimeRef.current = null
      return
    }
    if (lastTimeRef.current === null) {
      lastTimeRef.current = time
      return
    }
    const delta = time - lastTimeRef.current
    lastTimeRef.current = time
    elapsedRef.current += delta

    // Linear loop: 0 -> 100 over `duration`, then restart
    const cycle = elapsedRef.current % duration
    progress.set((cycle / duration) * 100)
  })

  // Sweep the highlight from the left edge to the right edge.
  // With backgroundSize 200%, position 150% -> -50% moves the shine L -> R.
  const backgroundPosition = useTransform(progress, (p) => `${150 - p * 2}% center`)

  return (
    <motion.span
      className={`inline-block ${className}`}
      style={{
        backgroundImage: `linear-gradient(${spread}deg, ${color} 0%, ${color} 35%, ${shineColor} 50%, ${color} 65%, ${color} 100%)`,
        backgroundSize: '200% auto',
        backgroundPosition,
        backgroundClip: 'text',
        WebkitBackgroundClip: 'text',
        color: 'transparent',
        WebkitTextFillColor: 'transparent',
      }}
    >
      {text}
    </motion.span>
  )
}
