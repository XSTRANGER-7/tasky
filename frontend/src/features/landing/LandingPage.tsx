import {
  motion,
  useMotionValue,
  useScroll,
  useSpring,
  useTransform,
  type Variants,
} from 'framer-motion'
import {
  ArrowRight,
  BellRing,
  Check,
  CheckCircle2,
  Clock3,
  Mail,
  Moon,
  Sparkles,
  Sun,
  Users,
  UsersRound,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { useRef, type MouseEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { useAuthConfig } from '@/api/queries'
import { useTheme } from '@/lib/theme'

/*
 * The public front door: what Tasky is, then "Get started" or "Log in". Glass surfaces
 * over the aurora (the same material as the sign-in card), sections that rise in as they
 * scroll into view, and a live-looking product preview that tilts toward the pointer.
 * Every animation stops under "reduce motion" (the app-wide MotionConfig).
 */

const EASE = [0.16, 1, 0.3, 1] as const

const rise: Variants = {
  hidden: { opacity: 0, y: 24 },
  show: (i: number = 0) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, ease: EASE, delay: i * 0.08 },
  }),
}

const FEATURES: { icon: LucideIcon; title: string; body: string; tint: string }[] = [
  {
    icon: UsersRound,
    title: 'Assign to one or many',
    body: 'Put several people on a task. Everyone assigned sees it in My work and hears about every change.',
    tint: 'from-[#6E8BFF] to-[#8B5CF6]',
  },
  {
    icon: Users,
    title: 'Teams with approvals',
    body: 'Create a team and you are its admin. People ask to join; admins approve with one click.',
    tint: 'from-[#8B5CF6] to-[#EC4899]',
  },
  {
    icon: Mail,
    title: 'Email that never gets lost',
    body: 'Assignments, updates and approvals are emailed reliably, even if the server restarts.',
    tint: 'from-[#EC4899] to-[#F97316]',
  },
  {
    icon: Zap,
    title: 'Live, everywhere',
    body: 'Changes appear instantly for your whole team. No refresh button, no stale lists.',
    tint: 'from-[#F59E0B] to-[#EAB308]',
  },
  {
    icon: Clock3,
    title: 'Deadlines you can see',
    body: 'Every task carries clear response and resolution timers, and warns before it slips.',
    tint: 'from-[#10B981] to-[#14B8A6]',
  },
  {
    icon: Sparkles,
    title: 'AI that only suggests',
    body: 'Priority, the right person and a summary, suggested as you type. You decide.',
    tint: 'from-[#06B6D4] to-[#6E8BFF]',
  },
]

const STEPS = [
  { title: 'Create your team', body: 'Sign up, name your team, and you are its admin.' },
  { title: 'Add and assign tasks', body: 'Give each task to one person or a whole group.' },
  { title: 'Track it to done', body: 'Updates, emails and deadlines keep everyone moving.' },
]

export function LandingPage() {
  const { data: config } = useAuthConfig()
  const canSignUp = config?.allow_self_register ?? true
  const start = canSignUp ? '/register' : '/login'

  return (
    <div className="aurora relative min-h-dvh overflow-x-clip text-fg">
      <Nav start={start} canSignUp={canSignUp} />
      <main>
        <Hero start={start} canSignUp={canSignUp} />
        <Features />
        <HowItWorks />
        <FinalCta start={start} canSignUp={canSignUp} />
      </main>
      <footer className="border-t border-border px-4 py-8 text-center text-xs text-fg-muted sm:px-6">
        <span className="inline-flex items-center gap-2">
          <img src="/logo.svg" alt="" className="size-4" /> Tasky · Team tasks, done calmly.
        </span>
      </footer>
    </div>
  )
}

// ---------------------------------------------------------------- navigation

function Nav({ start, canSignUp }: { start: string; canSignUp: boolean }) {
  const [theme, toggleTheme] = useTheme()
  return (
    <motion.header
      initial={{ y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.5, ease: EASE }}
      className="sticky top-3 z-40 mx-auto mt-3 w-[calc(100%-24px)] max-w-6xl"
    >
      <nav
        aria-label="Main"
        className="glass-card flex h-14 items-center gap-2 rounded-full pl-4 pr-2"
      >
        <Link to="/" className="flex items-center gap-2" aria-label="Tasky home">
          <img src="/logo.svg" alt="" className="size-7" />
          <span className="font-semibold tracking-tight">Tasky</span>
        </Link>
        <div className="ml-6 hidden items-center gap-1 text-sm text-fg-muted md:flex">
          <a href="#features" className="rounded-full px-3 py-1.5 hover:bg-canvas/60 hover:text-fg">
            Features
          </a>
          <a href="#how" className="rounded-full px-3 py-1.5 hover:bg-canvas/60 hover:text-fg">
            How it works
          </a>
        </div>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            className="flex size-9 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-canvas/60 hover:text-fg"
          >
            {theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>
          <Link
            to="/login"
            className="rounded-full px-4 py-2 text-sm font-medium text-fg transition-colors hover:bg-canvas/60"
          >
            Log in
          </Link>
          {canSignUp && (
            <Link
              to={start}
              className="btn-glow rounded-full px-4 py-2 text-sm font-medium text-white"
            >
              Get started
            </Link>
          )}
        </div>
      </nav>
    </motion.header>
  )
}

// ---------------------------------------------------------------- hero

function Hero({ start, canSignUp }: { start: string; canSignUp: boolean }) {
  const ref = useRef<HTMLElement>(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end start'] })
  const drift = useTransform(scrollYProgress, [0, 1], [0, 120])
  const fade = useTransform(scrollYProgress, [0, 0.8], [1, 0.2])

  return (
    <section ref={ref} className="relative mx-auto max-w-6xl px-4 pb-10 pt-16 sm:px-6 sm:pt-24">
      <motion.div style={{ opacity: fade }} className="mx-auto max-w-3xl text-center">
        <motion.span
          variants={rise}
          initial="hidden"
          animate="show"
          className="glass-card inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium"
        >
          <span className="size-1.5 animate-pulse rounded-full bg-status-resolved" />
          New: several people per task, and a fresh look
        </motion.span>
        <motion.h1
          variants={rise}
          initial="hidden"
          animate="show"
          custom={1}
          className="mt-6 text-balance text-[40px] font-semibold leading-[1.05] tracking-[-0.03em] sm:text-6xl"
        >
          Plan it. Assign it. <span className="gradient-text">Get it done.</span>
        </motion.h1>
        <motion.p
          variants={rise}
          initial="hidden"
          animate="show"
          custom={2}
          className="mx-auto mt-5 max-w-xl text-balance text-md text-fg-muted"
        >
          Tasky is the calm, fast workspace for team tasks. Give work to one person or many, see
          every deadline, and never miss an update.
        </motion.p>
        <motion.div
          variants={rise}
          initial="hidden"
          animate="show"
          custom={3}
          className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row"
        >
          {canSignUp && (
            <Link
              to={start}
              className="btn-glow group inline-flex h-12 items-center gap-2 rounded-full px-6 text-sm font-semibold text-white"
            >
              Get started free
              <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
          )}
          <Link
            to="/login"
            className="glass-card inline-flex h-12 items-center rounded-full px-6 text-sm font-semibold transition-transform hover:-translate-y-0.5"
          >
            Log in
          </Link>
        </motion.div>
        <motion.ul
          variants={rise}
          initial="hidden"
          animate="show"
          custom={4}
          className="mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-xs text-fg-muted"
        >
          {['Email alerts', 'Real-time updates', 'Light and dark'].map((t) => (
            <li key={t} className="inline-flex items-center gap-1.5">
              <Check className="size-3.5 text-status-resolved" /> {t}
            </li>
          ))}
        </motion.ul>
      </motion.div>

      <motion.div style={{ y: drift }}>
        <Preview />
      </motion.div>
    </section>
  )
}

/** A glass app window with tasks sliding in, tilting gently toward the pointer. */
function Preview() {
  const mx = useMotionValue(0)
  const my = useMotionValue(0)
  const rotateX = useSpring(useTransform(my, [-0.5, 0.5], [6, -6]), { stiffness: 120, damping: 18 })
  const rotateY = useSpring(useTransform(mx, [-0.5, 0.5], [-8, 8]), { stiffness: 120, damping: 18 })

  function onMove(e: MouseEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    mx.set((e.clientX - r.left) / r.width - 0.5)
    my.set((e.clientY - r.top) / r.height - 0.5)
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 40, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.9, ease: EASE, delay: 0.35 }}
      className="relative mx-auto mt-16 max-w-4xl [perspective:1400px]"
      onMouseMove={onMove}
      onMouseLeave={() => {
        mx.set(0)
        my.set(0)
      }}
    >
      <motion.div
        style={{ rotateX, rotateY }}
        className="glass-card relative overflow-hidden rounded-[26px] p-2 [transform-style:preserve-3d]"
        aria-label="A preview of the Tasky task list"
        role="img"
      >
        <div className="flex items-center gap-1.5 px-3 py-2">
          <span className="size-2.5 rounded-full bg-[#FF5F57]" />
          <span className="size-2.5 rounded-full bg-[#FEBC2E]" />
          <span className="size-2.5 rounded-full bg-[#28C840]" />
          <span className="ml-3 text-xs text-fg-muted">Tasky · Product team</span>
        </div>
        <div className="grid gap-2 sm:grid-cols-[180px_1fr]">
          <div className="hidden space-y-1 rounded-2xl bg-canvas/40 p-3 sm:block">
            {['Dashboard', 'Tasks', 'My work', 'Team'].map((item, i) => (
              <div
                key={item}
                className={`rounded-lg px-2.5 py-1.5 text-xs ${i === 1 ? 'bg-accent/15 font-medium text-accent' : 'text-fg-muted'}`}
              >
                {item}
              </div>
            ))}
          </div>
          <div className="space-y-2 rounded-2xl bg-canvas/40 p-3">
            <PreviewRow
              i={0}
              title="Launch the new pricing page"
              status="In progress"
              tone="bg-priority-medium"
              people={['#6E8BFF', '#EC4899']}
              due="2h left"
            />
            <PreviewRow
              i={1}
              title="Fix checkout on Safari"
              status="Open"
              tone="bg-accent"
              people={['#10B981']}
              due="Today"
            />
            <PreviewRow
              i={2}
              title="Write the Q3 release notes"
              status="Done"
              tone="bg-status-resolved"
              people={['#F59E0B', '#8B5CF6', '#06B6D4']}
              due="Done"
            />
            <PreviewRow
              i={3}
              title="Interview two designers"
              status="Open"
              tone="bg-accent"
              people={['#8B5CF6']}
              due="Fri"
            />
          </div>
        </div>
      </motion.div>

      <Floating className="-left-4 top-24 hidden sm:flex" delay={0.9} float={10}>
        <CheckCircle2 className="size-4 text-status-resolved" />
        <span>
          <b className="font-semibold">Task done</b>
          <span className="block text-fg-muted">Release notes, by Ada</span>
        </span>
      </Floating>
      <Floating className="-right-6 top-40 hidden sm:flex" delay={1.1} float={14}>
        <UsersRound className="size-4 text-accent" />
        <span>
          <b className="font-semibold">Assigned to</b>
          <span className="block text-fg-muted">Ada, Jonas and Priya</span>
        </span>
      </Floating>
      <Floating className="-bottom-5 left-1/3 hidden sm:flex" delay={1.3} float={8}>
        <BellRing className="size-4 text-priority-high" />
        <span>
          <b className="font-semibold">Emailed 3 people</b>
          <span className="block text-fg-muted">just now</span>
        </span>
      </Floating>
    </motion.div>
  )
}

function PreviewRow({
  i,
  title,
  status,
  tone,
  people,
  due,
}: {
  i: number
  title: string
  status: string
  tone: string
  people: string[]
  due: string
}) {
  return (
    <motion.div
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.6, ease: EASE, delay: 0.7 + i * 0.12 }}
      className="flex items-center gap-3 rounded-xl border border-border bg-surface px-3 py-2.5"
    >
      <span className={`size-2 shrink-0 rounded-full ${tone}`} />
      <span className="min-w-0 flex-1 truncate text-sm">{title}</span>
      <span className="hidden text-xs text-fg-muted sm:inline">{status}</span>
      <span className="flex">
        {people.map((c, n) => (
          <span
            key={c}
            className={`size-5 rounded-full ring-2 ring-surface ${n ? '-ml-1.5' : ''}`}
            style={{ background: c }}
          />
        ))}
      </span>
      <span className="w-14 text-right text-xs tabular-nums text-fg-muted">{due}</span>
    </motion.div>
  )
}

function Floating({
  children,
  className,
  delay,
  float,
}: {
  children: ReactNode
  className: string
  delay: number
  float: number
}) {
  return (
    <motion.div
      aria-hidden
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1, y: [0, -float, 0] }}
      transition={{
        opacity: { delay, duration: 0.4 },
        scale: { delay, type: 'spring', stiffness: 260, damping: 18 },
        y: { delay: delay + 0.4, duration: 5, repeat: Infinity, ease: 'easeInOut' },
      }}
      className={`glass-card absolute z-10 items-center gap-2.5 rounded-2xl px-3.5 py-2.5 text-xs ${className}`}
    >
      {children}
    </motion.div>
  )
}

// ---------------------------------------------------------------- features

function SectionTitle({ eyebrow, title, body }: { eyebrow: string; title: string; body: string }) {
  return (
    <motion.div
      variants={rise}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: '-80px' }}
      className="mx-auto max-w-2xl text-center"
    >
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">{eyebrow}</p>
      <h2 className="mt-3 text-balance text-3xl font-semibold tracking-[-0.02em] sm:text-4xl">
        {title}
      </h2>
      <p className="mt-3 text-balance text-fg-muted">{body}</p>
    </motion.div>
  )
}

function Features() {
  return (
    <section id="features" className="mx-auto max-w-6xl scroll-mt-24 px-4 py-24 sm:px-6">
      <SectionTitle
        eyebrow="Features"
        title="Everything your team needs. Nothing it doesn't."
        body="Clear ownership, reliable notifications and deadlines everyone can see."
      />
      <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((f, i) => {
          const Icon = f.icon
          return (
            <motion.article
              key={f.title}
              variants={rise}
              initial="hidden"
              whileInView="show"
              viewport={{ once: true, margin: '-60px' }}
              custom={i % 3}
              whileHover={{ y: -4 }}
              className="glass-card group rounded-[22px] p-6"
            >
              <span
                className={`flex size-11 items-center justify-center rounded-[14px] bg-gradient-to-br text-white shadow-lg ${f.tint}`}
              >
                <Icon aria-hidden className="size-5" />
              </span>
              <h3 className="mt-5 font-semibold">{f.title}</h3>
              <p className="mt-1.5 text-sm text-fg-muted">{f.body}</p>
            </motion.article>
          )
        })}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- how it works

function HowItWorks() {
  return (
    <section id="how" className="mx-auto max-w-6xl scroll-mt-24 px-4 py-16 sm:px-6">
      <SectionTitle
        eyebrow="How it works"
        title="Up and running in a minute"
        body="No setup calls, no training. Three steps and your team is moving."
      />
      <ol className="relative mt-14 grid gap-4 md:grid-cols-3">
        <motion.span
          aria-hidden
          initial={{ scaleX: 0 }}
          whileInView={{ scaleX: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 1.2, ease: EASE, delay: 0.2 }}
          className="absolute left-[16%] right-[16%] top-8 hidden h-px origin-left bg-gradient-to-r from-[#6E8BFF] via-[#8B5CF6] to-[#EC4899] md:block"
        />
        {STEPS.map((s, i) => (
          <motion.li
            key={s.title}
            variants={rise}
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: '-60px' }}
            custom={i}
            className="relative text-center"
          >
            <span className="glass-card relative mx-auto flex size-16 items-center justify-center rounded-[20px] text-xl font-semibold">
              <span className="gradient-text">{i + 1}</span>
            </span>
            <h3 className="mt-5 font-semibold">{s.title}</h3>
            <p className="mx-auto mt-1.5 max-w-xs text-sm text-fg-muted">{s.body}</p>
          </motion.li>
        ))}
      </ol>
    </section>
  )
}

// ---------------------------------------------------------------- final call to action

function FinalCta({ start, canSignUp }: { start: string; canSignUp: boolean }) {
  return (
    <section className="mx-auto max-w-5xl px-4 pb-24 pt-16 sm:px-6">
      <motion.div
        variants={rise}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: '-60px' }}
        className="glass-card relative overflow-hidden rounded-[32px] px-6 py-14 text-center sm:px-12"
      >
        <div
          aria-hidden
          className="pointer-events-none absolute -top-24 left-1/2 size-72 -translate-x-1/2 rounded-full bg-[#8B5CF6] opacity-25 blur-3xl"
        />
        <img src="/logo.svg" alt="" className="relative mx-auto size-14" />
        <h2 className="relative mt-6 text-balance text-3xl font-semibold tracking-[-0.02em] sm:text-4xl">
          Ready to get your team moving?
        </h2>
        <p className="relative mx-auto mt-3 max-w-lg text-fg-muted">
          Create your team in seconds. Invite people when you are ready.
        </p>
        <div className="relative mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          {canSignUp && (
            <Link
              to={start}
              className="btn-glow inline-flex h-12 items-center gap-2 rounded-full px-6 text-sm font-semibold text-white"
            >
              Get started free <ArrowRight className="size-4" />
            </Link>
          )}
          <Link
            to="/login"
            className="inline-flex h-12 items-center rounded-full px-6 text-sm font-semibold text-fg hover:bg-canvas/60"
          >
            I already have an account
          </Link>
        </div>
      </motion.div>
    </section>
  )
}
