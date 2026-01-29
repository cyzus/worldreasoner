import React, { useState, useEffect, useRef } from 'react'
import {
    useEvidenceNeeds,
    useModelStats,
    useForecastReadiness,
    useSatisfaction
} from '../hooks/useQuestionMonitor'
import { startPipeline } from '../api/monitorApi'
import './QuestionMonitor.css'

const QuestionMonitor = () => {
    const { data: evidenceNeeds, loading: needsLoading, error: needsError, refetch: refetchNeeds } = useEvidenceNeeds()
    const { data: modelStats, loading: statsLoading } = useModelStats()
    const [selectedQuestion, setSelectedQuestion] = useState(null)
    const [activeTab, setActiveTab] = useState('needs')
    const [collecting, setCollecting] = useState({})
    const [collectingAll, setCollectingAll] = useState(false)

    // Auto-collect state
    const [autoCollect, setAutoCollect] = useState(false)
    const autoCollectRef = useRef(null)

    // Auto-collect logic
    useEffect(() => {
        if (autoCollect) {
            const checkAndCollect = async () => {
                // Only collect if we have needs, aren't loading, and aren't already collecting
                if (!needsLoading && evidenceNeeds && evidenceNeeds.length > 0 && !collectingAll) {
                    console.log(`[Auto-Collect] Triggering collection for ${evidenceNeeds.length} items`)
                    await handleCollectAll(true) // Pass true to bypass confirm
                }
            }

            // Check immediately on enable/update
            checkAndCollect()

            // And then interval
            autoCollectRef.current = setInterval(checkAndCollect, 10000) // Check every 10s
        } else {
            if (autoCollectRef.current) {
                clearInterval(autoCollectRef.current)
                autoCollectRef.current = null
            }
        }

        return () => {
            if (autoCollectRef.current) clearInterval(autoCollectRef.current)
        }
    }, [autoCollect, needsLoading, evidenceNeeds, collectingAll])

    // Helper to safely format dates
    const formatDate = (dateString) => {
        if (!dateString) return 'N/A'
        try {
            return new Date(dateString).toLocaleDateString()
        } catch (e) {
            return 'Invalid Date'
        }
    }

    const handleCollect = async (questionId) => {
        try {
            setCollecting(prev => ({ ...prev, [questionId]: true }))
            await startPipeline([questionId], 'adaptive_evidence')
        } catch (err) {
            console.error('Failed to start collection:', err)
            alert(`Failed to start collection: ${err.message}`)
        } finally {
            setTimeout(() => {
                setCollecting(prev => ({ ...prev, [questionId]: false }))
            }, 2000)
        }
    }

    const handleCollectAll = async (bypassConfirm = false) => {
        if (!evidenceNeeds || evidenceNeeds.length === 0) return

        const allIds = evidenceNeeds.map(q => q.id)

        if (!bypassConfirm) {
            const confirmMsg = `Start adaptive evidence collection for ${allIds.length} questions?`
            if (!window.confirm(confirmMsg)) return
        }

        try {
            setCollectingAll(true)
            await startPipeline(allIds, 'adaptive_evidence')
            if (!bypassConfirm) {
                alert(`Started batch collection for ${allIds.length} questions`)
            }
        } catch (err) {
            console.error('Failed to start batch collection:', err)
            if (!bypassConfirm) alert(`Failed to start batch collection: ${err.message}`)
        } finally {
            // Keep "collecting" state true for a bit to prevent immediate re-trigger
            setTimeout(() => {
                setCollectingAll(false)
                refetchNeeds() // Refresh list after starting
            }, 5000)
        }
    }

    return (
        <div className="monitor-container">
            <div className="monitor-header">
                <h2>Monitor & Status</h2>
                <div className="monitor-controls">
                    <button
                        className={`monitor-btn ${activeTab === 'needs' ? 'active' : 'inactive'}`}
                        onClick={() => setActiveTab('needs')}
                    >
                        Evidence Needs
                    </button>
                    <button
                        className={`monitor-btn ${activeTab === 'stats' ? 'active' : 'inactive'}`}
                        onClick={() => setActiveTab('stats')}
                    >
                        Model Usage
                    </button>
                    <button
                        className="monitor-btn refresh-btn"
                        onClick={refetchNeeds}
                    >
                        ↻ Refresh
                    </button>
                </div>
            </div>

            {activeTab === 'needs' && (
                <div className="needs-section">
                    {needsLoading && <div className="loading-text">Loading evidence needs...</div>}
                    {needsError && <div className="error-text">Error: {needsError.message}</div>}

                    {!needsLoading && evidenceNeeds && (
                        <div className="card">
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                                <h3 className="card-title" style={{ margin: 0 }}>Pending Evidence Collection ({evidenceNeeds.length})</h3>

                                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                                    {/* Auto Collect Toggle */}
                                    <label className="auto-collect-toggle" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', userSelect: 'none' }}>
                                        <input
                                            type="checkbox"
                                            checked={autoCollect}
                                            onChange={(e) => setAutoCollect(e.target.checked)}
                                            style={{ width: '1.25rem', height: '1.25rem' }}
                                        />
                                        <span style={{ fontWeight: 500, color: autoCollect ? '#2563eb' : '#4b5563' }}>
                                            Auto-Collect {autoCollect ? '(ON)' : '(OFF)'}
                                        </span>
                                    </label>

                                    {evidenceNeeds.length > 0 && (
                                        <button
                                            className="action-btn"
                                            style={{
                                                backgroundColor: '#2563eb',
                                                color: 'white',
                                                padding: '0.5rem 1rem',
                                                borderRadius: '0.375rem',
                                                textDecoration: 'none'
                                            }}
                                            onClick={() => handleCollectAll(false)}
                                            disabled={collectingAll || autoCollect}
                                        >
                                            {collectingAll ? 'Starting Batch...' : 'Collect All'}
                                        </button>
                                    )}
                                </div>
                            </div>
                            <div className="monitor-table-container">
                                <table className="monitor-table">
                                    <thead>
                                        <tr>
                                            <th style={{ width: '40%' }}>Question</th>
                                            <th>Domain</th>
                                            <th>Created</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {evidenceNeeds.map(q => (
                                            <tr key={q.id}>
                                                <td>
                                                    <div className="question-text" title={q.question_text}>
                                                        {q.question_text}
                                                    </div>
                                                    <div className="question-id">{q.id}</div>
                                                </td>
                                                <td>
                                                    <span className="domain-badge">
                                                        {q.domain}
                                                    </span>
                                                </td>
                                                <td className="date-text">
                                                    {formatDate(q.created_at)}
                                                </td>
                                                <td>
                                                    <div style={{ display: 'flex', gap: '0.75rem' }}>
                                                        <button
                                                            className="action-btn"
                                                            style={{ color: '#2563eb' }}
                                                            onClick={() => handleCollect(q.id)}
                                                            disabled={collecting[q.id] || autoCollect}
                                                        >
                                                            {collecting[q.id] ? 'Starting...' : 'Collect'}
                                                        </button>
                                                        <button
                                                            className="action-btn"
                                                            onClick={() => setSelectedQuestion(q.id)}
                                                        >
                                                            Check Readiness
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'stats' && (
                <div className="stats-section">
                    {statsLoading && <div>Loading model stats...</div>}
                    {!statsLoading && modelStats && (
                        <div className="stats-grid">
                            {modelStats.map(stat => (
                                <div key={stat.model_name} className="stat-card">
                                    <h3>{stat.model_name}</h3>
                                    <div className="stat-details">
                                        <span className="stat-label">Forecasts:</span>
                                        <span className="stat-value">{stat.forecast_count}</span>

                                        <span className="stat-label">Accuracy:</span>
                                        <span className="stat-value">{(stat.accuracy * 100).toFixed(1)}% ({stat.correct_count} correct)</span>

                                        <span className="stat-label">Avg Confidence:</span>
                                        <span className="stat-value">{(stat.avg_confidence * 100).toFixed(1)}%</span>

                                        <span className="stat-label">Brier Score:</span>
                                        <span className="stat-value">{stat.avg_brier_score?.toFixed(3) || 'N/A'}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Selected Question Detail Modal/Panel */}
            {selectedQuestion && (
                <ForecastReadinessPanel
                    questionId={selectedQuestion}
                    onClose={() => setSelectedQuestion(null)}
                />
            )}
        </div>
    )
}


const ForecastReadinessPanel = ({ questionId, onClose }) => {
    const { data: readiness, loading } = useForecastReadiness(questionId)
    const { data: satisfaction } = useSatisfaction(questionId)

    return (
        <div className="modal-overlay">
            <div className="modal-content">
                <button onClick={onClose} className="close-btn">✕</button>

                <h3 className="card-title">Readiness Check: {questionId}</h3>

                {loading && <div>Checking readiness...</div>}

                {!loading && readiness && (
                    <div>
                        <div className={`readiness-status ${readiness.available_modes.includes('container') ? 'status-green' : 'status-yellow'}`}>
                            <div style={{ fontWeight: 600, marginBottom: '0.5rem' }}>Available Modes</div>
                            <div className="modes-list">
                                {readiness.available_modes.map(mode => (
                                    <span key={mode} className="mode-tag">{mode}</span>
                                ))}
                            </div>
                        </div>

                        {satisfaction && (
                            <div className="satisfaction-card">
                                <div style={{ fontWeight: 600, marginBottom: '0.5rem' }}>Evidence Satisfaction</div>
                                <div className="satisfaction-grid">
                                    <span className="stat-label">Status:</span>
                                    <span className={satisfaction.is_satisfied ? 'text-success' : 'text-danger'}>
                                        {satisfaction.is_satisfied ? 'Satisfied' : 'Unsatisfied'}
                                    </span>

                                    <span className="stat-label">Articles:</span>
                                    <span>{satisfaction.article_count} (Need {satisfaction.missing_requirements.includes('articles') ? 'More' : 'OK'})</span>

                                    <span className="stat-label">Hypotheses:</span>
                                    <span>{satisfaction.hypothesis_count}</span>

                                    <span className="stat-label">Graph Depth:</span>
                                    <span>{satisfaction.graph_depth}</span>
                                </div>

                                {satisfaction.missing_requirements.length > 0 && (
                                    <div style={{ marginTop: '0.5rem', color: '#dc2626', fontSize: '0.875rem' }}>
                                        Missing: {satisfaction.missing_requirements.join(', ')}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}

export default QuestionMonitor
