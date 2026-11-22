/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#0f172a',
        panel: '#111827',
        accent: '#6366f1',
      },
      fontFamily: {
        sans: ['Inter', 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', 'ui-sans-serif', 'system-ui'],
      },
      boxShadow: {
        soft: '0 1px 2px rgba(15,23,42,0.04), 0 18px 44px -28px rgba(15,23,42,0.20)',
      },
    },
  },
  plugins: [],
}