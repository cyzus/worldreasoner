import React from 'react'

export const ChartHeader = ({
    eventsInRange,
    turningPoints,
    leadChanges,
    activeInterval,
    onIntervalChange,
    isExpanded,
    setIsExpanded
}) => {
    return (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <h3 style={{ color: '#212529', margin: 0, fontSize: '16px', fontWeight: 600 }}>
                Market Price History
                {(eventsInRange.length > 0 || turningPoints.length > 0 || leadChanges.length > 0) && (
                    <span style={{ fontSize: '13px', color: '#6c757d', marginLeft: '10px', fontWeight: 400 }}>
                        ({eventsInRange.length > 0 ? `${eventsInRange.length} event${eventsInRange.length !== 1 ? 's' : ''}` : ''}
                        {eventsInRange.length > 0 && turningPoints.length > 0 ? ', ' : ''}
                        {turningPoints.length > 0 ? `${turningPoints.length} turning point${turningPoints.length !== 1 ? 's' : ''}` : ''}
                        {(eventsInRange.length > 0 || turningPoints.length > 0) && leadChanges.length > 0 ? ', ' : ''}
                        {leadChanges.length > 0 ? `${leadChanges.length} lead change${leadChanges.length !== 1 ? 's' : ''}` : ''})
                    </span>
                )}
            </h3>

            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                {/* Interval Controls */}
                <div style={{ display: 'flex', border: '1px solid #dee2e6', borderRadius: '4px', overflow: 'hidden' }}>
                    {['max', '1w', '1d', '6h', '1h', '1m'].map(interval => (
                        <button
                            key={interval}
                            onClick={() => onIntervalChange && onIntervalChange(interval)}
                            style={{
                                background: activeInterval === interval ? '#e9ecef' : '#fff',
                                border: 'none',
                                borderRight: interval !== '1m' ? '1px solid #dee2e6' : 'none',
                                padding: '4px 8px',
                                fontSize: '11px',
                                cursor: 'pointer',
                                fontWeight: activeInterval === interval ? '600' : '400',
                                color: activeInterval === interval ? '#212529' : '#6c757d'
                            }}
                        >
                            {interval === 'max' ? 'Max' : interval.toUpperCase()}
                        </button>
                    ))}
                </div>

                <button
                    onClick={() => setIsExpanded(!isExpanded)}
                    style={{
                        background: 'none',
                        border: '1px solid #dee2e6',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        padding: '4px 8px',
                        fontSize: '12px',
                        color: '#6c757d',
                        marginLeft: '8px'
                    }}
                >
                    {isExpanded ? 'Hide' : 'Show'}
                </button>
            </div>
        </div>
    )
}
