import React, { useState, memo, useEffect } from 'react'
import { useDraggablePopup } from '../hooks/useDraggablePopup'
import { EventMetrics } from './EventDetails/EventMetrics'
import { RelatedArticles, RelatedQuestions } from './EventDetails/RelatedItems'
import { EventImpacts } from './EventDetails/EventImpacts'
import './EventDetails.css'

const EventDetails = memo(function EventDetails({ node, onClose }) {
  const [showArticles, setShowArticles] = useState(false)
  const [showQuestions, setShowQuestions] = useState(false)
  const [showImpacts, setShowImpacts] = useState(false)

  const { position, isDragging, handleMouseDown } = useDraggablePopup(node)

  // Reset toggles when node changes
  useEffect(() => {
    if (node) {
      setShowArticles(false)
      setShowQuestions(false)
      setShowImpacts(false)
    }
  }, [node?.id])

  if (!node) return null

  return (
    <div className="event-details" style={{
      maxWidth: '320px',
      maxHeight: '80vh',
      display: 'flex',
      flexDirection: 'column',
      position: 'fixed',
      left: position.x,
      top: position.y,
      zIndex: 1000,
      transform: 'translate(0, 0)',
      boxShadow: '0 8px 30px rgba(0,0,0,0.2)',
      borderRadius: '8px',
      backgroundColor: '#fff'
    }}>
      <div
        className="details-header"
        onMouseDown={handleMouseDown}
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid #eee',
          cursor: isDragging ? 'grabbing' : 'grab',
          userSelect: 'none'
        }}
      >
        <div className="header-top" style={{ marginBottom: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <span
            className="node-type-badge"
            style={{
              textTransform: 'capitalize',
              backgroundColor: '#e7f3ff',
              color: '#2563eb',
              border: '1px solid #bfdbfe',
              fontSize: '0.7rem',
              fontWeight: '600',
              padding: '2px 8px',
              borderRadius: '12px',
              letterSpacing: '0.025em'
            }}
          >
            {node.domain || 'General'}
          </span>
          <button className="close-btn" onClick={onClose} aria-label="Close details" style={{ fontSize: '1.2rem', padding: '4px', background: 'none', border: 'none', cursor: 'pointer' }}>
            ×
          </button>
        </div>
        <h3 style={{
          fontSize: '1.1rem',
          fontWeight: '600',
          lineHeight: '1.4',
          margin: 0,
          color: '#111827'
        }}>
          {node.name}
        </h3>

        {/* Outcome badges */}
        {node.isOutcome && (
          <div style={{ marginTop: '8px', display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            <span style={{
              display: 'inline-block',
              padding: '3px 10px',
              backgroundColor: '#fbbf24',
              color: '#fff',
              borderRadius: '12px',
              fontSize: '0.7rem',
              fontWeight: '600'
            }}>
              ⭐ Outcome Event
            </span>
            {node.properties?.outcome_scenario && (
              <span style={{
                display: 'inline-block',
                padding: '3px 10px',
                backgroundColor: '#e0e7ff',
                color: '#4338ca',
                borderRadius: '12px',
                fontSize: '0.7rem',
                fontWeight: '600'
              }}>
                {node.properties.outcome_scenario}
              </span>
            )}
            {node.properties?.is_actual_outcome && (
              <span style={{
                display: 'inline-block',
                padding: '3px 10px',
                backgroundColor: '#4CAF50',
                color: '#fff',
                borderRadius: '12px',
                fontSize: '0.7rem',
                fontWeight: '600'
              }}>
                ✓ Actual Outcome
              </span>
            )}
          </div>
        )}
      </div>

      <div className="details-content" style={{ padding: '16px 20px', overflowY: 'auto' }}>
        <EventMetrics node={node} />

        <RelatedArticles
          eventId={node.id}
          show={showArticles}
          onToggle={() => setShowArticles(!showArticles)}
        />

        <RelatedQuestions
          eventId={node.id}
          show={showQuestions}
          onToggle={() => setShowQuestions(!showQuestions)}
        />

        <EventImpacts
          node={node}
          show={showImpacts}
          onToggle={() => setShowImpacts(!showImpacts)}
        />

      </div>
    </div>
  )
})

export default EventDetails
