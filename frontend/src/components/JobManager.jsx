import React from 'react';
import './JobManager.css';

// --- Helper Functions ---
export const getStatusColor = (status) => {
    switch (status) {
        case 'running': return '#2196f3';
        case 'completed': return '#4caf50';
        case 'failed': return '#f44336';
        case 'cancelled': return '#ff9800';
        default: return '#9e9e9e';
    }
};

export const getStatusIcon = (status) => {
    switch (status) {
        case 'running': return '⏳';
        case 'completed': return '✅';
        case 'failed': return '❌';
        case 'cancelled': return '⚠️';
        default: return '⏸️';
    }
};

export const formatDate = (dateString) => {
    if (!dateString) return 'Unknown';
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
};

// --- Components ---

export const JobSidebar = ({
    jobs,
    selectedJobId,
    onJobClick,
    loading,
    onRefresh,
    title = "Recent Jobs"
}) => {
    return (
        <div className="jobs-section">
            <div className="jobs-section-header">
                <h3>{title}</h3>
                <button
                    className="refresh-btn"
                    onClick={onRefresh}
                    disabled={loading}
                    title="Refresh Jobs"
                >
                    🔄 {loading ? 'Loading...' : 'Refresh'}
                </button>
            </div>

            <div className="jobs-list-container">
                {(!jobs || jobs.length === 0) ? (
                    <div className="jobs-empty">
                        <div className="jobs-empty-icon">📋</div>
                        <div>No recent jobs</div>
                        <div style={{ fontSize: '12px', color: '#999', marginTop: '4px' }}>
                            Start a pipeline to see jobs here
                        </div>
                    </div>
                ) : (
                    jobs.map(job => (
                        <div
                            key={job.job_id}
                            className={`job-item ${job.status} ${selectedJobId === job.job_id ? 'selected' : ''}`}
                            onClick={() => onJobClick(job)}
                        >
                            <div className="job-header">
                                <div className="job-info-primary">
                                    <span className="job-status-icon" style={{ color: getStatusColor(job.status) }}>
                                        {getStatusIcon(job.status)}
                                    </span>
                                    <span className="job-id" title={job.job_id}>{job.job_id}</span>
                                    {job.pipeline_type && (
                                        <span className="job-type-badge">{job.pipeline_type}</span>
                                    )}
                                </div>
                                <span className="job-time">{formatDate(job.created_at)}</span>
                            </div>

                            {/* Running Progress */}
                            {job.status === 'running' && (
                                <div className="job-progress-container">
                                    <div className="job-progress-bar-track">
                                        <div
                                            className="job-progress-bar-fill"
                                            style={{
                                                width: `${(job.progress || 0) * 100}%`,
                                                backgroundColor: getStatusColor(job.status)
                                            }}
                                        />
                                    </div>
                                    <div className="job-progress-text">
                                        {job.processed_count || 0} / {job.total_count || '?'} items
                                    </div>
                                </div>
                            )}

                            {/* Completed Results Mini */}
                            {job.status === 'completed' && job.results && (
                                <div className="job-results-mini">
                                    <span className="result-tag success">✓ {job.results.processed || 0}</span>
                                    {job.results.failed > 0 && (
                                        <span className="result-tag failed">✗ {job.results.failed}</span>
                                    )}
                                    {job.results.duration_seconds && (
                                        <span className="result-tag duration">⏱ {job.results.duration_seconds.toFixed(1)}s</span>
                                    )}
                                </div>
                            )}

                            {/* Failed Message */}
                            {job.status === 'failed' && (
                                <div className="job-error-preview">
                                    {job.message || 'Pipeline failed'}
                                </div>
                            )}
                        </div>
                    ))
                )}
            </div>
        </div>
    );
};

export const JobDetails = ({ job, onClose }) => {
    if (!job) return null;

    return (
        <div className="job-details-panel">
            <div className="job-details-header">
                <h3>Job Details: <span style={{ fontFamily: 'monospace' }}>{job.job_id}</span></h3>
                <button className="close-details-btn" onClick={onClose}>
                    ✕ Close
                </button>
            </div>

            <div className="job-details-content">
                {/* Status Card */}
                <div className="detail-card">
                    <h4>Status & Config</h4>
                    <div className="detail-row">
                        <span className="detail-label">Status:</span>
                        <span className="detail-value" style={{ color: getStatusColor(job.status), fontWeight: 600 }}>
                            {getStatusIcon(job.status)} {job.status.toUpperCase()}
                        </span>
                    </div>
                    <div className="detail-row">
                        <span className="detail-label">Type:</span>
                        <span className="detail-value">{job.pipeline_type}</span>
                    </div>
                    <div className="detail-row">
                        <span className="detail-label">Created:</span>
                        <span className="detail-value">{new Date(job.created_at).toLocaleString()}</span>
                    </div>
                    {job.updated_at && (
                        <div className="detail-row">
                            <span className="detail-label">Last Updated:</span>
                            <span className="detail-value">{new Date(job.updated_at).toLocaleString()}</span>
                        </div>
                    )}
                </div>

                {/* Results Stats */}
                {job.results && (
                    <div className="stats-grid">
                        <div className="stat-box success">
                            <span className="value">{job.results.processed || 0}</span>
                            <span className="label">Processed</span>
                        </div>
                        <div className="stat-box failed">
                            <span className="value">{job.results.failed || 0}</span>
                            <span className="label">Failed</span>
                        </div>
                        <div className="stat-box skipped">
                            <span className="value">{job.results.skipped || 0}</span>
                            <span className="label">Skipped</span>
                        </div>
                        <div className="stat-box duration">
                            <span className="value">
                                {typeof job.results.duration_seconds === 'number' ? job.results.duration_seconds.toFixed(1) : '0.0'}s
                            </span>
                            <span className="label">Duration</span>
                        </div>
                    </div>
                )}

                {/* Failure Details */}
                {job.results?.failed_details && job.results.failed_details.length > 0 && (
                    <div className="detail-card" style={{ borderColor: '#f44336' }}>
                        <h4 style={{ color: '#d32f2f', borderBottomColor: '#ffcdd2' }}>Failure Details</h4>
                        <div className="failure-list">
                            {job.results.failed_details.map((item, idx) => (
                                <div key={idx} className="failure-item">
                                    <div><strong>ID:</strong> <code style={{ userSelect: 'all' }}>{item.id}</code></div>
                                    <div style={{ marginTop: '4px' }}>{item.error}</div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Error Message for top-level failure */}
                {job.status === 'failed' && job.message && (
                    <div className="detail-card" style={{ borderColor: '#f44336', backgroundColor: '#ffebee' }}>
                        <h4 style={{ color: '#d32f2f', borderBottomColor: '#ffcdd2' }}>Error Message</h4>
                        <div style={{ color: '#c62828', fontSize: '13px' }}>{job.message}</div>
                    </div>
                )}

            </div>
        </div>
    );
};

export default { JobSidebar, JobDetails, getStatusColor, getStatusIcon, formatDate };
