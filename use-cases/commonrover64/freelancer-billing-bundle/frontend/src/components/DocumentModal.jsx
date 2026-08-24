function DocumentModal({ title, onClose, children }) {
    return (
        <div className="modal-backdrop" onClick={onClose}>
            <div
                className="modal-card card"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="modal-header">
                    <h3>{title}</h3>
                    <button className="btn modal-close" onClick={onClose}>
                        x
                    </button>
                </div>
                {children}
            </div>
        </div>
    );
}

export default DocumentModal;
