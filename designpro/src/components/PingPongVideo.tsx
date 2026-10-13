import { useEffect, useRef } from 'react'

interface PingPongVideoProps {
  src: string
  className?: string
}

/**
 * Plays the clip forward once (native playback), then scrubs it backward at the
 * same real-time speed, then forward again, endlessly. No hard jump-cut at the
 * loop point, so the motion always stays continuous.
 */
export default function PingPongVideo({ src, className = '' }: PingPongVideoProps) {
  const ref = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    const v = ref.current
    if (!v) return

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)')
    let raf = 0
    let dir: 1 | -1 = 1
    let last = 0
    let seeking = false

    const forward = () => {
      cancelAnimationFrame(raf)
      dir = 1
      seeking = false
      v.play().catch(() => {})
    }

    const step = (now: number) => {
      if (dir !== -1) return
      // Only issue a new seek once the previous one has landed, so frames never queue up.
      if (!seeking) {
        const dt = (now - last) / 1000
        last = now
        const t = v.currentTime - dt
        if (t <= 0.02) {
          v.currentTime = 0
          forward()
          return
        }
        seeking = true
        v.currentTime = t
      }
      raf = requestAnimationFrame(step)
    }

    const reverse = () => {
      if (reduce.matches) return
      dir = -1
      v.pause()
      last = performance.now()
      seeking = false
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(step)
    }

    const onSeeked = () => {
      seeking = false
    }

    const sync = () => {
      if (reduce.matches) {
        cancelAnimationFrame(raf)
        v.pause()
        v.currentTime = 0
      } else if (dir === 1) {
        v.play().catch(() => {})
      } else {
        reverse()
      }
    }

    const onVisibility = () => {
      if (!document.hidden) sync()
    }

    v.addEventListener('ended', reverse)
    v.addEventListener('seeked', onSeeked)
    v.addEventListener('canplay', sync)
    document.addEventListener('visibilitychange', onVisibility)
    reduce.addEventListener('change', sync)
    sync()

    return () => {
      cancelAnimationFrame(raf)
      v.removeEventListener('ended', reverse)
      v.removeEventListener('seeked', onSeeked)
      v.removeEventListener('canplay', sync)
      document.removeEventListener('visibilitychange', onVisibility)
      reduce.removeEventListener('change', sync)
    }
  }, [])

  return (
    <video
      ref={ref}
      className={className}
      src={src}
      autoPlay
      muted
      playsInline
      preload="auto"
    />
  )
}
