import React, { useEffect, useRef, useState, memo } from 'react'
import { ChartHeader } from './Chart/ChartHeader'
import { ChartTooltips } from './Chart/ChartTooltips'
import { drawTimeSeriesChart } from './Chart/drawTimeSeries'

/**
 * TimeSeriesChart - Displays Polymarket price history with event markers
 */
const TimeSeriesChart = memo(function TimeSeriesChart({
  priceHistory,
  events = [],
  turningPoints = [],
  leadChanges = [],
  outcomes = ['Yes', 'No'],
  tokenOutcomes = {},
  width = 900,
  height = 400,
  activeInterval = 'max',
  onIntervalChange
}) {
  const svgRef = useRef()
  const [hoveredEvent, setHoveredEvent] = useState(null)
  const [hoveredEventImpact, setHoveredEventImpact] = useState(null)
  const [hoveredTurningPoint, setHoveredTurningPoint] = useState(null)
  const [hoveredLeadChange, setHoveredLeadChange] = useState(null)
  const [hoveredPrice, setHoveredPrice] = useState(null)
  const [isExpanded, setIsExpanded] = useState(true)

  useEffect(() => {
    if (!isExpanded) return
    if (!priceHistory || typeof priceHistory !== 'object' || Object.keys(priceHistory).length === 0) return

    drawTimeSeriesChart(svgRef.current, {
      priceHistory, events, turningPoints, leadChanges, outcomes, tokenOutcomes,
      width, height,
      setHoveredEvent, setHoveredEventImpact, setHoveredTurningPoint,
      setHoveredLeadChange, setHoveredPrice
    })
  }, [priceHistory, events, turningPoints, leadChanges, outcomes, tokenOutcomes, width, height, isExpanded])

  // Count events in time range for title
  const eventsInRange = (Array.isArray(events) && events.length > 0) ? events.filter(event => {
    if (!event.occurred_date && !event.predicted_date) return false
    if (!priceHistory || typeof priceHistory !== 'object' || Object.keys(priceHistory).length === 0) return false

    const allData = []
    Object.values(priceHistory).forEach(history => {
      if (Array.isArray(history)) {
        history.forEach(point => allData.push(point.t * 1000))
      }
    })
    if (allData.length === 0) return false

    const eventDate = new Date(event.occurred_date || event.predicted_date)
    const minDate = new Date(Math.min(...allData))
    const maxDate = new Date(Math.max(...allData))
    return eventDate >= minDate && eventDate <= maxDate
  }) : []

  return (
    <div style={{ position: 'relative', background: '#ffffff', padding: '20px', borderRadius: '8px', border: '1px solid #dee2e6' }}>
      <ChartHeader
        eventsInRange={eventsInRange}
        turningPoints={turningPoints || []}
        leadChanges={leadChanges || []}
        activeInterval={activeInterval}
        onIntervalChange={onIntervalChange}
        isExpanded={isExpanded}
        setIsExpanded={setIsExpanded}
      />

      {isExpanded && (
        <svg
          ref={svgRef}
          width={width}
          height={height}
          style={{ display: 'block' }}
        />
      )}

      {isExpanded && (
        <ChartTooltips
          hoveredPrice={hoveredPrice}
          hoveredEvent={hoveredEvent}
          hoveredEventImpact={hoveredEventImpact}
          hoveredTurningPoint={hoveredTurningPoint}
          hoveredLeadChange={hoveredLeadChange}
        />
      )}
    </div>
  )
})

export default TimeSeriesChart
