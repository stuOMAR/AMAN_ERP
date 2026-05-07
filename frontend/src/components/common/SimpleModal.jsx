import React from 'react';
import './SimpleModal.css'; // We'll create this css next

const SimpleModal = ({ isOpen, onClose, title, children, footer, size }) => {
    if (!isOpen) return null;

    const sizeStyles = {
        sm: { width: '400px' },
        md: { width: '600px' },
        lg: { width: '800px' },
        xl: { width: '1000px' },
    };

    return (
        <div className="modal-overlay">
            <div className="modal-content" style={sizeStyles[size] || {}}>
                <div className="modal-header">
                    <h3>{title}</h3>
                    <button className="close-button" onClick={onClose}>&times;</button>
                </div>
                <div className="modal-body">
                    {children}
                </div>
                {footer && (
                    <div className="modal-footer">
                        {footer}
                    </div>
                )}
            </div>
        </div>
    );
};

export default SimpleModal;
