import React, { useState, useEffect } from 'react'
import { fetchOutcomeImpacts } from '../api/graphApi'
import './OutcomeImpactPanel.css'

/**
 * Panel showing impacts that affect a specific outcome event
 */
function OutcomeImpactPanel({ outcome, onClose }) {
  const [impacts, setImpacts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [minConfidence, setMinConfidence] = useState(0)
  const [filterDirection, setFilterDirection] = useState(null)

  // Load impacts
  useEffect(() => {
    const loadImpacts = async () => {
      if (!outcome || !outcome.id) return

      setLoading(true)
      setError(null)

      try {
        const data = await fetchOutcomeImpacts(
          outcome.id,
          minConfidence > 0 ? minConfidence : null,
          filterDirection
        )
        setImpacts(data)
      } catch (err) {
        setError(err.message)
        console.error('Failed to load impacts:', err)
      } finally {
        setLoading(false)
      }
    }

    loadImpacts()
  }, [outcome, minConfidence, filterDirection])

  if (!outcome) return null

  // Get direction icon and color
  const getDirectionInfo = (direction) => {
    switch (direction) {
      case 'positive':
        return { icon: '↗', color: '#22c55e', label: 'Positive' }
      case 'negative':
        return { icon: '↘', color: '#ef4444', label: 'Negative' }
      case 'mixed':
        return { icon: '↔', color: '#a855f7', label: 'Mixed' }
      case 'neutral':
        return { icon: '→', color: '#94a3b8', label: 'Neutral' }
      default:
        return { icon: '?', color: '#6c757d', label: 'Unknown' }
    }
  }

  return (
    <div className="outcome-impact-panel">
      {/* Header */}
      <div className="outcome-panel-header">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
            <span style={{ fontSize: '18px' }}>⭐</span>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '600', color: '#333' }}>
              Outcome Event
            </h3>
          </div>
          <p style={{ margin: '4px 0 0 0', fontSize: '13px', color: '#666' }}>
            {outcome.name || outcome.label || outcome.id}
          </p>
          {outcome.properties?.outcome_scenario && (
            <span style={{
              display: 'inline-block',
              padding: '2px 8px',
              backgroundColor: '#ffc107',
              color: '#333',
              borderRadius: '12px',
              fontSize: '11px',
              fontWeight: '600',
              marginTop: '6px'
            }}>
              {outcome.properties.outcome_scenario}
            </span>
          )}
          {outcome.properties?.is_actual_outcome && (
            <span style={{
              display: 'inline-block',
              padding: '2px 8px',
              backgroundColor: '#4CAF50',
              color: '#fff',
              borderRadius: '12px',
              fontSize: '11px',
              fontWeight: '600',
              marginLeft: '6px',
              marginTop: '6px'
            }}>
              Actual Outcome
            </span>
          )}
        </div>
        <button onClick={onClose} className="outcome-panel-close">×</button>
      </div>

      {/* Filters */}
      <div className="outcome-panel-filters">
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 auto', minWidth: '120px' }}>
            <label style={{ fontSize: '11px', color: '#666', display: 'block', marginBottom: '4px' }}>
              Min Confidence
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={minConfidence}
              onChange={(e) => setMinConfidence(parseFloat(e.target.value))}
              style={{ width: '100%' }}
            />
            <span style={{ fontSize: '11px', color: '#666' }}>{(minConfidence * 100).toFixed(0)}%</span>
          </div>
          <div style={{ flex: '1 1 auto', minWidth: '120px' }}>
            <label style={{ fontSize: '11px', color: '#666', display: 'block', marginBottom: '4px' }}>
              Direction
            </label>
            <select
              value={filterDirection || ''}
              onChange={(e) => setFilterDirection(e.target.value || null)}
              style={{
                width: '100%',
                padding: '4px 8px',
                fontSize: '12px',
                borderRadius: '4px',
                border: '1px solid #ced4da'
              }}
            >
              <option value="">All</option>
              <option value="positive">Positive</option>
              <option value="negative">Negative</option>
              <option value="mixed">Mixed</option>
              <option value="neutral">Neutral</option>
            </select>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="outcome-panel-content">
        {loading && (
          <div style={{ padding: '20px', textAlign: 'center', color: '#6c757d' }}>
            Loading impacts...
          </div>
        )}

        {error && (
          <div style={{ padding: '20px', textAlign: 'center', color: '#dc3545' }}>
            Error: {error}
          </div>
        )}

        {!loading && !error && impacts.length === 0 && (
          <div style={{ padding: '20px', textAlign: 'center', color: '#6c757d', fontStyle: 'italic' }}>
            No impacts recorded for this outcome.
          </div>
        )}

        {!loading && !error && impacts.length > 0 && (
          <div className="impacts-list">
            <div style={{
              fontSize: '12px',
              fontWeight: '600',
              color: '#495057',
              marginBottom: '12px',
              padding: '0 4px'
            }}>
              {impacts.length} Impact{impacts.length !== 1 ? 's' : ''} Found
            </div>

            {impacts.map((impact, index) => {
              const dirInfo = getDirectionInfo(impact.properties?.impact_direction)
              const magnitude = impact.properties?.impact_magnitude || 0
              const confidence = impact.properties?.confidence || 0
              const reasoning = impact.properties?.reasoning || 'No reasoning provided'
              const evidenceCount = impact.properties?.evidence_count || 0
              const chainCount = impact.properties?.causal_chain_hypothesis_ids?.length || 0

              return (
                <div key={index} className="impact-card">
                  {/* Direction Badge */}
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    marginBottom: '8px'
                  }}>
                    <div style={{
                      width: '32px',
                      height: '32px',
                      borderRadius: '50%',
                      backgroundColor: dirInfo.color,
                      color: '#fff',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '16px',
                      fontWeight: '600'
                    }}>
                      {dirInfo.icon}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '13px', fontWeight: '600', color: '#333' }}>
                        {dirInfo.label} Impact
                      </div>
                      <div style={{ fontSize: '11px', color: '#6c757d' }}>
                        Magnitude: {(magnitude * 100).toFixed(0)}% • Confidence: {(confidence * 100).toFixed(0)}%
                      </div>
                    </div>
                  </div>

                  {/* Reasoning */}
                  <div style={{
                    fontSize: '12px',
                    color: '#495057',
                    lineHeight: '1.5',
                    marginBottom: '8px',
                    padding: '8px',
                    backgroundColor: '#f8f9fa',
                    borderRadius: '4px'
                  }}>
                    {reasoning}
                  </div>

                  {/* Metadata */}
                  <div style={{
                    display: 'flex',
                    gap: '12px',
                    fontSize: '11px',
                    color: '#6c757d'
                  }}>
                    {evidenceCount > 0 && (
                      <span>📄 {evidenceCount} evidence article{evidenceCount !== 1 ? 's' : ''}</span>
                    )}
                    {chainCount > 0 && (
                      <span>🔗 {chainCount} causal link{chainCount !== 1 ? 's' : ''}</span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default OutcomeImpactPanel
