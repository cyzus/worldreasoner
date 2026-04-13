import React, { useEffect, useState } from 'react'

/**
 * CausalPathProgress - Shows causal chain completion progress
 *
 * Displays how far along the causal path to the target event we are,
 * showing which events have been confirmed vs predicted.
 */
function CausalPathProgress({ questionId }) {
  const [pathData, setPathData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [isExpanded, setIsExpanded] = useState(false)
  const [selectedPathIndex, setSelectedPathIndex] = useState(0)

  useEffect(() => {
    if (!questionId) {
      setPathData(null)
      setLoading(false)
      return
    }

    setLoading(true)
    setError(null)
    setSelectedPathIndex(0) // Reset path selection when question changes

    fetch(`/api/questions/${questionId}/causal_path`)
      .then(res => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`)
        }
        return res.json()
      })
      .then(data => {
        setPathData(data)
        setLoading(false)
      })
      .catch(err => {
        console.error('Error fetching causal path:', err)
        setError(err.message)
        setLoading(false)
      })
  }, [questionId])

  if (loading) {
    return (
      <div style={{
        padding: '12px 16px',
        backgroundColor: '#f8f9fa',
        borderRadius: '8px',
        border: '1px solid #dee2e6',
        marginBottom: '16px'
      }}>
        <div style={{ fontSize: '13px', color: '#6c757d' }}>
          Loading causal path analysis...
        </div>
      </div>
    )
  }

  if (error) {
    return null // Silently hide on error
  }

  if (!pathData || !pathData.has_target_event) {
    return null // No target event, nothing to show
  }

  const stats = pathData.statistics || {}
  const completionRatio = stats.completion_ratio || 0
  const completionPercent = Math.round(completionRatio * 100)
  const confirmedCount = stats.confirmed_events || 0
  const totalCount = stats.total_events || 0
  const allPaths = pathData.paths || []
  const currentPath = allPaths[selectedPathIndex] || []
  const pathCount = allPaths.length

  // Determine status
  let statusColor = '#6c757d'
  let statusText = 'No path'
  if (totalCount > 0) {
    if (completionRatio >= 0.75) {
      statusColor = '#22c55e'
      statusText = 'Strong progress'
    } else if (completionRatio >= 0.5) {
      statusColor = '#3b82f6'
      statusText = 'Moderate progress'
    } else if (completionRatio >= 0.25) {
      statusColor = '#f59e0b'
      statusText = 'Early stage'
    } else {
      statusColor = '#94a3b8'
      statusText = 'Just started'
    }
  }

  return (
    <div style={{
      padding: '14px 18px',
      backgroundColor: '#ffffff',
      borderRadius: '8px',
      border: '1px solid #e5e7eb',
      marginBottom: '16px',
      boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
    }}>
      {/* Header with toggle */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: isExpanded ? '12px' : '0'
      }}>
        <div style={{ flex: 1 }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            marginBottom: '8px'
          }}>
            <span style={{ fontSize: '14px', fontWeight: '600', color: '#374151' }}>
              Causal Path Progress
            </span>
            <span style={{
              fontSize: '11px',
              fontWeight: '600',
              color: statusColor,
              backgroundColor: `${statusColor}15`,
              padding: '2px 8px',
              borderRadius: '10px'
            }}>
              {statusText}
            </span>
          </div>

          {/* Progress bar */}
          <div style={{
            width: '100%',
            height: '8px',
            backgroundColor: '#e5e7eb',
            borderRadius: '4px',
            overflow: 'hidden'
          }}>
            <div style={{
              width: `${completionPercent}%`,
              height: '100%',
              backgroundColor: statusColor,
              transition: 'width 0.3s ease',
              borderRadius: '4px'
            }} />
          </div>

          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginTop: '6px'
          }}>
            <span style={{ fontSize: '12px', color: '#6b7280' }}>
              {confirmedCount}/{totalCount} events confirmed ({completionPercent}%)
            </span>
            {stats.total_paths > 0 && (
              <span style={{ fontSize: '11px', color: '#9ca3af' }}>
                {stats.total_paths} path{stats.total_paths !== 1 ? 's' : ''} found
              </span>
            )}
          </div>
        </div>

        {/* Toggle button */}
        {pathCount > 0 && (
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            style={{
              marginLeft: '12px',
              padding: '6px 10px',
              backgroundColor: isExpanded ? '#e5e7eb' : 'transparent',
              border: '1px solid #d1d5db',
              borderRadius: '6px',
              fontSize: '12px',
              color: '#4b5563',
              cursor: 'pointer',
              fontWeight: '500',
              transition: 'all 0.2s'
            }}
            onMouseEnter={(e) => e.target.style.backgroundColor = '#e5e7eb'}
            onMouseLeave={(e) => e.target.style.backgroundColor = isExpanded ? '#e5e7eb' : 'transparent'}
          >
            {isExpanded ? 'Hide' : 'Show'} Path
          </button>
        )}
      </div>

      {/* Expanded view: path selector and details */}
      {isExpanded && pathCount > 0 && (
        <div style={{
          marginTop: '12px',
          paddingTop: '12px',
          borderTop: '1px solid #e5e7eb'
        }}>
          {/* Path selector */}
          {pathCount > 1 && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              marginBottom: '12px'
            }}>
              <span style={{ fontSize: '12px', fontWeight: '600', color: '#6b7280' }}>
                View Path:
              </span>
              <div style={{
                display: 'flex',
                gap: '4px',
                flex: 1,
                flexWrap: 'wrap'
              }}>
                {allPaths.map((path, idx) => (
                  <button
                    key={idx}
                    onClick={() => setSelectedPathIndex(idx)}
                    style={{
                      padding: '4px 10px',
                      fontSize: '11px',
                      fontWeight: '500',
                      backgroundColor: selectedPathIndex === idx ? '#3b82f6' : '#f3f4f6',
                      color: selectedPathIndex === idx ? '#ffffff' : '#6b7280',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      transition: 'all 0.2s'
                    }}
                    onMouseEnter={(e) => {
                      if (selectedPathIndex !== idx) {
                        e.target.style.backgroundColor = '#e5e7eb'
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (selectedPathIndex !== idx) {
                        e.target.style.backgroundColor = '#f3f4f6'
                      }
                    }}
                  >
                    Path {idx + 1} ({path.length} events)
                  </button>
                ))}
              </div>
            </div>
          )}

          <div style={{
            fontSize: '12px',
            fontWeight: '600',
            color: '#6b7280',
            marginBottom: '10px'
          }}>
            {pathCount > 1 ? `Path ${selectedPathIndex + 1} of ${pathCount}` : 'Causal Path'} ({currentPath.length} events):
          </div>

          {/* Reverse path to show chronological order: root (earliest) → target (latest) */}
          {[...currentPath].reverse().map((node, idx) => {
            const isConfirmed = node.status === 'occurred'
            const isPending = node.status !== 'occurred'
            const isLast = idx === currentPath.length - 1
            // Get the next node in the REVERSED array to access its edge_from_parent
            const nextNodeInReversed = idx < currentPath.length - 1 ? [...currentPath].reverse()[idx + 1] : null

            return (
              <div key={node.event_id} style={{ marginBottom: isLast ? '0' : '8px' }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '10px'
                }}>
                  {/* Status indicator */}
                  <div style={{
                    width: '20px',
                    height: '20px',
                    borderRadius: '50%',
                    backgroundColor: isConfirmed ? '#22c55e' : '#e5e7eb',
                    border: `2px solid ${isConfirmed ? '#16a34a' : '#9ca3af'}`,
                    flexShrink: 0,
                    marginTop: '2px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '10px'
                  }}>
                    {isConfirmed ? '✓' : '⋯'}
                  </div>

                  {/* Event details */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      fontSize: '13px',
                      fontWeight: '500',
                      color: isConfirmed ? '#374151' : '#9ca3af',
                      marginBottom: '2px',
                      lineHeight: '1.3'
                    }}>
                      {node.title}
                    </div>
                    <div style={{
                      fontSize: '11px',
                      color: isConfirmed ? '#6b7280' : '#9ca3af',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      flexWrap: 'wrap'
                    }}>
                      <span>
                        {isConfirmed ? '✅ Confirmed' : '⏳ Predicted'}
                      </span>
                      {node.occurred_date && (
                        <span>
                          {new Date(node.occurred_date).toLocaleDateString('en-US', {
                            month: 'short',
                            day: 'numeric',
                            year: 'numeric'
                          })}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Arrow between events - show relation on the arrow itself */}
                {!isLast && (
                  <div style={{
                    marginLeft: '10px',
                    paddingLeft: '10px',
                    borderLeft: '2px solid #e5e7eb',
                    height: '24px',
                    position: 'relative',
                    display: 'flex',
                    alignItems: 'center'
                  }}>
                    <div style={{
                      position: 'absolute',
                      left: '-5px',
                      top: '50%',
                      transform: 'translateY(-50%)',
                      fontSize: '10px',
                      color: '#9ca3af'
                    }}>
                      ↓
                    </div>
                    {nextNodeInReversed?.edge_from_parent?.relation_type && (
                      <span style={{
                        marginLeft: '8px',
                        backgroundColor: '#f3f4f6',
                        padding: '1px 6px',
                        borderRadius: '3px',
                        fontSize: '9px',
                        fontWeight: '500',
                        color: '#6b7280'
                      }}>
                        {nextNodeInReversed.edge_from_parent.relation_type}
                      </span>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default CausalPathProgress
