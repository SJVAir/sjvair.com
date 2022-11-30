import { resolve } from "path"
import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"

// https://vitejs.dev/config/
export default defineConfig({
  root: resolve("./assets/vue/"),
  base: "/static/vue/",
  envDir: resolve("./"),
  clearScreen: false,
  plugins: [vue()],
    server: {
    host: 'localhost',
    port: 3000,
    open: false,
    watch: {
      usePolling: true,
      disableGlobbing: false,
    },
  },
  resolve: {
    extensions: [".js", ".ts", ".json"],
  },
  build: {
    outDir: resolve("./dist/vue"),
    manifest: true,
    //sourcemap: true,
    rollupOptions: {
      input: {
        main: resolve("./assets/vue/main.ts"),
        D3Background: resolve("./assets/vue/services/D3Background.ts"),
        MonitorsBackground: resolve("assets/vue/services/MonitorsBackground.ts")
      }
    },
  },
  worker: {
    rollupOptions: {
      external: [
        "leaflet",
        "leaflet-svg-shape-markers"
      ]
    }
  }
})
