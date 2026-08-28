import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // Deep navy/charcoal palette
        navy: {
          50: '#eef2ff',
          100: '#dde4ff',
          200: '#c3cfff',
          300: '#9fb2ff',
          400: '#7a8dff',
          500: '#5c66ff',
          600: '#4a3df5',
          700: '#3d2fd8',
          800: '#1e1b4b',
          900: '#181542',
          950: '#0f0d2e',
        },
        charcoal: {
          50: '#f6f6f7',
          100: '#e2e3e5',
          200: '#c4c5ca',
          300: '#9fa1a8',
          400: '#7b7d85',
          500: '#60636b',
          600: '#4c4e55',
          700: '#3e4046',
          800: '#2d2f34',
          900: '#1f2024',
          950: '#141518',
        },
        // Surface system
        surface: {
          base: '#0c0f1a',
          card: '#141927',
          elevated: '#1c2235',
        },
        // Type identity colors
        type: {
          finding: '#f43f5e',
          conflict: '#f59e0b',
          update: '#8b5cf6',
        },
        // Status colors for queue items
        status: {
          pending: {
            bg: 'rgba(245, 158, 11, 0.2)',
            text: '#fcd34d',
            border: 'rgba(245, 158, 11, 0.4)',
          },
          approved: {
            bg: 'rgba(34, 197, 94, 0.2)',
            text: '#86efac',
            border: 'rgba(34, 197, 94, 0.4)',
          },
          rejected: {
            bg: 'rgba(239, 68, 68, 0.2)',
            text: '#fca5a5',
            border: 'rgba(239, 68, 68, 0.4)',
          },
          unverifiable: {
            bg: 'rgba(107, 114, 128, 0.2)',
            text: '#9ca3af',
            border: 'rgba(107, 114, 128, 0.4)',
          },
        },
      },
      backgroundColor: {
        'app-primary': '#0c0f1a',
        'app-secondary': '#141927',
        'app-surface': '#1c2235',
      },
      textColor: {
        'app-primary': '#f6f6f7',
        'app-secondary': '#c4c5ca',
        'app-muted': '#7b7d85',
      },
      animation: {
        'spin-slow': 'spin-slow 2s linear infinite',
        'fade-slide-up': 'fadeSlideUp 300ms ease-out forwards',
        'sweep-right': 'sweepRight 400ms ease-out forwards',
        'warning-pulse': 'warningPulse 2s ease-in-out infinite',
        'draw-check': 'drawCheck 300ms ease-out forwards',
        'connector-fill': 'connectorFill 500ms ease-out forwards',
      },
      keyframes: {
        'spin-slow': {
          to: { transform: 'rotate(360deg)' },
        },
        fadeSlideUp: {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        sweepRight: {
          from: { transform: 'scaleX(0)' },
          to: { transform: 'scaleX(1)' },
        },
        warningPulse: {
          '0%, 100%': {
            opacity: '0.4',
            boxShadow: '0 0 0 0 rgba(251,191,36,0.3)',
          },
          '50%': {
            opacity: '1',
            boxShadow: '0 0 8px 2px rgba(251,191,36,0.2)',
          },
        },
        drawCheck: {
          from: { strokeDashoffset: '24' },
          to: { strokeDashoffset: '0' },
        },
        connectorFill: {
          from: { width: '0%' },
          to: { width: '100%' },
        },
      },
    },
  },
  plugins: [],
}

export default config
