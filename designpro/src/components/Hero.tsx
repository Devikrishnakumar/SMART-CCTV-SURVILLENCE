import { type ReactNode, useEffect, useState } from 'react'
import {
  Activity,
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Camera,
  Check,
  CircleDot,
  Eye,
  Flame,
  FileClock,
  ShieldAlert,
  ShieldCheck,
  Swords,
  Wifi,
} from 'lucide-react'
import { motion, useReducedMotion } from 'framer-motion'
import Navbar from './Navbar'
import ShinyText from './ShinyText'

type CameraState = {
  id?: string
  name?: string
  status?: 'connected' | 'connecting' | 'reconnecting' | 'disconnected' | string
  error?: string | null
}

type LiveStatus = {
  camera?: CameraState
  risk_level?: string
  fps?: number
  total_alerts?: number
}

const signals = [
  {
    number: '01',
    icon: Flame,
    title: 'Fire and smoke',
    detail: 'Surface a fire signal in the active camera feed.',
    tone: 'signal-orange',
  },
  {
    number: '02',
    icon: Swords,
    title: 'Violence',
    detail: 'Review movement patterns that may indicate a fight.',
    tone: 'signal-red',
  },
  {
    number: '03',
    icon: ShieldAlert,
    title: 'Weapons',
    detail: 'Bring detected weapon signals into operator view.',
    tone: 'signal-violet',
  },
  {
    number: '04',
    icon: Activity,
    title: 'Traffic incidents',
    detail: 'Track accident and traffic signals in the footage.',
    tone: 'signal-amber',
  },
]

const steps = [
  {
    icon: Camera,
    title: 'Connect a source',
    detail: 'Use a webcam attached to the computer or enter an IP camera / NVR stream URL.',
  },
  {
    icon: Eye,
    title: 'Review the live feed',
    detail: 'See the annotated video, camera health, risk level, and confidence signals together.',
  },
  {
    icon: FileClock,
    title: 'Keep incident context',
    detail: 'Save evidence clips and reports when a detection needs a closer look.',
  },
]

function Reveal({ children, className = '', delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const reduceMotion = useReducedMotion()
  return (
    <motion.div
      className={className}
      initial={reduceMotion ? false : { opacity: 0, y: 22 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.18 }}
      transition={{ duration: 0.65, ease: [0.22, 1, 0.36, 1], delay }}
    >
      {children}
    </motion.div>
  )
}

export default function Hero() {
  const [liveStatus, setLiveStatus] = useState<LiveStatus | null>(null)
  const [serviceOnline, setServiceOnline] = useState(false)
  const reduceMotion = useReducedMotion()

  useEffect(() => {
    let mounted = true
    const refreshStatus = async () => {
      try {
        const response = await fetch('/api/status', { cache: 'no-store' })
        if (!response.ok) throw new Error('Dashboard is not responding')
        const status = await response.json() as LiveStatus
        if (mounted) {
          setLiveStatus(status)
          setServiceOnline(true)
        }
      } catch {
        if (mounted) {
          setLiveStatus(null)
          setServiceOnline(false)
        }
      }
    }
    void refreshStatus()
    const timer = window.setInterval(refreshStatus, 4000)
    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [])

  const camera = liveStatus?.camera
  const feedIsLive = camera?.status === 'connected'
  const serviceLabel = !serviceOnline
    ? 'DASHBOARD NOT CONNECTED'
    : feedIsLive
      ? 'CAMERA FEED LIVE'
      : 'ENGINE READY · CAMERA STANDBY'

  return (
    <main className="landing-page" id="top">
      <section className="hero-section" aria-labelledby="hero-title">
        <div className="hero-ambient hero-ambient-one" />
        <div className="hero-ambient hero-ambient-two" />
        <div className="hero-grid" />
        <Navbar />

        <div className="hero-content page-width">
          <motion.div
            className="hero-copy"
            initial={reduceMotion ? false : { opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: 'easeOut' }}
          >
            <div className="eyebrow"><span className="eyebrow-dot" /> COMPUTER VISION FOR CAMERA OPERATORS</div>
            <h1 id="hero-title">
              See the moment.<br />
              <ShinyText text="Understand the risk." color="#c9f5df" shineColor="#ffffff" speed={4.8} spread={105} disabled={Boolean(reduceMotion)} className="hero-shine" />
            </h1>
            <p className="hero-description">
              NovaGuard reads a live camera feed for fire, violence, weapons, and traffic incidents—then brings the video, risk signals, and incident evidence into one clear workspace.
            </p>
            <div className="hero-actions">
              <a className="button button-primary" href="/dashboard">
                Open live dashboard <ArrowUpRight size={17} />
              </a>
              <a className="button button-quiet" href="#overview">
                Explore the system <ArrowDown size={16} />
              </a>
            </div>
            <div className="hero-proof">
              <span><Check size={14} /> USB webcams</span>
              <span><Check size={14} /> RTSP cameras & NVRs</span>
              <span><Check size={14} /> Local processing</span>
            </div>
          </motion.div>

          <motion.div
            className="monitor-card-wrap"
            initial={reduceMotion ? false : { opacity: 0, scale: 0.97, y: 16 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ duration: 0.85, delay: 0.12, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="monitor-orbit orbit-one" />
            <div className="monitor-orbit orbit-two" />
            <div className="monitor-card">
              <div className="monitor-topline">
                <div className="monitor-brand"><span className="mini-mark">N</span> NOVAGUARD <span className="topline-divider" /> MONITOR</div>
                <div className={`monitor-live ${feedIsLive ? 'is-live' : ''}`}>
                  <span /> {feedIsLive ? 'LIVE' : 'PREVIEW'}
                </div>
              </div>

              <div className="monitor-scene" aria-label="Animated illustrative camera-feed preview">
                <div className="scene-grain" />
                <div className="scene-light scene-light-left" />
                <div className="scene-light scene-light-right" />
                <div className="scene-window" />
                <div className="scene-door"><span /></div>
                <div className="scene-floor" />
                <div className="scene-person"><i /><b /><span /></div>
                <div className="scene-track-box"><span>SUBJECT TRACKING · UI PREVIEW</span></div>
                <div className="scene-scanline" />
                <div className="scene-corner scene-corner-tl" />
                <div className="scene-corner scene-corner-tr" />
                <div className="scene-corner scene-corner-bl" />
                <div className="scene-corner scene-corner-br" />
                <div className="scene-caption"><CircleDot size={12} /> {feedIsLive ? camera?.name || 'Active camera' : 'ILLUSTRATIVE FEED'}</div>
                <div className="scene-time">00:24:18</div>
              </div>

              <div className="monitor-foot">
                <div className="monitor-state">
                  <span className={`state-pulse ${feedIsLive ? 'pulse-live' : ''}`} />
                  <div><strong>{serviceLabel}</strong><small>{camera?.error || (feedIsLive ? 'Analyzing incoming frames' : 'Connect a camera to see its live video here')}</small></div>
                </div>
                <div className="monitor-risk">
                  <small>RISK LEVEL</small>
                  <strong className={`risk-${(liveStatus?.risk_level || 'standby').toLowerCase()}`}>{serviceOnline ? liveStatus?.risk_level || '—' : '—'}</strong>
                </div>
              </div>
            </div>
            <div className="float-chip chip-top"><span className="chip-icon"><Wifi size={15} /></span><span><b>Camera health</b><small>{feedIsLive ? 'Connected · receiving video' : serviceOnline ? 'Ready for a source' : 'Waiting for dashboard'}</small></span></div>
            <div className="float-chip chip-bottom"><span className="chip-icon chip-icon-mint"><Activity size={15} /></span><span><b>4 signal checks</b><small>Fire · violence · weapons · traffic</small></span></div>
          </motion.div>
        </div>

        <div className="hero-bottom page-width">
          <span>LIVE VIDEO <i /> SIGNALS <i /> EVIDENCE</span>
          <span>BUILT FOR THE CAMERA SYSTEMS YOU ALREADY HAVE</span>
        </div>
      </section>

      <section className="overview-section section-pad" id="overview">
        <div className="page-width">
          <Reveal className="section-heading-row">
            <div>
              <div className="eyebrow eyebrow-dark"><span className="eyebrow-dot" /> A PRACTICAL OPERATOR WORKFLOW</div>
              <h2>One live view.<br /><span>More useful context.</span></h2>
            </div>
            <p className="section-intro">NovaGuard connects camera video to a set of detection models, so operators can review the feed and its signals without jumping between tools.</p>
          </Reveal>

          <div className="workflow-grid">
            {steps.map((step, index) => {
              const Icon = step.icon
              return (
                <Reveal className="workflow-card" delay={index * 0.09} key={step.title}>
                  <div className="workflow-card-top"><span className="workflow-icon"><Icon size={19} strokeWidth={1.7} /></span><span className="workflow-number">0{index + 1}</span></div>
                  <h3>{step.title}</h3>
                  <p>{step.detail}</p>
                  <div className="workflow-line" />
                </Reveal>
              )
            })}
          </div>
        </div>
      </section>

      <section className="signals-section section-pad" id="signals">
        <div className="page-width">
          <Reveal className="signals-heading">
            <div>
              <div className="eyebrow"><span className="eyebrow-dot" /> WHAT THE MODELS WATCH FOR</div>
              <h2>Signals worth<br /><span>a closer look.</span></h2>
            </div>
            <p>Each signal appears alongside its confidence and the source footage. An alert is a prompt for human review, not a final determination.</p>
          </Reveal>
          <div className="signals-grid">
            {signals.map((signal, index) => {
              const Icon = signal.icon
              return (
                <Reveal className={`signal-card ${signal.tone}`} delay={index * 0.07} key={signal.number}>
                  <div className="signal-card-top"><span className="signal-icon"><Icon size={20} strokeWidth={1.7} /></span><span>{signal.number}</span></div>
                  <h3>{signal.title}</h3>
                  <p>{signal.detail}</p>
                  <span className="signal-foot"><span /> MODEL SIGNAL</span>
                </Reveal>
              )
            })}
          </div>
        </div>
      </section>

      <section className="camera-section section-pad" id="cameras">
        <div className="page-width camera-cta-panel">
          <div className="camera-cta-copy">
            <div className="eyebrow"><span className="eyebrow-dot" /> START WITH ONE CAMERA</div>
            <h2>Bring your view<br />into <span>focus.</span></h2>
            <p>Add a webcam for a quick demo, or connect an IP camera / NVR with its RTSP stream URL. Save camera profiles and switch the active feed from the dashboard.</p>
            <a className="button button-primary" href="/dashboard">Set up a camera <ArrowRight size={17} /></a>
          </div>
          <div className="camera-setup-visual">
            <div className="setup-line setup-line-one" />
            <div className="setup-line setup-line-two" />
            <div className="setup-node setup-node-one"><Camera size={19} /><span>WEBCAM</span></div>
            <div className="setup-node setup-node-two"><Wifi size={19} /><span>RTSP / NVR</span></div>
            <div className="setup-center"><span className="setup-center-mark">N</span><strong>NovaGuard</strong><small>ONE ACTIVE FEED</small></div>
            <div className="setup-orbit" />
          </div>
        </div>
      </section>

      <footer className="site-footer page-width">
        <a className="brand footer-brand" href="#top">
          <span className="brand-mark" aria-hidden="true"><ShieldCheck size={26} strokeWidth={1.5} /></span>
          <span className="brand-copy"><strong>NOVAGUARD</strong><small>VIDEO INTELLIGENCE</small></span>
        </a>
        <p>AI-assisted camera monitoring for a faster, clearer review.</p>
        <a className="footer-link" href="/dashboard">Go to dashboard <ArrowUpRight size={14} /></a>
      </footer>
    </main>
  )
}
