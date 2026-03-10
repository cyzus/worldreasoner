import { select } from 'd3-selection'
import { scaleTime, scaleLinear, scaleOrdinal } from 'd3-scale'
import { extent, group, bisector } from 'd3-array'
import { axisLeft, axisBottom } from 'd3-axis'
import { timeMonth, timeWeek, timeDay } from 'd3-time'
import { timeFormat } from 'd3-time-format'
import { line, curveMonotoneX } from 'd3-shape'
import { pointer } from 'd3-selection'
import { GraphStyles } from '../../styles/GraphStyles'

// Helper function to calculate price impact
const calculatePriceImpact = (eventDate, priceHistory, outcomes) => {
    const eventTime = eventDate.getTime()
    const before1h = eventTime - (1 * 60 * 60 * 1000)
    const after4h = eventTime + (4 * 60 * 60 * 1000)

    const firstTokenId = Object.keys(priceHistory)[0]
    if (!firstTokenId) return null

    const history = priceHistory[firstTokenId]
    if (!Array.isArray(history) || history.length === 0) return null

    let priceBefore = null
    let priceAfter = null

    for (let point of history) {
        const pointTime = point.t * 1000
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
    const deltaPercent = delta * 100

    return {
        delta: deltaPercent,
        direction: delta > 0.02 ? 'up' : delta < -0.02 ? 'down' : 'neutral',
        priceBefore: priceBefore.price,
        priceAfter: priceAfter.price
    }
}

const getEventMarkerColor = (event, isTarget) => {
    if (isTarget) return GraphStyles.nodeColors.target || '#f59e0b'
    if (event.properties?.is_actual_outcome) return GraphStyles.nodeColors.outcome || '#FFC107'
    if (event.isOutcome || event.properties?.is_outcome) return '#FDB022'

    const impactDirection = event._impactDirection || event.impact_direction || event.properties?.impact_direction
    if (impactDirection) {
        if (impactDirection === 'positive') return GraphStyles.linkColors.impact_positive
        if (impactDirection === 'negative') return GraphStyles.linkColors.impact_negative
        if (impactDirection === 'mixed') return GraphStyles.linkColors.impact_mixed
    }

    const status = event.properties?.status || event.status
    if (status === 'occurred') return '#10b981'
    if (status === 'predicted' || status === 'uncertain') return '#3b82f6'

    const eventDate = event.occurred_date || event.predicted_date
    if (eventDate && new Date(eventDate) < new Date()) return '#10b981'

    return GraphStyles.nodeColors[event.domain] || event.color || GraphStyles.nodeColors.general || '#3b82f6'
}

export function drawTimeSeriesChart(svgElement, params) {
    const {
        priceHistory, events, turningPoints, leadChanges, outcomes, tokenOutcomes,
        width, height,
        setHoveredEvent, setHoveredEventImpact, setHoveredTurningPoint,
        setHoveredLeadChange, setHoveredPrice
    } = params

    const margin = { top: 40, right: 150, bottom: 50, left: 60 }
    const allData = []
    const tokenIds = Object.keys(priceHistory)

    tokenIds.forEach((tokenId, idx) => {
        const history = priceHistory[tokenId]
        if (Array.isArray(history)) {
            history.forEach(point => {
                allData.push({
                    timestamp: point.t * 1000,
                    price: point.p,
                    tokenId: tokenId,
                    outcome: (tokenOutcomes && tokenOutcomes[tokenId]) ? tokenOutcomes[tokenId] : (outcomes[idx] || `Outcome ${idx + 1}`)
                })
            })
        }
    })

    const svg = select(svgElement)
    svg.selectAll('*').remove()
    const innerWidth = width - margin.left - margin.right

    if (allData.length === 0) {
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

    const xExtent = extent(allData, d => d.timestamp)
    const xScaleDomain = [new Date(xExtent[0]), new Date(xExtent[1])]
    const xScale = scaleTime().domain(xScaleDomain).range([0, innerWidth])

    let eventsInTimeRange = []
    let maxLevel = 0
    const levelHeight = 20

    if (Array.isArray(events) && events.length > 0) {
        eventsInTimeRange = events.filter(event => {
            if (!event.occurred_date && !event.predicted_date) return false
            const eventDate = new Date(event.occurred_date || event.predicted_date)
            return eventDate >= xScaleDomain[0] && eventDate <= xScaleDomain[1]
        })

        const eventNodes = eventsInTimeRange.map(event => {
            const date = new Date(event.occurred_date || event.predicted_date)
            return { ...event, xPos: xScale(date), level: 0 }
        }).sort((a, b) => a.xPos - b.xPos)

        const lanes = []
        const minNodeDist = 15

        eventNodes.forEach(node => {
            let laneIdx = 0
            while (true) {
                if (!lanes[laneIdx] || node.xPos >= lanes[laneIdx] + minNodeDist) {
                    lanes[laneIdx] = node.xPos
                    node.level = laneIdx
                    break
                }
                laneIdx++
            }
        })

        maxLevel = Math.max(0, ...eventNodes.map(n => n.level))
        eventsInTimeRange = eventNodes
    }

    const requiredTop = 40 + (maxLevel * levelHeight)
    margin.top = Math.max(margin.top, requiredTop)
    const innerHeight = height - margin.top - margin.bottom

    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)

    const yScale = scaleLinear().domain([0, 1]).range([innerHeight, 0]).nice()
    const colorScale = scaleOrdinal().domain(outcomes).range(['#4CAF50', '#F44336', '#2196F3', '#FF9800'])

    // Grid
    g.append('g')
        .attr('class', 'grid')
        .attr('opacity', 0.15)
        .call(axisLeft(yScale).tickSize(-innerWidth).tickFormat(''))
        .selectAll('line').style('stroke', '#dee2e6')

    // X axis
    const timeRange = xScale.domain()[1] - xScale.domain()[0]
    const daysRange = timeRange / (1000 * 60 * 60 * 24)

    let tickInterval, tickFormatFunc
    if (daysRange > 180) { tickInterval = timeMonth.every(1); tickFormatFunc = timeFormat('%b %Y') }
    else if (daysRange > 60) { tickInterval = timeWeek.every(2); tickFormatFunc = timeFormat('%b %d') }
    else if (daysRange > 30) { tickInterval = timeWeek.every(1); tickFormatFunc = timeFormat('%b %d') }
    else if (daysRange > 7) { tickInterval = timeDay.every(3); tickFormatFunc = timeFormat('%b %d') }
    else { tickInterval = timeDay.every(1); tickFormatFunc = timeFormat('%b %d') }

    const xAxis = g.append('g')
        .attr('transform', `translate(0,${innerHeight})`)
        .call(axisBottom(xScale).ticks(tickInterval).tickFormat(tickFormatFunc))

    xAxis.selectAll('text')
        .style('fill', '#495057')
        .style('font-size', '11px')
        .attr('transform', 'rotate(-45)')
        .style('text-anchor', 'end')
    xAxis.selectAll('line').style('stroke', '#dee2e6')
    xAxis.select('.domain').style('stroke', '#dee2e6')

    // Y axis
    const yAxis = g.append('g')
        .call(axisLeft(yScale).ticks(5).tickFormat(d => `${(d * 100).toFixed(0)}%`))
    yAxis.selectAll('text').style('fill', '#495057').style('font-size', '12px')
    yAxis.selectAll('line').style('stroke', '#dee2e6')
    yAxis.select('.domain').style('stroke', '#dee2e6')

    g.append('text').attr('x', innerWidth / 2).attr('y', innerHeight + 40).attr('text-anchor', 'middle')
        .style('fill', '#6c757d').style('font-size', '13px').style('font-weight', '500').text('Date')
    g.append('text').attr('transform', 'rotate(-90)').attr('x', -innerHeight / 2).attr('y', -40).attr('text-anchor', 'middle')
        .style('fill', '#6c757d').style('font-size', '13px').style('font-weight', '500').text('Market Probability')

    const lineGenerator = line()
        .x(d => xScale(new Date(d.timestamp)))
        .y(d => yScale(d.price))
        .curve(curveMonotoneX)

    const dataByOutcome = group(allData, d => d.outcome)

    dataByOutcome.forEach((data, outcome) => {
        g.append('path')
            .datum(data)
            .attr('fill', 'none')
            .attr('stroke', colorScale(outcome))
            .attr('stroke-width', 2.5)
            .attr('d', lineGenerator)
            .style('opacity', 0.9)
    })

    const legend = g.append('g').attr('transform', `translate(${innerWidth + 20}, 0)`)
    outcomes.forEach((outcome, idx) => {
        const legendRow = legend.append('g').attr('transform', `translate(0, ${idx * 25})`)
        legendRow.append('rect').attr('width', 15).attr('height', 15).attr('fill', colorScale(outcome))
        legendRow.append('text').attr('x', 20).attr('y', 12).style('fill', '#495057').style('font-size', '12px')
            .style('font-weight', '500').text(outcome)
    })

    // Event Markers
    if (eventsInTimeRange.length > 0) {
        eventsInTimeRange.forEach((event) => {
            const x = event.xPos
            const isTarget = event.is_actual_outcome || event.properties?.is_actual_outcome
            const markerColor = getEventMarkerColor(event, isTarget)
            const level = event.level || 0
            const yOffset = -15 - (level * levelHeight)
            const eventDate = new Date(event.occurred_date || event.predicted_date)
            const impact = calculatePriceImpact(eventDate, priceHistory, outcomes)

            g.append('line')
                .attr('x1', x).attr('x2', x).attr('y1', yOffset + 6).attr('y2', innerHeight)
                .attr('stroke', markerColor).attr('stroke-width', isTarget ? 2 : 1)
                .attr('stroke-dasharray', isTarget ? '0' : '5,5').attr('opacity', 0.4).style('pointer-events', 'none')

            const markerCircle = g.append('circle')
                .attr('cx', x).attr('cy', yOffset).attr('r', isTarget ? 8 : 6)
                .attr('fill', markerColor).attr('stroke', '#ffffff').attr('stroke-width', 2)
                .style('cursor', 'pointer').style('filter', 'drop-shadow(0 2px 4px rgba(0,0,0,0.15))')
                .on('mouseenter', function () {
                    setHoveredEvent({ ...event, _markerColor: markerColor })
                    setHoveredEventImpact(impact)
                    select(this).attr('r', isTarget ? 10 : 8).attr('stroke-width', 3)
                })
                .on('mouseleave', function () {
                    setHoveredEvent(null)
                    setHoveredEventImpact(null)
                    select(this).attr('r', isTarget ? 8 : 6).attr('stroke-width', 2)
                })

            if (isTarget) {
                const pulseCircle = g.append('circle').attr('cx', x).attr('cy', yOffset).attr('r', 8)
                    .attr('fill', 'none').attr('stroke', '#f59e0b').attr('stroke-width', 2).attr('opacity', 0.8)
                    .style('pointer-events', 'none')
                function pulse() {
                    pulseCircle.attr('r', 8).attr('opacity', 0.8).transition().duration(2000)
                        .attr('r', 16).attr('opacity', 0).on('end', pulse)
                }
                pulse()
                g.append('text').attr('x', x).attr('y', yOffset - 13).attr('text-anchor', 'middle').style('fill', '#f59e0b')
                    .style('font-size', '10px').style('font-weight', 'bold').style('text-shadow', '0 1px 2px rgba(0,0,0,0.2)')
                    .text('🎯 TARGET')
            }

            if (!isTarget && eventsInTimeRange.length <= 15 && level < 2) {
                const title = event.title || event.name || event.label || event.properties?.title || 'EVT'
                g.append('text').attr('x', x).attr('y', yOffset - 10).attr('text-anchor', 'middle')
                    .style('fill', markerColor).style('font-size', '9px').style('font-weight', 'bold')
                    .style('text-shadow', '0 1px 2px rgba(0,0,0,0.1)').text(title.substring(0, 3).toUpperCase())
            }

            if (impact && impact.direction !== 'neutral') {
                const impactColor = impact.direction === 'up' ? '#22c55e' : '#ef4444'
                const impactArrow = impact.direction === 'up' ? '↗' : '↘'
                const priceY = yScale(impact.priceAfter)

                if (isFinite(priceY)) {
                    const midX = x + 25
                    const midY = (yOffset + 10 + priceY) / 2
                    const path = `M ${x},${yOffset + 10} Q ${midX},${midY} ${x + 20},${priceY}`

                    g.append('path').attr('d', path).attr('fill', 'none').attr('stroke', impactColor)
                        .attr('stroke-width', 1.5).attr('opacity', 0.6).attr('stroke-dasharray', '3,2').style('pointer-events', 'none')
                    g.append('circle').attr('cx', x + 20).attr('cy', priceY).attr('r', 2).attr('fill', impactColor).style('pointer-events', 'none')
                    g.append('text').attr('x', x + 15).attr('y', midY - 2).attr('text-anchor', 'middle').style('fill', impactColor)
                        .style('font-size', '9px').style('font-weight', 'bold').style('text-shadow', '0 1px 2px rgba(255,255,255,0.8)')
                        .text(`${impactArrow} ${Math.abs(impact.delta).toFixed(1)}pp`)
                }
            }
        })

        const eventLegend = g.append('g').attr('transform', `translate(${innerWidth + 20}, ${outcomes.length * 25 + 20})`)
        eventLegend.append('text').attr('y', 0).style('fill', '#495057').style('font-size', '11px').style('font-weight', 'bold').text('Events:')

        const hasActualOutcome = eventsInTimeRange.some(e => e.is_actual_outcome || e.properties?.is_actual_outcome)
        if (hasActualOutcome) {
            eventLegend.append('circle').attr('cx', 5).attr('cy', 18).attr('r', 5).attr('fill', '#f59e0b').attr('stroke', '#ffffff').attr('stroke-width', 1)
            eventLegend.append('text').attr('x', 15).attr('y', 22).style('fill', '#495057').style('font-size', '10px').text('Outcome')
        }

        eventLegend.append('circle').attr('cx', 5).attr('cy', hasActualOutcome ? 35 : 18).attr('r', 4).attr('fill', '#4a90e2').attr('stroke', '#ffffff').attr('stroke-width', 1)
        eventLegend.append('text').attr('x', 15).attr('y', hasActualOutcome ? 39 : 22).style('fill', '#495057').style('font-size', '10px').text(`Events (${eventsInTimeRange.length - (hasActualOutcome ? 1 : 0)})`)
    }

    // Turning Point Markers
    if (Array.isArray(turningPoints) && turningPoints.length > 0) {
        const turningPointsInRange = turningPoints.filter(tp => {
            const tpTime = tp.timestamp * 1000
            return tpTime >= xScale.domain()[0].getTime() && tpTime <= xScale.domain()[1].getTime()
        })

        turningPointsInRange.forEach((tp, idx) => {
            const x = xScale(new Date(tp.timestamp * 1000))
            const y = yScale(tp.price)
            const isPeak = tp.type === 'peak'
            const color = isPeak ? '#ef4444' : '#22c55e'

            const diamondSize = 6
            const diamondPath = `M ${x} ${y - diamondSize} L ${x + diamondSize} ${y} L ${x} ${y + diamondSize} L ${x - diamondSize} ${y} Z`

            g.append('path').attr('d', diamondPath).attr('fill', color).attr('stroke', '#ffffff').attr('stroke-width', 2)
                .style('cursor', 'pointer').style('filter', 'drop-shadow(0 2px 4px rgba(0,0,0,0.2))')
                .on('mouseenter', function () {
                    setHoveredTurningPoint(tp)
                    select(this).attr('transform', `scale(1.3)`).attr('transform-origin', `${x}px ${y}px`)
                })
                .on('mouseleave', function () {
                    setHoveredTurningPoint(null)
                    select(this).attr('transform', null)
                })

            if (tp.significance >= 15 || idx < 3) {
                g.append('text').attr('x', x).attr('y', isPeak ? y - 12 : y + 16).attr('text-anchor', 'middle')
                    .style('fill', color).style('font-size', '9px').style('font-weight', 'bold').style('pointer-events', 'none')
                    .text(isPeak ? '▼' : '▲')
            }
        })

        const tpLegendY = (eventsInTimeRange.length > 0 ? 55 : 0) + outcomes.length * 25 + 20
        const tpLegend = g.append('g').attr('transform', `translate(${innerWidth + 20}, ${tpLegendY})`)
        tpLegend.append('text').attr('y', 0).style('fill', '#495057').style('font-size', '11px').style('font-weight', 'bold').text('Turning Points:')

        tpLegend.append('path').attr('d', 'M 5 8 L 9 12 L 5 16 L 1 12 Z').attr('fill', '#ef4444').attr('stroke', '#ffffff').attr('stroke-width', 1)
        tpLegend.append('text').attr('x', 15).attr('y', 16).style('fill', '#495057').style('font-size', '10px').text(`Peaks (${turningPointsInRange.filter(t => t.type === 'peak').length})`)

        tpLegend.append('path').attr('d', 'M 5 25 L 9 29 L 5 33 L 1 29 Z').attr('fill', '#22c55e').attr('stroke', '#ffffff').attr('stroke-width', 1)
        tpLegend.append('text').attr('x', 15).attr('y', 33).style('fill', '#495057').style('font-size', '10px').text(`Troughs (${turningPointsInRange.filter(t => t.type === 'trough').length})`)
    }

    // Lead Changes
    if (Array.isArray(leadChanges) && leadChanges.length > 0) {
        const leadChangesInRange = leadChanges.filter(lc => {
            const lcTime = lc.timestamp * 1000
            return lcTime >= xScale.domain()[0].getTime() && lcTime <= xScale.domain()[1].getTime()
        })

        leadChangesInRange.forEach((lc) => {
            const x = xScale(new Date(lc.timestamp * 1000))
            const y = yScale(lc.price)
            const crossedAbove = lc.direction === 'above'
            const color = crossedAbove ? '#2563eb' : '#f59e0b'

            g.append('circle').attr('cx', x).attr('cy', y).attr('r', 6).attr('fill', '#ffffff').attr('stroke', color)
                .attr('stroke-width', 2.5).style('cursor', 'pointer').style('filter', 'drop-shadow(0 2px 4px rgba(0,0,0,0.15))')
                .on('mouseenter', function () {
                    setHoveredLeadChange(lc)
                    select(this).attr('r', 8)
                })
                .on('mouseleave', function () {
                    setHoveredLeadChange(null)
                    select(this).attr('r', 6)
                })

            g.append('text').attr('x', x).attr('y', y + 3).attr('text-anchor', 'middle').style('fill', color)
                .style('font-size', '9px').style('font-weight', '700').style('pointer-events', 'none').text(crossedAbove ? '↑' : '↓')
        })

        const baseLegendY = (eventsInTimeRange.length > 0 ? 55 : 0) + outcomes.length * 25 + 20
        const hasTurningPoints = Array.isArray(turningPoints) && turningPoints.length > 0
        const leadLegendY = hasTurningPoints ? baseLegendY + 50 : baseLegendY
        const leadLegend = g.append('g').attr('transform', `translate(${innerWidth + 20}, ${leadLegendY})`)

        leadLegend.append('text').attr('y', 0).style('fill', '#495057').style('font-size', '11px').style('font-weight', 'bold').text('Lead Changes:')
        leadLegend.append('circle').attr('cx', 5).attr('cy', 12).attr('r', 4).attr('fill', '#ffffff').attr('stroke', '#2563eb').attr('stroke-width', 2)
        leadLegend.append('text').attr('x', 15).attr('y', 16).style('fill', '#495057').style('font-size', '10px').text(`Crossed Above (${leadChangesInRange.filter(l => l.direction === 'above').length})`)
        leadLegend.append('circle').attr('cx', 5).attr('cy', 28).attr('r', 4).attr('fill', '#ffffff').attr('stroke', '#f59e0b').attr('stroke-width', 2)
        leadLegend.append('text').attr('x', 15).attr('y', 32).style('fill', '#495057').style('font-size', '10px').text(`Crossed Below (${leadChangesInRange.filter(l => l.direction === 'below').length})`)
    }

    // Interactive tooltip line
    const tooltipLine = g.append('line').attr('stroke', '#6c757d').attr('stroke-width', 1).attr('stroke-dasharray', '3,3').style('opacity', 0)
    const tooltipCircles = []
    dataByOutcome.forEach((data, outcome) => {
        const circle = g.append('circle').attr('r', 4).attr('fill', colorScale(outcome)).attr('stroke', '#fff').attr('stroke-width', 2).style('opacity', 0)
        tooltipCircles.push({ circle, outcome })
    })

    // Overlay
    g.append('rect').attr('width', innerWidth).attr('height', innerHeight).attr('fill', 'none').attr('pointer-events', 'all')
        .on('mousemove', function (event) {
            const [mouseX] = pointer(event)
            const hoveredDate = xScale.invert(mouseX)

            tooltipLine.attr('x1', mouseX).attr('x2', mouseX).attr('y1', 0).attr('y2', innerHeight).style('opacity', 0.5)

            const priceInfo = []
            dataByOutcome.forEach((data, outcome) => {
                const bisectFunc = bisector(d => d.timestamp).left
                const idx = bisectFunc(data, hoveredDate.getTime())
                const closestPoint = data[idx] || data[data.length - 1]

                if (closestPoint) {
                    priceInfo.push({ outcome, price: closestPoint.price, timestamp: closestPoint.timestamp })
                }
            })

            tooltipCircles.forEach(({ circle, outcome }) => {
                const info = priceInfo.find(p => p.outcome === outcome)
                if (info) circle.attr('cx', mouseX).attr('cy', yScale(info.price)).style('opacity', 1)
            })

            setHoveredPrice(priceInfo)
        })
        .on('mouseleave', function () {
            tooltipLine.style('opacity', 0)
            tooltipCircles.forEach(({ circle }) => circle.style('opacity', 0))
            setHoveredPrice(null)
        })
}
