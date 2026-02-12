
import React, { useRef, useEffect, useState, useMemo } from 'react'
import * as d3 from 'd3'
import { GraphLegend } from '../utils/graphRendering.jsx'
import { GraphStyles } from '../styles/GraphStyles' // Import Styles
import './ChronologicalGraph.css'

/**
 * ChronologicalGraph (v2 - Constrained Physics & LOD)
 * 
 * A D3-based visualization that arranges nodes on a timeline (X-axis)
 * while using physics to prevent vertical overlap (Y-axis).
 * 
 * Features:
 * - Constrained Force Layout: Nodes are pulled strongly to their DATE (x) and effectively collision-detected.
 * - Semantic Zoom (LOD): 
 *    - Scale < 0.65: Renders as "DOTS" (activity heatmap style)
 *    - Scale >= 0.65: Renders as "CARDS" (detailed view)
 * - Time Traversal: Dims nodes outside the `timeFilter` range.
 */
const ChronologicalGraph = ({
    graphData,
    width,
    height,
    onNodeClick,
    selectedNode,
    timeFilter = null, // { start: Date, end: Date } from Timeline
    padding = { top: 40, right: 100, bottom: 60, left: 100 }
}) => {
    const svgRef = useRef(null)
    const containerRef = useRef(null)
    const [dimensions, setDimensions] = useState({ width: width || 800, height: height || 600 })
    const [viewMode, setViewMode] = useState('cards') // 'dots' | 'cards'
    const simulationRef = useRef(null)

    // Configuration Constants
    const CARD_WIDTH = 160
    const CARD_HEIGHT = 70
    const DOT_RADIUS = 6
    const LOD_THRESHOLD = 0.65

    // 1. Responsive Dimensions
    useEffect(() => {
        if (!containerRef.current) return
        const updateDimensions = () => {
            if (containerRef.current) {
                setDimensions(prev => {
                    // Only update if changed to avoid loops
                    const w = containerRef.current.clientWidth
                    const h = containerRef.current.clientHeight
                    if (prev.width === w && prev.height === h) return prev
                    return { width: w, height: h }
                })
            }
        }
        updateDimensions()
        const observer = new ResizeObserver(updateDimensions)
        observer.observe(containerRef.current)
        return () => observer.disconnect()
    }, [width, height])


    // 2. Data Preparation
    const rawNodes = useMemo(() => {
        if (!graphData?.nodes) return []

        // Helper to validate date
        const isValidDate = (d) => d instanceof Date && !isNaN(d)

        // Filter valid dated nodes and clone
        return graphData.nodes
            .map(n => ({
                ...n,
                _date: new Date(n.properties?.occurred_date || n.properties?.predicted_date)
            }))
            .filter(n => isValidDate(n._date)) // Strict filter
            .sort((a, b) => a._date - b._date)
    }, [graphData])

    const timeDomain = useMemo(() => {
        if (rawNodes.length === 0) return [new Date(), new Date()]
        const min = rawNodes[0]._date
        const max = rawNodes[rawNodes.length - 1]._date
        // Add 5% buffer
        const span = max - min || 86400000
        return [new Date(min.getTime() - span * 0.05), new Date(max.getTime() + span * 0.05)]
    }, [rawNodes])



    // 3. D3 Layout & Rendering Engine
    useEffect(() => {
        if (rawNodes.length === 0 || !svgRef.current) return

        let currentMode = 'cards' // Closure variable for d3 events
        const { width, height } = dimensions
        const svg = d3.select(svgRef.current)
        svg.selectAll("*").remove()

        // --- Scales ---
        const xScale = d3.scaleTime()
            .domain(timeDomain)
            .range([padding.left, width - padding.right])

        const centerY = height / 2

        // --- Simulation Setup ---
        const nodes = rawNodes.map(n => ({ ...n }))
        const links = (graphData.links || []).map(l => ({ ...l }))

        nodes.forEach(n => {
            n.fx = xScale(n._date)
            // Initial Y jitter
            n.y = centerY + (Math.random() - 0.5) * 100
        })

        // Improved Collision:
        // Use a much larger radius to represent the width of the cards.
        // Since X is fixed, this forces Y separation.
        const simulation = d3.forceSimulation(nodes)
            .force("y", d3.forceY(centerY).strength(0.02)) // Very weak centering to allow spread
            .force("collide", d3.forceCollide()
                .radius(100) // Radius ~ 60% of card width
                .strength(0.8)
                .iterations(3)
            )
            .stop()

        // Run simulation
        for (let i = 0; i < 300; i++) simulation.tick()
        simulationRef.current = simulation

        // --- Render Groups ---
        const gMain = svg.append("g").attr("class", "main-group")
        const gLinks = gMain.append("g").attr("class", "links-layer")
        const gNodes = gMain.append("g").attr("class", "nodes-layer")
        const gAxis = svg.append("g").attr("class", "axis-layer")

        // Link Path Generator - Simple straight line
        const getLinkPath = (d) => {
            // Direct line from center to center
            return `M${d.source.x},${d.source.y} L${d.target.x},${d.target.y}`
        }

        // --- Zoom Behavior ---
        const zoom = d3.zoom()
            .scaleExtent([0.1, 8])
            .on("zoom", (event) => {
                const { k } = event.transform

                // 1. Semantic LOD check
                const newMode = k < LOD_THRESHOLD ? 'dots' : 'cards'
                const modeChanged = newMode !== currentMode

                if (modeChanged) {
                    currentMode = newMode
                    updateVisibility()
                    setViewMode(newMode)
                }

                // 2. Apply Transform
                gMain.attr("transform", event.transform)

                // 3. Semantic Axis (Rescale)
                drawAxis(event.transform.rescaleX(xScale))

                // 4. Update Links 
                // Thinner lines to avoid clutter (1.5px screen width)
                gLinks.selectAll("path")
                    .attr("stroke-width", 1.5 / k)

                // CRITICAL FIX: If mode changed, we MUST re-calculate path geometric data
                if (modeChanged) {
                    gLinks.selectAll("path").attr("d", getLinkPath)
                }
            })

        svg.call(zoom)
            .on("dblclick.zoom", null)

        // Helper: Draw Axis
        const drawAxis = (scale) => {
            gAxis.selectAll("*").remove()
            const axis = d3.axisBottom(scale)
                .ticks(Math.max(width / 150, 2))
                .tickSizeInner(-height + padding.top + padding.bottom)
                .tickPadding(10)

            const axisG = gAxis.append("g")
                .attr("transform", `translate(0, ${height - padding.bottom})`)
                .call(axis)

            axisG.selectAll(".tick line")
                .attr("stroke", "#f1f5f9")
                .attr("stroke-dasharray", "4,4")
            axisG.select(".domain").attr("stroke", "#e2e8f0")
            axisG.selectAll("text")
                .attr("fill", "#94a3b8")
                .style("font-size", "11px")
                .style("font-weight", "500")
        }
        drawAxis(xScale) // Initial

        // --- Draw Links ---
        // Need to identify color for "marker-end" reference
        const getRelationColor = (l) => {
            const type = l.relation_type || l.type || 'default'
            const key = type.toLowerCase().replace(/ /g, '_')
            return GraphStyles.linkColors[key] || GraphStyles.linkColors.default || '#94a3b8'
        }

        const nodeMap = new Map(nodes.map(n => [n.id, n]))
        const validLinks = links.filter(l =>
            nodeMap.has(l.source.id || l.source) &&
            nodeMap.has(l.target.id || l.target)
        ).map(l => ({
            ...l,
            source: nodeMap.get(l.source.id || l.source),
            target: nodeMap.get(l.target.id || l.target)
        }))

        gLinks.selectAll("path")
            .data(validLinks)
            .enter()
            .append("path")
            .attr("class", "chrono-link")
            .attr("d", getLinkPath)
            .attr("fill", "none")
            // Use dynamic color
            .attr("stroke", d => getRelationColor(d))
            .attr("stroke-width", 2)
            .style("opacity", 0.6)
            // Use marker matching the color
            .attr("marker-end", d => {
                const type = d.relation_type || d.type || 'default'
                const key = type.toLowerCase().replace(/ /g, '_')
                // Only use markers for known types with colors to avoid missing refs
                if (GraphStyles.linkColors[key]) return `url(#arrow-${key})`
                return `url(#arrow-default)`
            })

        // --- Draw Nodes ---
        const nodeGroups = gNodes.selectAll(".node-wrapper")
            .data(nodes)
            .enter()
            .append("g")
            .attr("class", "node-wrapper")
            .attr("transform", d => `translate(${d.x}, ${d.y})`)

        // Helper: Get status class matching Legend
        const getStatusClass = (d) => {
            if (d.isOutcome || d.properties?.is_actual_outcome) return 'target'
            const status = d.properties?.status || d.status
            if (status === 'occurred') return 'confirmed'
            if (status === 'predicted') return 'predicted'
            // Fallback: Past = Confirmed, Future = Predicted
            return (d._date < new Date()) ? 'confirmed' : 'predicted'
        }

        // 1. DOTS
        nodeGroups.append("circle")
            .attr("class", d => `chrono-dot ${getStatusClass(d)}`)
            .attr("r", d => (d.isOutcome || d.properties?.is_actual_outcome) ? 8 : 5)
            .on("click", (e, d) => { e.stopPropagation(); onNodeClick(d); })

        // 2. CARDS
        const fo = nodeGroups.append("foreignObject")
            .attr("class", "node-fo")
            .attr("width", CARD_WIDTH)
            .attr("height", CARD_HEIGHT)
            .attr("x", -CARD_WIDTH / 2)
            .attr("y", -CARD_HEIGHT / 2)

        fo.append("xhtml:div")
            .attr("class", d => `chrono-node ${getStatusClass(d)} ${d.id === selectedNode?.id ? 'selected' : ''}`)
            .on("click", (e, d) => { e.stopPropagation(); onNodeClick(d); })
            .html(d => `
                <div class="node-header">
                  <span class="node-date">${d._date.toLocaleDateString(undefined, { month: 'numeric', day: 'numeric' })}</span>
                  <span class="node-type-badge">${d.type || 'Event'}</span>
                </div>
                <div class="node-title">${d.name}</div>
            `)

        // Visibility Updater
        const updateVisibility = () => {
            if (currentMode === 'dots') {
                gNodes.selectAll(".node-fo").style("display", "none")
                gNodes.selectAll(".chrono-dot").style("display", "block").style("opacity", 1)
            } else {
                gNodes.selectAll(".node-fo").style("display", "block")
                gNodes.selectAll(".chrono-dot").style("display", "none")
            }
        }
        updateVisibility() // Initial

        // Visibility / Dimming
        svg.node().updateDimming = (filter) => {
            if (!filter || !filter.start || !filter.end) {
                gNodes.selectAll(".chrono-node, .chrono-dot").classed("dimmed", false)
                return
            }
            gNodes.selectAll(".node-wrapper").each(function (d) {
                const isVisible = d._date >= filter.start && d._date <= filter.end
                d3.select(this).select(".chrono-node").classed("dimmed", !isVisible)
                d3.select(this).select(".chrono-dot").classed("dimmed", !isVisible)
            })
        }

    }, [rawNodes, dimensions, selectedNode]) // Depend on rawNodes to re-sim

    // 4. Handle Time Filter Updates (Efficiently)
    useEffect(() => {
        if (svgRef.current && svgRef.current.updateDimming) {
            svgRef.current.updateDimming(timeFilter)
        }
    }, [timeFilter])


    return (
        <div className="chronological-graph-container" ref={containerRef}>
            <svg
                ref={svgRef}
                width={dimensions.width}
                height={dimensions.height}
                style={{ width: '100%', height: '100%', display: 'block' }}
            >
                <defs>
                    {/* Generate a marker for every link color in GraphStyles */}
                    {Object.entries(GraphStyles.linkColors).map(([key, color]) => (
                        <marker
                            key={key}
                            id={`arrow-${key}`}
                            viewBox="0 0 10 10"
                            refX="9" // Tip of the arrow
                            refY="5" // Center
                            markerWidth="6"
                            markerHeight="6"
                            orient="auto-start-reverse"
                        >
                            <path d="M 0 0 L 10 5 L 0 10 z" fill={color} />
                        </marker>
                    ))}
                    {/* Add default marker just in case */}
                    <marker id="arrow-default" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                        <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
                    </marker>

                    <filter id="glow">
                        <feGaussianBlur stdDeviation="2.5" result="coloredBlur" />
                        <feMerge>
                            <feMergeNode in="coloredBlur" />
                            <feMergeNode in="SourceGraphic" />
                        </feMerge>
                    </filter>
                </defs>
            </svg>

            <div className="graph-overlay-controls">
                <button
                    className="control-btn"
                    onClick={() => {
                        const svg = d3.select(svgRef.current)
                        svg.transition().duration(750).call(d3.zoom().transform, d3.zoomIdentity)
                    }}
                    title="Reset View"
                >
                    ⟲
                </button>
            </div>

            <GraphLegend />
        </div>
    )
}

export default ChronologicalGraph
