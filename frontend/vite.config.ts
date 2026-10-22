import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base './' makes the build work from any static host path (GitHub Pages project sites, Netlify, a plain folder).
export default defineConfig({ base: './', plugins: [react()] })
