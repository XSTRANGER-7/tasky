import type { Config } from 'tailwindcss'

// Every colour is a CSS variable from src/styles/tokens.css (RGB channels), so the
// dark/light themes, Recharts and Framer Motion all read the same palette.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`
// Glass surfaces: the class's own opacity times the theme's glass opacity.
const glass = (name: string, alpha: string) =>
  `rgb(var(--${name}) / calc(<alpha-value> * var(--${alpha}, 1)))`

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        canvas: token('bg-canvas'),
        surface: glass('bg-surface', 'glass-alpha'),
        elevated: glass('bg-elevated', 'glass-alpha-elevated'),
        border: 'var(--border)',
        fg: { DEFAULT: token('text-primary'), muted: token('text-muted') },
        accent: token('accent'),
        priority: {
          critical: token('priority-critical'),
          high: token('priority-high'),
          medium: token('priority-medium'),
          low: token('priority-low'),
        },
        status: {
          open: token('status-open'),
          progress: token('status-in-progress'),
          resolved: token('status-resolved'),
          closed: token('status-closed'),
        },
        danger: token('danger'),
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      fontSize: {
        xs: ['12px', '16px'],
        sm: ['13px', '20px'],
        base: ['14px', '22px'],
        md: ['16px', '24px'],
        lg: ['20px', '28px'],
        xl: ['28px', '36px'],
      },
      // Rounder, iOS-like corners.
      borderRadius: { control: '10px', card: '16px', dialog: '22px' },
      transitionDuration: {
        instant: '80ms',
        fast: '150ms',
        base: '220ms',
        slow: '320ms',
        data: '700ms',
      },
      transitionTimingFunction: {
        out: 'cubic-bezier(0.16, 1, 0.3, 1)',
        in: 'cubic-bezier(0.7, 0, 0.84, 0)',
      },
    },
  },
  plugins: [],
} satisfies Config
