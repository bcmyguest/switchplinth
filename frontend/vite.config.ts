import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { PRODUCT_NAME } from './src/brand'

export default defineConfig({
  plugins: [react(), tailwindcss(), { name: 'product-name', transformIndexHtml: (html) => html.replaceAll('%PRODUCT_NAME%', PRODUCT_NAME) }],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/node_modules/@xyflow/')) return 'graph'
          if (id.includes('/node_modules/react/') || id.includes('/node_modules/react-dom/')) return 'react'
          if (id.includes('/node_modules/yaml/')) return 'yaml'
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
})
