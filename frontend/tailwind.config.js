/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#090b0a', panel: '#0f1311', panel2: '#141a17', line: '#1f2924', text: '#d8dfd4', dim: '#8b998f',
        amber: '#f2b134', phos: '#5be39a', verm: '#ff6a47', slate: '#7f8da0',
      },
      fontFamily: {
        display: ['"Big Shoulders Display"', 'Impact', 'sans-serif'],
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
}
