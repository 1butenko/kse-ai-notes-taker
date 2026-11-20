import path from "node:path"

import { defineConfig } from "vitest/config"

export default defineConfig({
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  test: {
    include: ["src/**/*.test.ts"],
    // @platejs/math imports KaTeX's CSS: let Vite, not Node, load it.
    server: { deps: { inline: [/@platejs\//, /katex/] } },
  },
})
