import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => ({
    plugins: [react()],
    esbuild: mode === 'production' ? { drop: ['console', 'debugger'] } : {},
    optimizeDeps: {
        include: ['react-grid-layout'],
    },
    build: {
        // Use Vite/Rollup default chunking to avoid runtime order issues between React and chart libs.
        chunkSizeWarningLimit: 1500,
        rollupOptions: {
            output: {
                // Manual chunk splitting keeps the initial bundle small while
                // grouping libraries that travel together. React must stay in
                // its own chunk so chart libraries (Recharts/Plotly) load it
                // synchronously before evaluating their bundles.
                manualChunks(id) {
                    if (!id.includes('node_modules')) return undefined
                    if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return 'vendor-react'
                    if (/[\\/]node_modules[\\/](react-router|react-router-dom|history)[\\/]/.test(id)) return 'vendor-router'
                    if (/[\\/]node_modules[\\/](echarts|echarts-for-react|zrender)[\\/]/.test(id)) return 'vendor-echarts'
                    if (/[\\/]node_modules[\\/](recharts|d3-|victory-vendor|decimal.js-light|es-toolkit)[\\/]/.test(id)) return 'vendor-charts'
                    if (/[\\/]node_modules[\\/](lucide-react|react-icons)[\\/]/.test(id)) return 'vendor-icons'
                    if (/[\\/]node_modules[\\/](i18next|react-i18next|i18next-browser-languagedetector)[\\/]/.test(id)) return 'vendor-i18n'
                    if (/[\\/]node_modules[\\/](axios)[\\/]/.test(id)) return 'vendor-api'
                    if (/[\\/]node_modules[\\/](@mui|@emotion|@mantine)[\\/]/.test(id)) return 'vendor-ui'
                    if (/[\\/]node_modules[\\/](dayjs|date-fns|luxon|moment|react-datepicker)[\\/]/.test(id)) return 'vendor-date'
                    if (/[\\/]node_modules[\\/](react-grid-layout|react-resizable|react-draggable|react-window|react-virtualized-auto-sizer)[\\/]/.test(id)) return 'vendor-grid'
                    if (/[\\/]node_modules[\\/](xlsx|jspdf|html2canvas|file-saver)[\\/]/.test(id)) return 'vendor-export'
                    return 'vendor'
                },
            },
        },
    },
    server: {
        port: 5173,
        proxy: {
            '/api': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                ws: true
            },
            '/uploads': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            }
        }
    }
}))
