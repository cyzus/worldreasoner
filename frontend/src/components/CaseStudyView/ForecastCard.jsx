import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const MODE_COLORS = {
    container: '#2b8a3e',
    real_time: '#e67700',
    knowledge_only: '#1c7ed6',
}

export function ForecastCard({ forecast: fc, groundTruth, onViewGraph, loadingGraphId }) {
    const [reasoningOpen, setReasoningOpen] = useState(false)
    const isLoadingGraph = loadingGraphId === fc.id
    const modeColor = MODE_COLORS[fc.mode] || '#495057'

    const modelLabel = fc.model_name
        ? `${fc.model_name}${fc.model_version ? ` (${fc.model_version})` : ''}`
        : null

    return (
        <div className="cs-forecast-card">
            {/* Header row: mode badge + correctness badge + P(Yes) */}
            <div className="cs-fc-header">
                <div className="cs-fc-header-left">
                    <span className="cs-fc-mode" style={{ color: modeColor, borderColor: modeColor }}>
                        {fc.mode.replace('_', ' ')}
                    </span>
                    {fc.enabled_tools?.length > 0 && (
                        <span className="cs-fc-tools">
                            🔧 {fc.enabled_tools.join(', ')}
                        </span>
                    )}
                </div>
                <div className="cs-fc-header-right">
                    {groundTruth != null && groundTruth !== '' && (
                        <span className="cs-fc-ground-truth-inline" title="Ground truth answer">
                            Truth: <strong>{String(groundTruth)}</strong>
                        </span>
                    )}
                    {fc.is_correct != null ? (
                        <span className={`cs-fc-correctness ${fc.is_correct ? 'correct' : 'incorrect'}`}>
                            {fc.is_correct ? '✓ Correct' : '✗ Incorrect'}
                        </span>
                    ) : (
                        <span className="cs-fc-correctness unevaluated">— Not evaluated</span>
                    )}
                </div>
            </div>

            {/* Prediction row */}
            <div className="cs-fc-prediction-row">
                <span className="cs-fc-prediction-label">Predicted</span>
                <span className={`cs-fc-prediction-value ${fc.expected_outcome === 'Yes' ? 'yes' : fc.expected_outcome === 'No' ? 'no' : ''}`}>
                    {fc.expected_outcome ?? 'N/A'}
                </span>
                <span className="cs-fc-confidence">
                    {(fc.confidence * 100).toFixed(0)}% confident
                </span>
                {fc.brier_score != null && (
                    <span className="cs-fc-brier" title="Brier score — lower is better (0 = perfect, 1 = worst)">
                        Brier: {fc.brier_score.toFixed(3)}
                    </span>
                )}
            </div>

            {/* Meta row: model, simulated date, articles */}
            <div className="cs-fc-meta-row">
                {modelLabel && <span>{modelLabel}</span>}
                {fc.simulated_date && (
                    <span>As of {new Date(fc.simulated_date).toLocaleDateString()}</span>
                )}
                {fc.articles_accessed_count > 0 && (
                    <span className="cs-fc-articles-count">
                        📄 {fc.articles_accessed_count} articles
                    </span>
                )}
            </div>

            {/* Reasoning toggle */}
            {fc.reasoning && (
                <details
                    className="cs-fc-reasoning-details"
                    open={reasoningOpen}
                    onToggle={(e) => setReasoningOpen(e.target.open)}
                >
                    <summary>Reasoning</summary>
                    <div className="cs-fc-rationale markdown-body">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{fc.reasoning}</ReactMarkdown>
                    </div>
                </details>
            )}

            {/* Footer */}
            <div className="cs-fc-footer">
                <button
                    className="cs-btn-view-graph"
                    onClick={() => onViewGraph(fc.id)}
                    disabled={isLoadingGraph}
                >
                    {isLoadingGraph ? 'Loading...' : '🔍 View Reasoning Graph'}
                </button>
                {fc.created_at && (
                    <span className="cs-fc-timestamp">
                        {new Date(fc.created_at).toLocaleString()}
                    </span>
                )}
            </div>
        </div>
    )
}
