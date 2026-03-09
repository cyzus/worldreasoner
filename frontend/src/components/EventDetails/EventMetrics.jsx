import React from 'react'
import { formatDate } from './RelatedItems'

export const EventMetrics = ({ node }) => {
    return (
        <>
            {/* Compact Metrics Row */}
            <div className="metrics-row" style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: '16px',
                fontSize: '0.8rem',
                color: '#4b5563',
                marginBottom: '16px',
                paddingBottom: '12px',
                borderBottom: '1px solid #f3f4f6'
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span>📅</span>
                    <span style={{ fontWeight: '500' }}>
                        {formatDate(node.properties?.occurred_date || node.properties?.predicted_date)}
                    </span>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span>🏷️</span>
                    <span style={{ textTransform: 'capitalize' }}>
                        {node.properties?.event_type || node.event_type || 'Event'}
                    </span>
                </div>

                {node.properties?.status && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span>
                            {node.properties.status === 'occurred' ? '✅' :
                                node.properties.status === 'predicted' ? '🔮' : 'ℹ️'}
                        </span>
                        <span style={{ textTransform: 'capitalize' }}>
                            {node.properties.status}
                        </span>
                    </div>
                )}
            </div>

            {node.properties?.description && (
                <div className="description-block" style={{ marginBottom: '16px' }}>
                    <p style={{
                        fontSize: '0.9rem',
                        lineHeight: '1.5',
                        color: '#374151',
                        margin: 0
                    }}>
                        {node.properties.description}
                    </p>
                </div>
            )}
        </>
    )
}
