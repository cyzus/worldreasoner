import React from 'react'
import ReactMarkdown from 'react-markdown'

export function ForecastComparison({
    selectedQuestion,
    forecasts,
    onViewForecastGraph,
    loadingGraph
}) {
    return (
        <div className="cs-section">
            <h3 className="cs-section-title">📊 Forecast Comparison</h3>
            <p className="cs-section-subtitle">How different evaluation conditions performed on this question</p>

            {selectedQuestion?.ground_truth != null && selectedQuestion.ground_truth !== '' && (
                <div className="cs-ground-truth-banner">
                    <span className="cs-badge-ground-truth">✓ Ground Truth</span>
                    <span className="cs-ground-truth-value">{String(selectedQuestion.ground_truth)}</span>
                </div>
            )}

            {!forecasts || forecasts.length === 0 ? (
                <div className="cs-empty">No forecasts available for this question.</div>
            ) : (
                <div className="cs-forecast-cards">
                    {forecasts.map(fc => (
                        <div key={fc.id} className="cs-forecast-card">
                            <div className="cs-fc-header">
                                <span className="cs-fc-mode">{fc.mode}</span>
                                <span className="cs-fc-prob">
                                    {fc.probability !== null ? `${(fc.probability * 100).toFixed(1)}%` : 'N/A'}
                                </span>
                            </div>
                            {fc.expected_outcome && (
                                <div className="cs-fc-outcome">
                                    <strong>Prediction:</strong> {fc.expected_outcome}
                                </div>
                            )}
                            {fc.rationale && (
                                <div className="cs-fc-rationale markdown-body">
                                    <ReactMarkdown>{fc.rationale}</ReactMarkdown>
                                </div>
                            )}
                            <div className="cs-fc-footer">
                                <button
                                    className="cs-btn-view-graph"
                                    onClick={() => onViewForecastGraph(fc.id)}
                                    disabled={loadingGraph}
                                >
                                    {loadingGraph ? 'Loading...' : '🔍 View Reasoning Graph'}
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
