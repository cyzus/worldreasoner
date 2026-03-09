import React from 'react'

export const ChartTooltips = ({
    hoveredPrice,
    hoveredEvent,
    hoveredEventImpact,
    hoveredTurningPoint,
    hoveredLeadChange
}) => {
    return (
        <>
            {/* Price tooltip */}
            {hoveredPrice && (
                <div style={{
                    position: 'absolute',
                    top: '60px',
                    right: '170px',
                    background: '#ffffff',
                    border: '1px solid #dee2e6',
                    borderRadius: '6px',
                    padding: '10px 14px',
                    color: '#495057',
                    fontSize: '12px',
                    pointerEvents: 'none',
                    zIndex: 1000,
                    boxShadow: '0 4px 12px rgba(0,0,0,0.15)'
                }}>
                    <div style={{ fontWeight: 'bold', marginBottom: '6px', color: '#212529', fontSize: '11px' }}>
                        {new Date(hoveredPrice[0].timestamp).toLocaleString('en-US', {
                            month: 'short',
                            day: 'numeric',
                            year: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit'
                        })}
                    </div>
                    {hoveredPrice.map(info => (
                        <div key={info.outcome} style={{ marginBottom: '2px' }}>
                            <span style={{ fontWeight: '600' }}>{info.outcome}:</span> {(info.price * 100).toFixed(1)}%
                        </div>
                    ))}
                </div>
            )}

            {/* Event tooltip */}
            {hoveredEvent && (
                <div style={{
                    position: 'absolute',
                    top: '60px',
                    left: '80px',
                    background: '#ffffff',
                    border: `2px solid ${hoveredEvent._markerColor || ((hoveredEvent.is_actual_outcome || hoveredEvent.properties?.is_actual_outcome) ? '#f59e0b' : '#4a90e2')}`,
                    borderRadius: '8px',
                    padding: '12px 16px',
                    color: '#495057',
                    fontSize: '12px',
                    maxWidth: '380px',
                    pointerEvents: 'none',
                    zIndex: 1000,
                    boxShadow: '0 8px 24px rgba(0,0,0,0.15)'
                }}>
                    {(hoveredEvent.is_actual_outcome || hoveredEvent.properties?.is_actual_outcome) && (
                        <div style={{ color: '#f59e0b', fontWeight: 'bold', marginBottom: '6px', fontSize: '12px' }}>
                            🎯 OUTCOME EVENT
                        </div>
                    )}
                    <div style={{ fontWeight: '600', marginBottom: '6px', fontSize: '13px', lineHeight: '1.4', color: '#212529' }}>
                        {hoveredEvent.title}
                    </div>
                    <div style={{ fontSize: '11px', color: '#6c757d', marginBottom: hoveredEventImpact ? '8px' : '0' }}>
                        📅 {new Date(hoveredEvent.occurred_date || hoveredEvent.predicted_date).toLocaleString('en-US', {
                            month: 'short',
                            day: 'numeric',
                            year: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit'
                        })}
                    </div>

                    {hoveredEventImpact && (
                        <div style={{ paddingTop: '8px', borderTop: '1px solid #e5e7eb', marginTop: '4px' }}>
                            <div style={{ fontSize: '11px', fontWeight: '600', color: '#374151', marginBottom: '4px' }}>
                                Market Reaction (4h window):
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px' }}>
                                <span style={{ color: '#6b7280' }}>Before:</span>
                                <span style={{ fontWeight: '600', color: '#374151' }}>
                                    {(hoveredEventImpact.priceBefore * 100).toFixed(1)}%
                                </span>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px' }}>
                                <span style={{ color: '#6b7280' }}>After:</span>
                                <span style={{ fontWeight: '600', color: '#374151' }}>
                                    {(hoveredEventImpact.priceAfter * 100).toFixed(1)}%
                                </span>
                            </div>
                            <div style={{
                                marginTop: '4px', padding: '4px 8px',
                                backgroundColor: hoveredEventImpact.direction === 'up' ? '#dcfce7' : '#fee2e2',
                                borderRadius: '4px', display: 'inline-block'
                            }}>
                                <span style={{ fontSize: '12px', fontWeight: '700', color: hoveredEventImpact.direction === 'up' ? '#15803d' : '#b91c1c' }}>
                                    {hoveredEventImpact.direction === 'up' ? '↗' : '↘'} {hoveredEventImpact.direction === 'up' ? '+' : ''}{hoveredEventImpact.delta.toFixed(1)}pp
                                </span>
                                <span style={{ fontSize: '10px', marginLeft: '6px', color: hoveredEventImpact.direction === 'up' ? '#166534' : '#991b1b' }}>
                                    ({hoveredEventImpact.direction === 'up' ? 'Target more likely' : 'Target less likely'})
                                </span>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Turning point tooltip */}
            {hoveredTurningPoint && (
                <div style={{
                    position: 'absolute',
                    top: '120px',
                    left: '80px',
                    background: '#ffffff',
                    border: `2px solid ${hoveredTurningPoint.type === 'peak' ? '#ef4444' : '#22c55e'}`,
                    borderRadius: '8px',
                    padding: '12px 16px',
                    color: '#495057', fontSize: '12px', maxWidth: '320px', pointerEvents: 'none', zIndex: 1000,
                    boxShadow: '0 8px 24px rgba(0,0,0,0.15)'
                }}>
                    <div style={{ color: hoveredTurningPoint.type === 'peak' ? '#ef4444' : '#22c55e', fontWeight: 'bold', marginBottom: '6px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        {hoveredTurningPoint.type === 'peak' ? '◆ MARKET PEAK' : '◆ MARKET TROUGH'}
                    </div>
                    <div style={{ fontWeight: '600', marginBottom: '8px', fontSize: '14px', color: '#212529' }}>
                        Price: {(hoveredTurningPoint.price * 100).toFixed(1)}%
                    </div>
                    <div style={{ fontSize: '11px', color: '#6c757d', marginBottom: '8px' }}>
                        {new Date(hoveredTurningPoint.timestamp * 1000).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', paddingTop: '8px', borderTop: '1px solid #e5e7eb' }}>
                        <div>
                            <div style={{ fontSize: '10px', color: '#6b7280', marginBottom: '2px' }}>Before</div>
                            <div style={{ fontSize: '12px', fontWeight: '600', color: hoveredTurningPoint.change_before > 0 ? '#22c55e' : '#ef4444' }}>
                                {hoveredTurningPoint.change_before > 0 ? '+' : ''}{hoveredTurningPoint.change_before.toFixed(1)}pp
                            </div>
                        </div>
                        <div>
                            <div style={{ fontSize: '10px', color: '#6b7280', marginBottom: '2px' }}>After</div>
                            <div style={{ fontSize: '12px', fontWeight: '600', color: hoveredTurningPoint.change_after > 0 ? '#22c55e' : '#ef4444' }}>
                                {hoveredTurningPoint.change_after > 0 ? '+' : ''}{hoveredTurningPoint.change_after.toFixed(1)}pp
                            </div>
                        </div>
                    </div>
                    <div style={{ marginTop: '8px', padding: '6px 10px', backgroundColor: '#f3f4f6', borderRadius: '4px', fontSize: '11px' }}>
                        <span style={{ color: '#6b7280' }}>Significance: </span>
                        <span style={{ fontWeight: '600', color: '#374151' }}>{hoveredTurningPoint.significance.toFixed(1)}</span>
                        <span style={{ color: '#9ca3af', marginLeft: '4px' }}>(total swing)</span>
                    </div>
                </div>
            )}

            {/* Lead change tooltip */}
            {hoveredLeadChange && (
                <div style={{
                    position: 'absolute',
                    top: '120px',
                    left: '420px',
                    background: '#ffffff',
                    border: `2px solid ${hoveredLeadChange.direction === 'above' ? '#2563eb' : '#f59e0b'}`,
                    borderRadius: '8px',
                    padding: '12px 16px',
                    color: '#495057', fontSize: '12px', maxWidth: '320px', pointerEvents: 'none', zIndex: 1000,
                    boxShadow: '0 8px 24px rgba(0,0,0,0.15)'
                }}>
                    <div style={{ color: hoveredLeadChange.direction === 'above' ? '#2563eb' : '#f59e0b', fontWeight: 'bold', marginBottom: '6px', fontSize: '12px' }}>
                        ⭕ LEAD CHANGE ({hoveredLeadChange.direction === 'above' ? 'Crossed Above 50%' : 'Crossed Below 50%'})
                    </div>
                    <div style={{ fontWeight: '600', marginBottom: '8px', fontSize: '14px', color: '#212529' }}>
                        Price: {(hoveredLeadChange.price * 100).toFixed(1)}%
                    </div>
                    <div style={{ fontSize: '11px', color: '#6c757d', marginBottom: '8px' }}>
                        {new Date(hoveredLeadChange.timestamp * 1000).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', paddingTop: '8px', borderTop: '1px solid #e5e7eb' }}>
                        <div>
                            <div style={{ fontSize: '10px', color: '#6b7280', marginBottom: '2px' }}>Previous Price</div>
                            <div style={{ fontSize: '12px', fontWeight: '600', color: '#374151' }}>{(hoveredLeadChange.previous_price * 100).toFixed(1)}%</div>
                        </div>
                        <div>
                            <div style={{ fontSize: '10px', color: '#6b7280', marginBottom: '2px' }}>State Duration</div>
                            <div style={{ fontSize: '12px', fontWeight: '600', color: '#374151' }}>
                                {hoveredLeadChange.time_in_previous_state_hours != null ? `${hoveredLeadChange.time_in_previous_state_hours.toFixed(1)}h` : 'n/a'}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </>
    )
}
