/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        dark: {
          bg: "#0a0a0f",
          card: "#13131f",
          surface: "#1e1e2e",
        },
        accent: {
          primary: "#8b5cf6",
          secondary: "#7c3aed",
          light: "#a78bfa",
        }
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["Cascadia Code", "Fira Code", "JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
}
