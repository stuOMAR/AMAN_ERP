import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { X, AlertTriangle, CheckCircle, Info, XCircle } from 'lucide-react';
import { toastEmitter } from '../utils/toastEmitter';
import './Toast.css';

const ToastContext = createContext(null);

const normalizeToastMessage = (message) => {
    if (message === null || message === undefined) return '';
    if (typeof message === 'string' || typeof message === 'number' || typeof message === 'boolean') {
        return String(message);
    }
    if (Array.isArray(message)) {
        return message
            .map(item => normalizeToastMessage(item))
            .filter(Boolean)
            .join(', ');
    }
    if (message instanceof Error) {
        return message.message;
    }
    if (typeof message === 'object') {
        return normalizeToastMessage(message.detail || message.message || message.msg) || JSON.stringify(message);
    }
    return String(message);
};

export const useToast = () => {
    const context = useContext(ToastContext);
    if (!context) {
        throw new Error('useToast must be used within a ToastProvider');
    }
    return context;
};

const Toast = ({ message, type = 'info', onClose }) => {
    const icons = {
        success: <CheckCircle size={20} />,
        error: <XCircle size={20} />,
        warning: <AlertTriangle size={20} />,
        info: <Info size={20} />
    };

    return (
        <div className={`toast toast-${type}`}>
            <span className="toast-icon">{icons[type]}</span>
            <span className="toast-message">{message}</span>
            <button className="toast-close" onClick={onClose}>
                <X size={16} />
            </button>
        </div>
    );
};

export const ToastProvider = ({ children }) => {
    const [toasts, setToasts] = useState([]);

    const showToast = useCallback((message, type = 'info', duration = 5000) => {
        const id = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
        setToasts(prev => [...prev, { id, message: normalizeToastMessage(message), type }]);

        if (duration > 0) {
            setTimeout(() => {
                setToasts(prev => prev.filter(t => t.id !== id));
            }, duration);
        }
    }, []);

    const removeToast = useCallback((id) => {
        setToasts(prev => prev.filter(t => t.id !== id));
    }, []);

    // Subscribe to global toast events from API interceptor
    useEffect(() => {
        const unsubscribe = toastEmitter.subscribe((message, type) => {
            showToast(message, type);
        });
        return unsubscribe;
    }, [showToast]);

    return (
        <ToastContext.Provider value={{ showToast }}>
            {children}
            <div className="toast-container">
                {toasts.map(toast => (
                    <Toast
                        key={toast.id}
                        message={toast.message}
                        type={toast.type}
                        onClose={() => removeToast(toast.id)}
                    />
                ))}
            </div>
        </ToastContext.Provider>
    );
};

export default ToastContext;
