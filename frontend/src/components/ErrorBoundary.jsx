import React from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import i18next from 'i18next'

class ErrorBoundaryInner extends React.Component {
    constructor(props) {
        super(props)
        this.state = { hasError: false, error: null }
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error }
    }

    componentDidCatch(error, errorInfo) {
        console.error('ErrorBoundary caught:', error, errorInfo)
    }

    handleReset = () => {
        this.setState({ hasError: false, error: null })
        const { navigate, previousPath } = this.props
        if (previousPath) {
            navigate(previousPath, { replace: true })
        }
    }

    handleGoHome = () => {
        this.setState({ hasError: false, error: null })
        this.props.navigate('/dashboard', { replace: true })
    }

    render() {
        if (this.state.hasError) {
            return (
                <div style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    minHeight: '60vh',
                    padding: '40px',
                    textAlign: 'center',
                    gap: '16px'
                }}>
                    <div style={{ fontSize: '48px' }}>⚠️</div>
                    <h2 style={{ margin: 0, color: 'var(--text-primary)' }}>
                        {i18next.t('error_boundary.title', 'Something went wrong')}
                    </h2>
                    <p style={{ color: 'var(--text-secondary)', maxWidth: '400px' }}>
                        {i18next.t('error_boundary.message', 'An unexpected error occurred. Please try again.')}
                    </p>
                    {this.state.error && (
                        <details style={{
                            background: 'var(--bg-secondary)',
                            padding: '12px 16px',
                            borderRadius: '8px',
                            maxWidth: '600px',
                            width: '100%',
                            textAlign: 'start',
                            fontSize: '12px',
                            color: 'var(--text-secondary)'
                        }}>
                            <summary style={{ cursor: 'pointer', marginBottom: '8px' }}>
                                {i18next.t('error_boundary.details', 'Error Details')}
                            </summary>
                            <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0 }}>
                                {this.state.error.toString()}
                            </pre>
                        </details>
                    )}
                    <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
                        <button
                            onClick={this.handleReset}
                            className="btn btn-outline-primary"
                        >
                            {i18next.t('error_boundary.try_again', 'Try Again')}
                        </button>
                        <button
                            onClick={this.handleGoHome}
                            className="btn btn-primary"
                        >
                            {i18next.t('error_boundary.go_home', 'Go to Dashboard')}
                        </button>
                    </div>
                </div>
            )
        }

        return this.props.children
    }
}

export default function ErrorBoundary({ children }) {
    const navigate = useNavigate()
    const location = useLocation()
    const previousPath = location.state?.from || location.pathname

    return (
        <ErrorBoundaryInner navigate={navigate} previousPath={previousPath}>
            {children}
        </ErrorBoundaryInner>
    )
}
