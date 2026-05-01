import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import { ToastProvider } from './context/ToastContext.jsx'
import { BranchProvider } from './context/BranchContext.jsx'
import { ThemeProvider } from './context/ThemeContext.jsx'
import './index.css'
// T8.3 — extracted from index.css to keep the global CSS source modular.
//   • cards.css   shared card styles (used across most pages).
//   • print.css   only matched by @media print, no render cost on screen.
import './styles/cards.css'
import './styles/print.css'
import './i18n'

ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
            <ThemeProvider>
                <ToastProvider>
                    <BranchProvider>
                        <App />
                    </BranchProvider>
                </ToastProvider>
            </ThemeProvider>
        </BrowserRouter>
    </React.StrictMode>,
)
