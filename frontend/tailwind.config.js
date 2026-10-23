/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#07090a', ink2: '#0b0f0e', panel: '#0f1311', panel2: '#141a17', line: '#1f2924', text: '#dde4d9', dim: '#8d9b92',
        amber: '#f2b134', phos: '#5be39a', verm: '#ff6a47', slate: '#7f8da0', ice: '#7cc4ff',
      },
      fontFamily: {
        display: ['"Bricolage Grotesque"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        sans: ['"Instrument Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        glass: 'inset 0 1px 0 rgba(255,255,255,.07), 0 24px 60px -28px rgba(0,0,0,.8)',
        glowA: '0 0 40px -6px rgba(242,177,52,.45)',
        glowP: '0 0 40px -6px rgba(91,227,154,.4)',
        glowV: '0 0 40px -6px rgba(255,106,71,.4)',
      },
      borderRadius: { xl2: '18px' },
      keyframes: {
        shimmer: { '100%': { transform: 'translateX(100%)' } },
        floaty: { '0%,100%': { transform: 'translateY(0)' }, '50%': { transform: 'translateY(-8px)' } },
      },
      animation: { shimmer: 'shimmer 1.6s infinite', floaty: 'floaty 6s ease-in-out infinite' },
    },
  },
  plugins: [],
}
