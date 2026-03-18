import React, { useState } from 'react'
import { useQuestionForecasts, useForecastGraph } from '../../hooks/queries/useForecastQueries'
import { ForecastCard } from './ForecastCard'
import { ForecastGraphModal } from './ForecastGraphModal'

export function ForecastTab({ selectedQuestion }) {
    const [activeForecastId, setActiveForecastId] = useState(null)

    const { data: forecasts = [], isLoading, isError } = useQuestionForecasts(selectedQuestion?.id)
    const { data: activeForecastGraph, isFetching: loadingGraph } = useForecastGraph(activeForecastId)

    const groundTruth = selectedQuestion?.ground_truth

    if (isLoading) {
        return <div className="cs-empty">Loading forecasts...</div>
    }

    if (isError) {
        return <div className="cs-empty" style={{ color: '#c92a2a' }}>Failed to load forecasts.</div>
    }

    if (forecasts.length === 0) {
        return <div className="cs-empty">No forecasts yet for this question.</div>
    }

    return (
        <div className="cs-forecast-tab">
            <div className="cs-forecast-list-header">
                <span className="cs-forecast-count">{forecasts.length} forecast{forecasts.length !== 1 ? 's' : ''}</span>
                {groundTruth != null && groundTruth !== '' && (
                    <div className="cs-ground-truth-banner">
                        <span className="cs-badge-ground-truth">✓ Ground Truth</span>
                        <span className="cs-ground-truth-value">{String(groundTruth)}</span>
                    </div>
                )}
            </div>

            <div className="cs-forecast-list">
                {forecasts.map(fc => (
                    <ForecastCard
                        key={fc.id}
                        forecast={fc}
                        groundTruth={groundTruth}
                        onViewGraph={setActiveForecastId}
                        loadingGraphId={loadingGraph ? activeForecastId : null}
                    />
                ))}
            </div>

            <ForecastGraphModal
                activeForecastGraph={activeForecastGraph}
                onClose={() => setActiveForecastId(null)}
            />
        </div>
    )
}
