/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          900: "#14181F",
          800: "#1B212B",
          700: "#2B3340",
          500: "#566273",
        },
        paper: {
          0: "#FFFFFF",
          50: "#F4F5F1",
          100: "#ECEEE8",
        },
        line: "#E2E4DD",
        amber: {
          DEFAULT: "#C9842B",
          50: "#FBF1E3",
          600: "#A8691B",
        },
        teal: {
          DEFAULT: "#1C7C72",
          50: "#E7F3F1",
        },
        violet: {
          DEFAULT: "#6E5A9E",
          50: "#EFEBF7",
        },
      },
      fontFamily: {
        serif: ["'Source Serif 4'", "'Noto Serif SC'", "serif"],
        sans: ["'Inter'", "'PingFang SC'", "'Noto Sans SC'", "sans-serif"],
        mono: ["'IBM Plex Mono'", "'JetBrains Mono'", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(20,24,31,0.04), 0 1px 1px rgba(20,24,31,0.03)",
      },
    },
  },
  plugins: [],
};
