import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export function ForecastGraphModal({ activeForecastGraph, onClose }) {
    if (!activeForecastGraph) return null

    return (
        <div className="cs-modal-overlay" onClick={onClose}>
            <div className="cs-modal" onClick={e => e.stopPropagation()}>
                <div className="cs-modal-header">
                    <h3>Reasoning Graph: {activeForecastGraph.forecast_id}</h3>
                    <button className="cs-modal-close" onClick={onClose}>×</button>
                </div>
                <div className="cs-modal-body">
                    <div className="cs-graph-summary">
                        <div className="cs-stat"><strong>Events:</strong> {activeForecastGraph.events.length}</div>
                        <div className="cs-stat"><strong>Hypotheses:</strong> {activeForecastGraph.hypotheses.length}</div>
                    </div>
                    <div className="cs-graph-list">
                        <h4>Causal Relationships Found:</h4>
                        {activeForecastGraph.hypotheses.length === 0 ? (
                            <p>No explicit causal hypotheses recorded for this forecast.</p>
                        ) : (
                            activeForecastGraph.hypotheses.map(hyp => {
                                const src = activeForecastGraph.events.find(e => e.id === hyp.source_event_id)
                                const tgt = activeForecastGraph.events.find(e => e.id === hyp.target_event_id)
                                return (
                                    <div key={hyp.id} className="cs-hyp-item">
                                        <div className="cs-hyp-path">
                                            <span className="cs-hyp-node">{src?.title || hyp.source_event_id}</span>
                                            <span className="cs-hyp-arrow">⎯⎯ {hyp.relation_type} ({Math.round(hyp.strength * 100)}%) ⎯→</span>
                                            <span className="cs-hyp-node">{tgt?.title || hyp.target_event_id}</span>
                                        </div>
                                        <div className="cs-hyp-reasoning markdown-body">
                                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{hyp.reasoning}</ReactMarkdown>
                                        </div>
                                    </div>
                                )
                            })
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
