import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: "index.html",
        videoAgent: "video-agent.html",
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/video-agent/test-setup.ts"],
    include: ["src/video-agent/**/*.test.{ts,tsx}"],
  },
});
