import React, { useEffect, useRef, useState, memo } from 'react'
import { select } from 'd3-selection'
import { scaleTime, scaleLinear, scaleOrdinal } from 'd3-scale'
import { extent, group, bisector } from 'd3-array'
import { axisLeft, axisBottom } from 'd3-axis'
import { timeMonth, timeWeek, timeDay } from 'd3-time'
import { timeFormat } from 'd3-time-format'
import { line, curveMonotoneX } from 'd3-shape'
import { pointer } from 'd3-selection'

/**
 * TimeSeriesChart - Displays Polymarket price history with event markers
 *
 * Shows market probability over time with events overlaid as markers.
 * The target event is highlighted with a gold marker.
 * Turning points (detected price reversals) are shown as diamond markers.
 */
const TimeSeriesChart = memo(function TimeSeriesChart({
  priceHistory,
  events = [],
  turningPoints = [],
  targetEventId,
  outcomes = ['Yes', 'No'],
  width = 900,
  height = 400,
  activeInterval = 'max',
  onIntervalChange
}) {
  const svgRef = useRef()
  const [hoveredEvent, setHoveredEvent] = useState(null)
  const [hoveredEventImpact, setHoveredEventImpact] = useState(null)
  const [hoveredTurningPoint, setHoveredTurningPoint] = useState(null)
  const [hoveredPrice, setHoveredPrice] = useState(null)
  const [isExpanded, setIsExpanded] = useState(true)

  useEffect(() => {
    if (!isExpanded) return
    if (!priceHistory || typeof priceHistory !== 'object' || Object.keys(priceHistory).length === 0) return

    // Clear previous chart
    const svg = select(svgRef.current)
    svg.selectAll('*').remove()

    // Base Margins
    const margin = { top: 40, right: 150, bottom: 50, left: 60 }
    const innerWidth = width - margin.left - margin.right

    // Prepare data - flatten price history for all tokens
    // NOTE: Polymarket timestamps are in SECONDS, multiply by 1000 for JavaScript Date
    const allData = []
    const tokenIds = Object.keys(priceHistory)

    tokenIds.forEach((tokenId, idx) => {
      const history = priceHistory[tokenId]
      if (Array.isArray(history)) {
        history.forEach(point => {
          allData.push({
            timestamp: point.t * 1000,  // Convert seconds to milliseconds
            price: point.p,
            tokenId: tokenId,
            outcome: outcomes[idx] || `Outcome ${idx + 1}`
          })
        })
      }
    })

    if (allData.length === 0) {
      // Show "No data" message
      const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)
      g.append('text')
        .attr('x', innerWidth / 2)
        .attr('y', (height - margin.top - margin.bottom) / 2)
        .attr('text-anchor', 'middle')
        .style('fill', '#6c757d')
        .style('font-size', '14px')
        .text('No price history available')
      return
    }

    // Create X scale first to calculate event positions
    const xExtent = extent(allData, d => d.timestamp)
    const xScale = scaleTime()
      .domain([new Date(xExtent[0]), new Date(xExtent[1])])
      .range([0, innerWidth])

    // Calculate event stacking to adjust top margin
    let eventsInTimeRange = []
    let maxLevel = 0
    const levelHeight = 20 // Vertical space per stacked event

    if (Array.isArray(events) && events.length > 0) {
      eventsInTimeRange = events.filter(event => {
        if (!event.occurred_date && !event.predicted_date) return false
        const eventDate = new Date(event.occurred_date || event.predicted_date)
        return eventDate >= xScale.domain()[0] && eventDate <= xScale.domain()[1]
      })

      // Sort by date/position
      const eventNodes = eventsInTimeRange.map(event => {
        const date = new Date(event.occurred_date || event.predicted_date)
        return {
          ...event,
          xPos: xScale(date),
          level: 0
        }
      }).sort((a, b) => a.xPos - b.xPos)

      // Assign levels to avoid overlap
      const lanes = [] // stores max x for each lane
      const minNodeDist = 15 // pixels between centers to consider overlap

      eventNodes.forEach(node => {
        let laneIdx = 0
        while (true) {
          // Check if this lane is free at this x position
          // We add a small buffer to minNodeDist
          if (!lanes[laneIdx] || node.xPos >= lanes[laneIdx] + minNodeDist) {
            lanes[laneIdx] = node.xPos
            node.level = laneIdx
            break
          }
          laneIdx++
        }
      })

      maxLevel = Math.max(0, ...eventNodes.map(n => n.level))

      // Update eventsInTimeRange with level info
      // We need to map back to the original events or use the enriched nodes
      // Let's replace the array with our enriched nodes
      eventsInTimeRange = eventNodes
    }

    // Adjust top margin based on max level
    // Base top is 40, add space for levels. 
    // Level 0 is at -15. Level 1 at -35, etc.
    // We need enough space above 0.
    const requiredTop = 40 + (maxLevel * levelHeight)
    margin.top = Math.max(margin.top, requiredTop)

    const innerHeight = height - margin.top - margin.bottom

    // Create main group with updated margins
    const g = svg
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`)

    const yScale = scaleLinear()
      .domain([0, 1])
      .range([innerHeight, 0])
      .nice()

    // Color scale for different outcomes
    const colorScale = scaleOrdinal()
      .domain(outcomes)
      .range(['#4CAF50', '#F44336', '#2196F3', '#FF9800'])

    // Add grid lines
    g.append('g')
      .attr('class', 'grid')
      .attr('opacity', 0.15)
      .call(axisLeft(yScale)
        .tickSize(-innerWidth)
        .tickFormat('')
      )
      .selectAll('line')
      .style('stroke', '#dee2e6')

    // Add X axis with smart tick calculation
    const timeRange = xScale.domain()[1] - xScale.domain()[0]
    const daysRange = timeRange / (1000 * 60 * 60 * 24)

    // Choose appropriate tick interval based on data range
    let tickInterval, tickFormatFunc
    if (daysRange > 180) {
      tickInterval = timeMonth.every(1)
      tickFormatFunc = timeFormat('%b %Y')
    } else if (daysRange > 60) {
      tickInterval = timeWeek.every(2)
      tickFormatFunc = timeFormat('%b %d')
    } else if (daysRange > 30) {
      tickInterval = timeWeek.every(1)
      tickFormatFunc = timeFormat('%b %d')
    } else if (daysRange > 7) {
      tickInterval = timeDay.every(3)
      tickFormatFunc = timeFormat('%b %d')
    } else {
      tickInterval = timeDay.every(1)
      tickFormatFunc = timeFormat('%b %d')
    }

    const xAxis = g.append('g')
      .attr('transform', `translate(0,${innerHeight})`)
      .call(axisBottom(xScale)
        .ticks(tickInterval)
        .tickFormat(tickFormatFunc)
      )

    xAxis.selectAll('text')
      .style('fill', '#495057')
      .style('font-size', '11px')
      .attr('transform', 'rotate(-45)')
      .style('text-anchor', 'end')

    xAxis.selectAll('line')
      .style('stroke', '#dee2e6')

    xAxis.select('.domain')
      .style('stroke', '#dee2e6')

    // Add Y axis
    const yAxis = g.append('g')
      .call(axisLeft(yScale).ticks(5).tickFormat(d => `${(d * 100).toFixed(0)}%`))

    yAxis.selectAll('text')
      .style('fill', '#495057')
      .style('font-size', '12px')

    yAxis.selectAll('line')
      .style('stroke', '#dee2e6')

    yAxis.select('.domain')
      .style('stroke', '#dee2e6')

    // Add axis labels
    g.append('text')
      .attr('x', innerWidth / 2)
      .attr('y', innerHeight + 40)
      .attr('text-anchor', 'middle')
      .style('fill', '#6c757d')
      .style('font-size', '13px')
      .style('font-weight', '500')
      .text('Date')

    g.append('text')
      .attr('transform', 'rotate(-90)')
      .attr('x', -innerHeight / 2)
      .attr('y', -40)
      .attr('text-anchor', 'middle')
      .style('fill', '#6c757d')
      .style('font-size', '13px')
      .style('font-weight', '500')
      .text('Market Probability')

    // Create line generator
    const lineGenerator = line()
      .x(d => xScale(new Date(d.timestamp)))
      .y(d => yScale(d.price))
      .curve(curveMonotoneX)

    // Group data by outcome
    const dataByOutcome = group(allData, d => d.outcome)

    // Draw price lines
    dataByOutcome.forEach((data, outcome) => {
      g.append('path')
        .datum(data)
        .attr('fill', 'none')
        .attr('stroke', colorScale(outcome))
        .attr('stroke-width', 2.5)
        .attr('d', lineGenerator)
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
        .style('fill', '#495057')
        .style('font-size', '12px')
        .style('font-weight', '500')
        .text(outcome)
    })

    // Helper function to calculate price impact
    const calculatePriceImpact = (eventDate, priceHistory, outcomes) => {
      const eventTime = eventDate.getTime()
      const before1h = eventTime - (1 * 60 * 60 * 1000)
      const after4h = eventTime + (4 * 60 * 60 * 1000)

      // Get price for first outcome (typically "Yes")
      const firstTokenId = Object.keys(priceHistory)[0]
      if (!firstTokenId) return null

      const history = priceHistory[firstTokenId]
      if (!Array.isArray(history) || history.length === 0) return null

      // Find closest prices before and after event
      let priceBefore = null
      let priceAfter = null

      // Binary search for closest before/after prices
      for (let point of history) {
        const pointTime = point.t * 1000 // Convert to ms
        if (pointTime < eventTime && pointTime >= before1h) {
          if (!priceBefore || Math.abs(pointTime - eventTime) < Math.abs(priceBefore.time - eventTime)) {
            priceBefore = { price: point.p, time: pointTime }
          }
        }
        if (pointTime > eventTime && pointTime <= after4h) {
          if (!priceAfter || Math.abs(pointTime - eventTime) < Math.abs(priceAfter.time - eventTime)) {
            priceAfter = { price: point.p, time: pointTime }
          }
        }
      }

      if (!priceBefore || !priceAfter) return null

      const delta = priceAfter.price - priceBefore.price
      const deltaPercent = delta * 100 // Already in 0-1 range

      return {
        delta: deltaPercent,
        direction: delta > 0.02 ? 'up' : delta < -0.02 ? 'down' : 'neutral',
        priceBefore: priceBefore.price,
        priceAfter: priceAfter.price
      }
    }

    // Add event markers (if events provided)
    if (eventsInTimeRange.length > 0) {
      eventsInTimeRange.forEach((event, idx) => {
        const x = event.xPos
        const isTarget = event.id === targetEventId
        const level = event.level || 0
        const yOffset = -15 - (level * levelHeight)

        // Calculate market impact for this event
        const eventDate = new Date(event.occurred_date || event.predicted_date)
        const impact = calculatePriceImpact(eventDate, priceHistory, outcomes)

        // Event marker line (vertical line at event time)
        g.append('line')
          .attr('x1', x)
          .attr('x2', x)
          .attr('y1', yOffset + 6) // Start just below the circle
          .attr('y2', innerHeight)
          .attr('stroke', isTarget ? '#f59e0b' : '#4a90e2')
          .attr('stroke-width', isTarget ? 2 : 1) // Thinner lines for stacked events
          .attr('stroke-dasharray', isTarget ? '0' : '5,5')
          .attr('opacity', 0.4)
          .style('pointer-events', 'none')

        // Event marker circle at top (stacked)
        const markerCircle = g.append('circle')
          .attr('cx', x)
          .attr('cy', yOffset)
          .attr('r', isTarget ? 8 : 6)
          .attr('fill', isTarget ? '#f59e0b' : '#4a90e2')
          .attr('stroke', '#ffffff')
          .attr('stroke-width', 2)
          .style('cursor', 'pointer')
          .style('filter', 'drop-shadow(0 2px 4px rgba(0,0,0,0.15))')
          .on('mouseenter', function () {
            setHoveredEvent(event)
            setHoveredEventImpact(impact)
            select(this)
              .attr('r', isTarget ? 10 : 8)
              .attr('stroke-width', 3)
          })
          .on('mouseleave', function () {
            setHoveredEvent(null)
            setHoveredEventImpact(null)
            select(this)
              .attr('r', isTarget ? 8 : 6)
              .attr('stroke-width', 2)
          })

        // Add pulse animation for target event
        if (isTarget) {
          const pulseCircle = g.append('circle')
            .attr('cx', x)
            .attr('cy', yOffset)
            .attr('r', 8)
            .attr('fill', 'none')
            .attr('stroke', '#f59e0b')
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
            .attr('y', yOffset - 13)
            .attr('text-anchor', 'middle')
            .style('fill', '#f59e0b')
            .style('font-size', '10px')
            .style('font-weight', 'bold')
            .style('text-shadow', '0 1px 2px rgba(0,0,0,0.2)')
            .text('🎯 TARGET')
        }

        // Add small label for regular events (show first 3 letters only)
        // Only show if not too cluttered (low level) or if it's the target
        if (!isTarget && eventsInTimeRange.length <= 15 && level < 2) {
          const shortTitle = event.title.substring(0, 3).toUpperCase()
          g.append('text')
            .attr('x', x)
            .attr('y', yOffset - 10)
            .attr('text-anchor', 'middle')
            .style('fill', '#4a90e2')
            .style('font-size', '9px')
            .style('font-weight', 'bold')
            .style('text-shadow', '0 1px 2px rgba(0,0,0,0.1)')
            .text(shortTitle)
        }

        // Add market impact indicator if available
        if (impact && impact.direction !== 'neutral') {
          const impactColor = impact.direction === 'up' ? '#22c55e' : '#ef4444'
          const impactArrow = impact.direction === 'up' ? '↗' : '↘'

          // Draw curved line from event to price line showing impact
          const priceY = yScale(impact.priceAfter)

          // Only draw if we have valid coordinates
          if (isFinite(priceY)) {
            const midX = x + 25
            const midY = (yOffset + 10 + priceY) / 2

            // Draw curved path
            const path = `M ${x},${yOffset + 10} Q ${midX},${midY} ${x + 20},${priceY}`

            g.append('path')
              .attr('d', path)
              .attr('fill', 'none')
              .attr('stroke', impactColor)
              .attr('stroke-width', 1.5)
              .attr('opacity', 0.6)
              .attr('stroke-dasharray', '3,2')
              .style('pointer-events', 'none')

            // Add arrow head
            g.append('circle')
              .attr('cx', x + 20)
              .attr('cy', priceY)
              .attr('r', 2)
              .attr('fill', impactColor)
              .style('pointer-events', 'none')

            // Add impact label (delta percentage)
            g.append('text')
              .attr('x', x + 15)
              .attr('y', midY - 2)
              .attr('text-anchor', 'middle')
              .style('fill', impactColor)
              .style('font-size', '9px')
              .style('font-weight', 'bold')
              .style('text-shadow', '0 1px 2px rgba(255,255,255,0.8)')
              .text(`${impactArrow} ${Math.abs(impact.delta).toFixed(1)}pp`)
          }
        }
      })

      // Add legend for event markers
      const eventLegend = g.append('g')
        .attr('transform', `translate(${innerWidth + 20}, ${outcomes.length * 25 + 20})`)

      eventLegend.append('text')
        .attr('y', 0)
        .style('fill', '#495057')
        .style('font-size', '11px')
        .style('font-weight', 'bold')
        .text('Events:')

      if (eventsInTimeRange.some(e => e.id === targetEventId)) {
        eventLegend.append('circle')
          .attr('cx', 5)
          .attr('cy', 18)
          .attr('r', 5)
          .attr('fill', '#f59e0b')
          .attr('stroke', '#ffffff')
          .attr('stroke-width', 1)

        eventLegend.append('text')
          .attr('x', 15)
          .attr('y', 22)
          .style('fill', '#495057')
          .style('font-size', '10px')
          .text('Target')
      }

      eventLegend.append('circle')
        .attr('cx', 5)
        .attr('cy', eventsInTimeRange.some(e => e.id === targetEventId) ? 35 : 18)
        .attr('r', 4)
        .attr('fill', '#4a90e2')
        .attr('stroke', '#ffffff')
        .attr('stroke-width', 1)

      eventLegend.append('text')
        .attr('x', 15)
        .attr('y', eventsInTimeRange.some(e => e.id === targetEventId) ? 39 : 22)
        .style('fill', '#495057')
        .style('font-size', '10px')
        .text(`Events (${eventsInTimeRange.length - (eventsInTimeRange.some(e => e.id === targetEventId) ? 1 : 0)})`)
    }

    // Add turning point markers (diamond shapes on the price line)
    if (Array.isArray(turningPoints) && turningPoints.length > 0) {
      const turningPointsInRange = turningPoints.filter(tp => {
        const tpTime = tp.timestamp * 1000 // Convert to ms
        return tpTime >= xScale.domain()[0].getTime() && tpTime <= xScale.domain()[1].getTime()
      })

      turningPointsInRange.forEach((tp, idx) => {
        const x = xScale(new Date(tp.timestamp * 1000))
        const y = yScale(tp.price)
        const isPeak = tp.type === 'peak'
        const color = isPeak ? '#ef4444' : '#22c55e' // Red for peaks, green for troughs

        // Draw diamond marker
        const diamondSize = 6
        const diamondPath = `M ${x} ${y - diamondSize} L ${x + diamondSize} ${y} L ${x} ${y + diamondSize} L ${x - diamondSize} ${y} Z`

        g.append('path')
          .attr('d', diamondPath)
          .attr('fill', color)
          .attr('stroke', '#ffffff')
          .attr('stroke-width', 2)
          .style('cursor', 'pointer')
          .style('filter', 'drop-shadow(0 2px 4px rgba(0,0,0,0.2))')
          .on('mouseenter', function () {
            setHoveredTurningPoint(tp)
            select(this)
              .attr('transform', `scale(1.3)`)
              .attr('transform-origin', `${x}px ${y}px`)
          })
          .on('mouseleave', function () {
            setHoveredTurningPoint(null)
            select(this)
              .attr('transform', null)
          })

        // Add small label for significant turning points
        if (tp.significance >= 15 || idx < 3) {
          g.append('text')
            .attr('x', x)
            .attr('y', isPeak ? y - 12 : y + 16)
            .attr('text-anchor', 'middle')
            .style('fill', color)
            .style('font-size', '9px')
            .style('font-weight', 'bold')
            .style('pointer-events', 'none')
            .text(isPeak ? '▼' : '▲')
        }
      })

      // Add turning points to legend
      const tpLegendY = (eventsInTimeRange.length > 0 ? 55 : 0) + outcomes.length * 25 + 20
      const tpLegend = g.append('g')
        .attr('transform', `translate(${innerWidth + 20}, ${tpLegendY})`)

      tpLegend.append('text')
        .attr('y', 0)
        .style('fill', '#495057')
        .style('font-size', '11px')
        .style('font-weight', 'bold')
        .text('Turning Points:')

      // Peak legend
      const peakDiamond = 'M 5 8 L 9 12 L 5 16 L 1 12 Z'
      tpLegend.append('path')
        .attr('d', peakDiamond)
        .attr('fill', '#ef4444')
        .attr('stroke', '#ffffff')
        .attr('stroke-width', 1)

      tpLegend.append('text')
        .attr('x', 15)
        .attr('y', 16)
        .style('fill', '#495057')
        .style('font-size', '10px')
        .text(`Peaks (${turningPointsInRange.filter(t => t.type === 'peak').length})`)

      // Trough legend
      const troughDiamond = 'M 5 25 L 9 29 L 5 33 L 1 29 Z'
      tpLegend.append('path')
        .attr('d', troughDiamond)
        .attr('fill', '#22c55e')
        .attr('stroke', '#ffffff')
        .attr('stroke-width', 1)

      tpLegend.append('text')
        .attr('x', 15)
        .attr('y', 33)
        .style('fill', '#495057')
        .style('font-size', '10px')
        .text(`Troughs (${turningPointsInRange.filter(t => t.type === 'trough').length})`)
    }

    // Add interactive tooltip line
    const tooltipLine = g.append('line')
      .attr('stroke', '#6c757d')
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
      .on('mousemove', function (event) {
        const [mouseX] = pointer(event)
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
          const bisectFunc = bisector(d => d.timestamp).left
          const idx = bisectFunc(data, hoveredDate.getTime())
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
      .on('mouseleave', function () {
        tooltipLine.style('opacity', 0)
        tooltipCircles.forEach(({ circle }) => circle.style('opacity', 0))
        setHoveredPrice(null)
      })

  }, [priceHistory, events, turningPoints, targetEventId, outcomes, width, height, isExpanded])

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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
        <h3 style={{ color: '#212529', margin: 0, fontSize: '16px', fontWeight: 600 }}>
          Market Price History
          {(eventsInRange.length > 0 || turningPoints.length > 0) && (
            <span style={{ fontSize: '13px', color: '#6c757d', marginLeft: '10px', fontWeight: 400 }}>
              ({eventsInRange.length > 0 ? `${eventsInRange.length} event${eventsInRange.length !== 1 ? 's' : ''}` : ''}
              {eventsInRange.length > 0 && turningPoints.length > 0 ? ', ' : ''}
              {turningPoints.length > 0 ? `${turningPoints.length} turning point${turningPoints.length !== 1 ? 's' : ''}` : ''})
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

      {isExpanded && (
        <svg
          ref={svgRef}
          width={width}
          height={height}
          style={{ display: 'block' }}
        />
      )}

      {/* Hover tooltips */}
      {isExpanded && hoveredPrice && (
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

      {isExpanded && hoveredEvent && (
        <div style={{
          position: 'absolute',
          top: '60px',
          left: '80px',
          background: '#ffffff',
          border: hoveredEvent.id === targetEventId ? '2px solid #f59e0b' : '2px solid #4a90e2',
          borderRadius: '8px',
          padding: '12px 16px',
          color: '#495057',
          fontSize: '12px',
          maxWidth: '380px',
          pointerEvents: 'none',
          zIndex: 1000,
          boxShadow: '0 8px 24px rgba(0,0,0,0.15)'
        }}>
          {hoveredEvent.id === targetEventId && (
            <div style={{ color: '#f59e0b', fontWeight: 'bold', marginBottom: '6px', fontSize: '12px' }}>
              🎯 TARGET EVENT
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

          {/* Market impact section */}
          {hoveredEventImpact && (
            <div style={{
              paddingTop: '8px',
              borderTop: '1px solid #e5e7eb',
              marginTop: '4px'
            }}>
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
                marginTop: '4px',
                padding: '4px 8px',
                backgroundColor: hoveredEventImpact.direction === 'up' ? '#dcfce7' : '#fee2e2',
                borderRadius: '4px',
                display: 'inline-block'
              }}>
                <span style={{
                  fontSize: '12px',
                  fontWeight: '700',
                  color: hoveredEventImpact.direction === 'up' ? '#15803d' : '#b91c1c'
                }}>
                  {hoveredEventImpact.direction === 'up' ? '↗' : '↘'} {hoveredEventImpact.direction === 'up' ? '+' : ''}{hoveredEventImpact.delta.toFixed(1)}pp
                </span>
                <span style={{
                  fontSize: '10px',
                  marginLeft: '6px',
                  color: hoveredEventImpact.direction === 'up' ? '#166534' : '#991b1b'
                }}>
                  ({hoveredEventImpact.direction === 'up' ? 'Target more likely' : 'Target less likely'})
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Turning point tooltip */}
      {isExpanded && hoveredTurningPoint && (
        <div style={{
          position: 'absolute',
          top: '120px',
          left: '80px',
          background: '#ffffff',
          border: `2px solid ${hoveredTurningPoint.type === 'peak' ? '#ef4444' : '#22c55e'}`,
          borderRadius: '8px',
          padding: '12px 16px',
          color: '#495057',
          fontSize: '12px',
          maxWidth: '320px',
          pointerEvents: 'none',
          zIndex: 1000,
          boxShadow: '0 8px 24px rgba(0,0,0,0.15)'
        }}>
          <div style={{
            color: hoveredTurningPoint.type === 'peak' ? '#ef4444' : '#22c55e',
            fontWeight: 'bold',
            marginBottom: '6px',
            fontSize: '12px',
            display: 'flex',
            alignItems: 'center',
            gap: '6px'
          }}>
            {hoveredTurningPoint.type === 'peak' ? '◆ MARKET PEAK' : '◆ MARKET TROUGH'}
          </div>

          <div style={{ fontWeight: '600', marginBottom: '8px', fontSize: '14px', color: '#212529' }}>
            Price: {(hoveredTurningPoint.price * 100).toFixed(1)}%
          </div>

          <div style={{ fontSize: '11px', color: '#6c757d', marginBottom: '8px' }}>
            {new Date(hoveredTurningPoint.timestamp * 1000).toLocaleString('en-US', {
              month: 'short',
              day: 'numeric',
              year: 'numeric',
              hour: '2-digit',
              minute: '2-digit'
            })}
          </div>

          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: '8px',
            paddingTop: '8px',
            borderTop: '1px solid #e5e7eb'
          }}>
            <div>
              <div style={{ fontSize: '10px', color: '#6b7280', marginBottom: '2px' }}>Before</div>
              <div style={{
                fontSize: '12px',
                fontWeight: '600',
                color: hoveredTurningPoint.change_before > 0 ? '#22c55e' : '#ef4444'
              }}>
                {hoveredTurningPoint.change_before > 0 ? '+' : ''}{hoveredTurningPoint.change_before.toFixed(1)}pp
              </div>
            </div>
            <div>
              <div style={{ fontSize: '10px', color: '#6b7280', marginBottom: '2px' }}>After</div>
              <div style={{
                fontSize: '12px',
                fontWeight: '600',
                color: hoveredTurningPoint.change_after > 0 ? '#22c55e' : '#ef4444'
              }}>
                {hoveredTurningPoint.change_after > 0 ? '+' : ''}{hoveredTurningPoint.change_after.toFixed(1)}pp
              </div>
            </div>
          </div>

          <div style={{
            marginTop: '8px',
            padding: '6px 10px',
            backgroundColor: '#f3f4f6',
            borderRadius: '4px',
            fontSize: '11px'
          }}>
            <span style={{ color: '#6b7280' }}>Significance: </span>
            <span style={{ fontWeight: '600', color: '#374151' }}>
              {hoveredTurningPoint.significance.toFixed(1)}
            </span>
            <span style={{ color: '#9ca3af', marginLeft: '4px' }}>
              (total swing)
            </span>
          </div>
        </div>
      )}
    </div>
  )
})

export default TimeSeriesChart
