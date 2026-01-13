/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Custom dark theme colors
        surface: {
          DEFAULT: '#1a1a2e',
          secondary: '#16213e',
          tertiary: '#0f3460'
        },
        accent: {
          DEFAULT: '#e94560',
          muted: '#533483'
        }
      }
    },
  },
  plugins: [],
}
