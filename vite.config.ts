import { resolve } from "path"
import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"

// https://vitejs.dev/config/
export default defineConfig({
  root: resolve("./assets/vue/"),
  base: "/static/",
  plugins: [vue()],
  resolve: {
    extensions: [".js", ".ts", ".json"],
  },
  build: {
    outDir: resolve("./dist/vue"),
    manifest: true,
    rollupOptions: {
      input: {
        main: resolve("./assets/vue/main.ts"),
      },
    },
  },
})
