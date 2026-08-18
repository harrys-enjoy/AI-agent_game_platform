export default {
  content: ["./src/video-agent/**/*.{ts,tsx}", "./src/App.tsx"],
  corePlugins: { preflight: false },
  theme: {
    extend: {
      colors: {
        "brief-bg": "#f7f9f6",
        "brief-accent": "#397454",
        "brief-accent-dark": "#2f624b",
        "brief-border": "#dfe7e1",
        "brief-text": "#19352c",
        "brief-muted": "#75867f",
      },
    },
  },
  plugins: [],
};
