import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

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
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                    <span className="cs-fc-mode">{fc.mode}</span>
                                    {fc.enabled_tools?.length > 0 && (
                                        <span style={{ fontSize: '11px', color: '#666' }}>
                                            🔧 {fc.enabled_tools.join(', ')}
                                        </span>
                                    )}
                                </div>
                                <div style={{ textAlign: 'right' }}>
                                    <div className="cs-fc-prob" title="Probability assigned to the 'Yes' outcome">
                                        {fc.probability != null ? `${(fc.probability * 100).toFixed(1)}%` : 'N/A'}
                                    </div>
                                    <div style={{ fontSize: '10px', color: '#868e96', marginTop: '2px' }}>P(Yes)</div>
                                </div>
                            </div>

                            <div className="cs-fc-prediction-row">
                                <span className="cs-fc-prediction-label">Prediction</span>
                                <span className={`cs-fc-prediction-value ${fc.expected_outcome === 'Yes' ? 'yes' : fc.expected_outcome === 'No' ? 'no' : ''}`}>
                                    {fc.expected_outcome ?? 'N/A'}
                                </span>
                                <span className="cs-fc-confidence" title="Model's confidence in its own prediction">
                                    {(fc.confidence * 100).toFixed(0)}% confident
                                </span>
                            </div>

                            {fc.is_correct != null && (
                                <div className={`cs-fc-correctness ${fc.is_correct ? 'correct' : 'incorrect'}`}>
                                    {fc.is_correct ? '✓ Correct' : '✗ Incorrect'}
                                </div>
                            )}

                            {fc.simulated_date && (
                                <div style={{ fontSize: '11px', color: '#868e96', marginBottom: '8px' }}>
                                    Forecasted as of {new Date(fc.simulated_date).toLocaleDateString()}
                                </div>
                            )}

                            {fc.reasoning && (
                                <details className="cs-fc-reasoning-details">
                                    <summary>Reasoning</summary>
                                    <div className="cs-fc-rationale markdown-body">
                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{fc.reasoning}</ReactMarkdown>
                                    </div>
                                </details>
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
