import React, { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'

/**
 * TimeSeriesChart - Displays Polymarket price history with event markers
 *
 * Shows market probability over time with events overlaid as markers.
 * The target event is highlighted with a gold marker.
 */
export default function TimeSeriesChart({
  priceHistory,
  events,
  targetEventId,
  outcomes = ['Yes', 'No'],
  width = 900,
  height = 400
}) {
  const svgRef = useRef()
  const [hoveredEvent, setHoveredEvent] = useState(null)
  const [hoveredPrice, setHoveredPrice] = useState(null)

  useEffect(() => {
    if (!priceHistory || Object.keys(priceHistory).length === 0) return

    // Clear previous chart
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    // Margins
    const margin = { top: 40, right: 150, bottom: 50, left: 60 }
    const innerWidth = width - margin.left - margin.right
    const innerHeight = height - margin.top - margin.bottom

    // Create main group
    const g = svg
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`)

    // Prepare data - flatten price history for all tokens
    // NOTE: Polymarket timestamps are in SECONDS, multiply by 1000 for JavaScript Date
    const allData = []
    const tokenIds = Object.keys(priceHistory)

    tokenIds.forEach((tokenId, idx) => {
      const history = priceHistory[tokenId]
      history.forEach(point => {
        allData.push({
          timestamp: point.t * 1000,  // Convert seconds to milliseconds
          price: point.p,
          tokenId: tokenId,
          outcome: outcomes[idx] || `Outcome ${idx + 1}`
        })
      })
    })

    if (allData.length === 0) {
      // Show "No data" message
      g.append('text')
        .attr('x', innerWidth / 2)
        .attr('y', innerHeight / 2)
        .attr('text-anchor', 'middle')
        .style('fill', '#666')
        .text('No price history available')
      return
    }

    // Create scales
    const xExtent = d3.extent(allData, d => d.timestamp)
    const xScale = d3.scaleTime()
      .domain([new Date(xExtent[0]), new Date(xExtent[1])])
      .range([0, innerWidth])

    const yScale = d3.scaleLinear()
      .domain([0, 1])
      .range([innerHeight, 0])
      .nice()

    // Color scale for different outcomes
    const colorScale = d3.scaleOrdinal()
      .domain(outcomes)
      .range(['#4CAF50', '#F44336', '#2196F3', '#FF9800'])

    // Add grid lines
    g.append('g')
      .attr('class', 'grid')
      .attr('opacity', 0.1)
      .call(d3.axisLeft(yScale)
        .tickSize(-innerWidth)
        .tickFormat('')
      )

    // Add X axis
    g.append('g')
      .attr('transform', `translate(0,${innerHeight})`)
      .call(d3.axisBottom(xScale)
        .ticks(d3.timeDay.every(1))  // Show ticks by day
        .tickFormat(d3.timeFormat('%b %d'))  // Format as "Dec 01"
      )
      .style('color', '#ddd')

    // Add Y axis
    g.append('g')
      .call(d3.axisLeft(yScale).ticks(5).tickFormat(d => `${(d * 100).toFixed(0)}%`))
      .style('color', '#ddd')

    // Add axis labels
    g.append('text')
      .attr('x', innerWidth / 2)
      .attr('y', innerHeight + 40)
      .attr('text-anchor', 'middle')
      .style('fill', '#ddd')
      .text('Date')

    g.append('text')
      .attr('transform', 'rotate(-90)')
      .attr('x', -innerHeight / 2)
      .attr('y', -40)
      .attr('text-anchor', 'middle')
      .style('fill', '#ddd')
      .text('Market Probability')

    // Create line generator
    const line = d3.line()
      .x(d => xScale(new Date(d.timestamp)))
      .y(d => yScale(d.price))
      .curve(d3.curveMonotoneX)

    // Group data by outcome
    const dataByOutcome = d3.group(allData, d => d.outcome)

    // Draw price lines
    dataByOutcome.forEach((data, outcome) => {
      g.append('path')
        .datum(data)
        .attr('fill', 'none')
        .attr('stroke', colorScale(outcome))
        .attr('stroke-width', 2.5)
        .attr('d', line)
        .style('opacity', 0.9)
    })

    // Add legend
    const legend = g.append('g')
      .attr('transform', `translate(${innerWidth + 20}, 0)`)

    outcomes.forEach((outcome, idx) => {
      const legendRow = legend.append('g')
        .attr('transform', `translate(0, ${idx * 25})`)

      legendRow.append('rect')
        .attr('width', 15)
        .attr('height', 15)
        .attr('fill', colorScale(outcome))

      legendRow.append('text')
        .attr('x', 20)
        .attr('y', 12)
        .style('fill', '#ddd')
        .style('font-size', '12px')
        .text(outcome)
    })

    // Add event markers (if events provided)
    if (events && events.length > 0) {
      const eventsInTimeRange = events.filter(event => {
        if (!event.occurred_date && !event.predicted_date) return false
        const eventDate = new Date(event.occurred_date || event.predicted_date)
        return eventDate >= xScale.domain()[0] && eventDate <= xScale.domain()[1]
      })

      eventsInTimeRange.forEach((event, idx) => {
        const eventDate = new Date(event.occurred_date || event.predicted_date)
        const x = xScale(eventDate)
        const isTarget = event.id === targetEventId

        // Event marker line (vertical line at event time)
        g.append('line')
          .attr('x1', x)
          .attr('x2', x)
          .attr('y1', 0)
          .attr('y2', innerHeight)
          .attr('stroke', isTarget ? '#FFD700' : '#00BFFF')
          .attr('stroke-width', isTarget ? 3 : 2)
          .attr('stroke-dasharray', isTarget ? '0' : '5,5')
          .attr('opacity', 0.7)
          .style('pointer-events', 'none')

        // Event marker circle at top
        const markerCircle = g.append('circle')
          .attr('cx', x)
          .attr('cy', -15)
          .attr('r', isTarget ? 8 : 6)
          .attr('fill', isTarget ? '#FFD700' : '#00BFFF')
          .attr('stroke', '#1a1a1a')
          .attr('stroke-width', 2)
          .style('cursor', 'pointer')
          .on('mouseenter', function() {
            setHoveredEvent(event)
            d3.select(this)
              .attr('r', isTarget ? 10 : 8)
              .attr('stroke-width', 3)
          })
          .on('mouseleave', function() {
            setHoveredEvent(null)
            d3.select(this)
              .attr('r', isTarget ? 8 : 6)
              .attr('stroke-width', 2)
          })

        // Add pulse animation for target event
        if (isTarget) {
          const pulseCircle = g.append('circle')
            .attr('cx', x)
            .attr('cy', -15)
            .attr('r', 8)
            .attr('fill', 'none')
            .attr('stroke', '#FFD700')
            .attr('stroke-width', 2)
            .attr('opacity', 0.8)
            .style('pointer-events', 'none')

          // Animate pulse
          function pulse() {
            pulseCircle
              .attr('r', 8)
              .attr('opacity', 0.8)
              .transition()
              .duration(2000)
              .attr('r', 16)
              .attr('opacity', 0)
              .on('end', pulse)
          }
          pulse()
        }

        // Target event label
        if (isTarget) {
          g.append('text')
            .attr('x', x)
            .attr('y', -28)
            .attr('text-anchor', 'middle')
            .style('fill', '#FFD700')
            .style('font-size', '10px')
            .style('font-weight', 'bold')
            .style('text-shadow', '0 0 3px #000, 0 0 3px #000')
            .text('🎯 TARGET')
        }

        // Add small label for regular events (show first 3 letters only)
        if (!isTarget && eventsInTimeRange.length <= 10) {
          const shortTitle = event.title.substring(0, 3).toUpperCase()
          g.append('text')
            .attr('x', x)
            .attr('y', -28)
            .attr('text-anchor', 'middle')
            .style('fill', '#00BFFF')
            .style('font-size', '9px')
            .style('font-weight', 'bold')
            .style('text-shadow', '0 0 2px #000')
            .text(shortTitle)
        }
      })

      // Add legend for event markers
      const eventLegend = g.append('g')
        .attr('transform', `translate(${innerWidth + 20}, ${outcomes.length * 25 + 20})`)

      eventLegend.append('text')
        .attr('y', 0)
        .style('fill', '#ddd')
        .style('font-size', '11px')
        .style('font-weight', 'bold')
        .text('Events:')

      if (eventsInTimeRange.some(e => e.id === targetEventId)) {
        eventLegend.append('circle')
          .attr('cx', 5)
          .attr('cy', 18)
          .attr('r', 5)
          .attr('fill', '#FFD700')

        eventLegend.append('text')
          .attr('x', 15)
          .attr('y', 22)
          .style('fill', '#ddd')
          .style('font-size', '10px')
          .text('Target')
      }

      eventLegend.append('circle')
        .attr('cx', 5)
        .attr('cy', eventsInTimeRange.some(e => e.id === targetEventId) ? 35 : 18)
        .attr('r', 4)
        .attr('fill', '#00BFFF')

      eventLegend.append('text')
        .attr('x', 15)
        .attr('y', eventsInTimeRange.some(e => e.id === targetEventId) ? 39 : 22)
        .style('fill', '#ddd')
        .style('font-size', '10px')
        .text(`Events (${eventsInTimeRange.length - (eventsInTimeRange.some(e => e.id === targetEventId) ? 1 : 0)})`)
    }

    // Add interactive tooltip line
    const tooltipLine = g.append('line')
      .attr('stroke', '#666')
      .attr('stroke-width', 1)
      .attr('stroke-dasharray', '3,3')
      .style('opacity', 0)

    const tooltipCircles = []
    dataByOutcome.forEach((data, outcome) => {
      const circle = g.append('circle')
        .attr('r', 4)
        .attr('fill', colorScale(outcome))
        .attr('stroke', '#fff')
        .attr('stroke-width', 2)
        .style('opacity', 0)
      tooltipCircles.push({ circle, outcome })
    })

    // Add invisible overlay for mouse tracking
    g.append('rect')
      .attr('width', innerWidth)
      .attr('height', innerHeight)
      .attr('fill', 'none')
      .attr('pointer-events', 'all')
      .on('mousemove', function(event) {
        const [mouseX] = d3.pointer(event)
        const hoveredDate = xScale.invert(mouseX)

        tooltipLine
          .attr('x1', mouseX)
          .attr('x2', mouseX)
          .attr('y1', 0)
          .attr('y2', innerHeight)
          .style('opacity', 0.5)

        // Find closest price points
        const priceInfo = []
        dataByOutcome.forEach((data, outcome) => {
          // Binary search for closest point
          const bisect = d3.bisector(d => d.timestamp).left
          const idx = bisect(data, hoveredDate.getTime())
          const closestPoint = data[idx] || data[data.length - 1]

          if (closestPoint) {
            priceInfo.push({
              outcome,
              price: closestPoint.price,
              timestamp: closestPoint.timestamp
            })
          }
        })

        // Update tooltip circles
        tooltipCircles.forEach(({ circle, outcome }) => {
          const info = priceInfo.find(p => p.outcome === outcome)
          if (info) {
            circle
              .attr('cx', mouseX)
              .attr('cy', yScale(info.price))
              .style('opacity', 1)
          }
        })

        setHoveredPrice(priceInfo)
      })
      .on('mouseleave', function() {
        tooltipLine.style('opacity', 0)
        tooltipCircles.forEach(({ circle }) => circle.style('opacity', 0))
        setHoveredPrice(null)
      })

  }, [priceHistory, events, targetEventId, outcomes, width, height])

  // Count events in time range for title
  const eventsInRange = events ? events.filter(event => {
    if (!event.occurred_date && !event.predicted_date) return false
    if (!priceHistory || Object.keys(priceHistory).length === 0) return false

    const allData = []
    Object.values(priceHistory).forEach(history => {
      history.forEach(point => allData.push(point.t * 1000))
    })
    if (allData.length === 0) return false

    const eventDate = new Date(event.occurred_date || event.predicted_date)
    const minDate = new Date(Math.min(...allData))
    const maxDate = new Date(Math.max(...allData))
    return eventDate >= minDate && eventDate <= maxDate
  }) : []

  return (
    <div style={{ position: 'relative', background: '#1a1a1a', padding: '20px', borderRadius: '8px' }}>
      <h3 style={{ color: '#ddd', marginTop: 0, marginBottom: '10px' }}>
        Market Price History
        {eventsInRange.length > 0 && (
          <span style={{ fontSize: '14px', color: '#888', marginLeft: '10px' }}>
            ({eventsInRange.length} event{eventsInRange.length !== 1 ? 's' : ''} marked)
          </span>
        )}
      </h3>

      <svg
        ref={svgRef}
        width={width}
        height={height}
        style={{ display: 'block' }}
      />

      {/* Hover tooltips */}
      {hoveredPrice && (
        <div style={{
          position: 'absolute',
          top: '60px',
          right: '170px',
          background: 'rgba(0,0,0,0.9)',
          border: '1px solid #444',
          borderRadius: '4px',
          padding: '10px 14px',
          color: '#ddd',
          fontSize: '12px',
          pointerEvents: 'none',
          zIndex: 1000
        }}>
          <div style={{ fontWeight: 'bold', marginBottom: '6px', color: '#FFD700' }}>
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
              <span style={{ fontWeight: 'bold' }}>{info.outcome}:</span> {(info.price * 100).toFixed(1)}%
            </div>
          ))}
        </div>
      )}

      {hoveredEvent && (
        <div style={{
          position: 'absolute',
          top: '60px',
          left: '80px',
          background: 'rgba(0,0,0,0.95)',
          border: hoveredEvent.id === targetEventId ? '3px solid #FFD700' : '2px solid #00BFFF',
          borderRadius: '6px',
          padding: '12px 16px',
          color: '#ddd',
          fontSize: '12px',
          maxWidth: '350px',
          pointerEvents: 'none',
          zIndex: 1000,
          boxShadow: '0 4px 12px rgba(0,0,0,0.5)'
        }}>
          {hoveredEvent.id === targetEventId && (
            <div style={{ color: '#FFD700', fontWeight: 'bold', marginBottom: '6px', fontSize: '13px' }}>
              🎯 TARGET EVENT
            </div>
          )}
          <div style={{ fontWeight: 'bold', marginBottom: '6px', fontSize: '13px', lineHeight: '1.4' }}>
            {hoveredEvent.title}
          </div>
          <div style={{ fontSize: '11px', opacity: 0.9, color: '#00BFFF' }}>
            📅 {new Date(hoveredEvent.occurred_date || hoveredEvent.predicted_date).toLocaleString('en-US', {
              month: 'short',
              day: 'numeric',
              year: 'numeric',
              hour: '2-digit',
              minute: '2-digit'
            })}
          </div>
        </div>
      )}
    </div>
  )
}
