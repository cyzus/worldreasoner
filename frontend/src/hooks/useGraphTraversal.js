import { useCallback } from 'react'
import { useGraphStore } from '../stores/graphStore'
import { useQuestionStore } from '../stores/questionStore'
import { fetchQuestionEvents } from '../api/graphApi'

/**
 * Hook to handle complex graph traversals like neighborhood view and question filtering
 */
export const useGraphTraversal = (questions) => {
    // Graph store
    const fullGraphData = useGraphStore(state => state.fullGraphData)
    const setGraphData = useGraphStore(state => state.setGraphData)
    const setSelectedNode = useGraphStore(state => state.setSelectedNode)
    const setTimeFilter = useGraphStore(state => state.setTimeFilter)

    // Question store
    const setSelectedQuestionId = useQuestionStore(state => state.setSelectedQuestion)
    const setPriceHistoryData = useQuestionStore(state => state.setPriceHistoryData)
    const setQuestionRelatedEvents = useQuestionStore(state => state.setQuestionRelatedEvents)
    const setPriceHistoryInterval = useQuestionStore(state => state.setPriceHistoryInterval)

    // Handle neighborhood view (client-side filtering)
    const handleShowNeighborhood = useCallback((nodeId, depth = 2) => {
        // Find the center node
        const centerNode = fullGraphData.nodes.find(n => n.id === nodeId)
        if (!centerNode) return

        // BFS to find neighborhood
        const visited = new Set([nodeId])
        const queue = [{ id: nodeId, depth: 0 }]

        // Only use real links, not synthetic ones
        const realLinks = fullGraphData.links.filter(link => !link.isSynthetic && link.type !== 'potentially_relevant')

        while (queue.length > 0) {
            const { id: currentId, depth: currentDepth } = queue.shift()

            if (currentDepth >= depth) continue

            // Find outgoing links
            realLinks.forEach(link => {
                const sourceId = typeof link.source === 'object' ? link.source.id : link.source
                const targetId = typeof link.target === 'object' ? link.target.id : link.target

                if (sourceId === currentId && !visited.has(targetId)) {
                    visited.add(targetId)
                    queue.push({ id: targetId, depth: currentDepth + 1 })
                }

                // Also check incoming links
                if (targetId === currentId && !visited.has(sourceId)) {
                    visited.add(sourceId)
                    queue.push({ id: sourceId, depth: currentDepth + 1 })
                }
            })
        }

        // Filter nodes and links, clear outcome markers
        const neighborhoodNodes = fullGraphData.nodes
            .filter(n => visited.has(n.id))
            .map(node => ({
                ...node,
                isOutcome: false
            }))

        const neighborhoodLinks = realLinks.filter(link => {
            const sourceId = typeof link.source === 'object' ? link.source.id : link.source
            const targetId = typeof link.target === 'object' ? link.target.id : link.target
            return visited.has(sourceId) && visited.has(targetId)
        }).map(link => ({
            ...link,
            source: typeof link.source === 'object' ? link.source.id : link.source,
            target: typeof link.target === 'object' ? link.target.id : link.target
        }))

        const neighborhoodData = {
            nodes: neighborhoodNodes,
            links: neighborhoodLinks,
        }
        setGraphData(neighborhoodData)


        // Clear time filter and question filter when showing neighborhood
        setTimeFilter(null)
        setSelectedQuestionId(null)
    }, [fullGraphData, setGraphData, setTimeFilter, setSelectedQuestionId])

    // Handle question filter
    const handleQuestionFilter = useCallback(async (questionId, depth = 2) => {
        if (!questionId) {
            console.log('Clearing question filter - resetting to full graph')
            // No filter, show all data and clear outcome markers
            // Create fresh copies to ensure synthetic edges are removed
            const resetNodes = fullGraphData.nodes.map(node => ({
                ...node,
                isOutcome: false
            }))

            // Filter out any synthetic links and create fresh copies
            const resetLinks = fullGraphData.links
                .filter(link => !link.isSynthetic && link.type !== 'potentially_relevant')
                .map(link => ({ ...link }))

            console.log(`Resetting graph: ${resetNodes.length} nodes, ${resetLinks.length} links (filtered from ${fullGraphData.links.length})`)

            const resetData = {
                nodes: resetNodes,
                links: resetLinks
            }
            setGraphData(resetData)

            setSelectedQuestionId(null)
            setTimeFilter(null)
            setPriceHistoryData(null) // Clear price history
            setQuestionRelatedEvents([]) // Clear question-related events
            setPriceHistoryInterval('max') // Reset interval to default
            return
        }

        setSelectedQuestionId(questionId)

        // Find the question
        const question = questions.find(q => q.id === questionId)
        if (!question) {
            console.warn('Question not found:', questionId)
            return
        }

        console.log('Filtering by question:', question.question_text)

        try {
            // Fetch all events related to this question (including from metadata and hypotheses)
            const questionEventsData = await fetchQuestionEvents(questionId)
            const seedEventIds = new Set(questionEventsData.event_ids)

            // Extract full event data for all question-related events (for TimeSeriesChart)
            const relatedEvents = fullGraphData.nodes
                .filter(node => seedEventIds.has(node.id))
                .map(node => ({
                    id: node.id,
                    title: node.name,
                    occurred_date: node.properties?.occurred_date,
                    predicted_date: node.properties?.predicted_date,
                }))
            setQuestionRelatedEvents(relatedEvents)
            console.log(`Stored ${relatedEvents.length} events for TimeSeriesChart`)

            console.log('=== Question Filter Statistics ===')
            console.log(`Direct events: ${questionEventsData.direct_events}`)
            console.log(`Extracted during evidence: ${questionEventsData.extracted_events}`)
            console.log(`In causal hypotheses: ${questionEventsData.hypothesis_events}`)
            console.log(`Orphaned (extracted but not in hypotheses): ${questionEventsData.orphaned_events}`)
            console.log(`Total seed events: ${questionEventsData.total_events}`)

            // BFS to find neighborhood around these events
            const visited = new Set(seedEventIds)
            const queue = Array.from(seedEventIds).map(id => ({ id, depth: 0 }))

            while (queue.length > 0) {
                const { id: currentId, depth: currentDepth } = queue.shift()

                if (currentDepth >= depth) continue

                // Find connected nodes (both incoming and outgoing)
                fullGraphData.links.forEach(link => {
                    const sourceId = typeof link.source === 'object' ? link.source.id : link.source
                    const targetId = typeof link.target === 'object' ? link.target.id : link.target

                    // Outgoing links (causes)
                    if (sourceId === currentId && !visited.has(targetId)) {
                        visited.add(targetId)
                        queue.push({ id: targetId, depth: currentDepth + 1 })
                    }

                    // Incoming links (caused by)
                    if (targetId === currentId && !visited.has(sourceId)) {
                        visited.add(sourceId)
                        queue.push({ id: sourceId, depth: currentDepth + 1 })
                    }
                })
            }

            console.log(`Expanded to ${visited.size} nodes (from ${seedEventIds.size} seed events, depth ${depth})`)

            // Debug: Check if seed events exist in fullGraphData
            const missingEventIds = Array.from(seedEventIds).filter(id => !fullGraphData.nodes.find(n => n.id === id))
            if (missingEventIds.length > 0) {
                console.warn(`⚠️ ${missingEventIds.length} seed events NOT found in fullGraphData:`, missingEventIds.slice(0, 5))
                console.log(`Full graph has ${fullGraphData.nodes.length} nodes`)
                console.log('💡 TIP: Increase "Max Nodes" in Controls panel or refresh the graph to load more events')
            }

            // Filter nodes to include the neighborhood
            const filteredNodes = fullGraphData.nodes.filter(node => visited.has(node.id))

            // Filter links to only include those between visible nodes
            const filteredLinks = fullGraphData.links.filter(link => {
                const sourceId = typeof link.source === 'object' ? link.source.id : link.source
                const targetId = typeof link.target === 'object' ? link.target.id : link.target
                return visited.has(sourceId) && visited.has(targetId)
            })

            console.log(`Filtered graph: ${filteredNodes.length} nodes, ${filteredLinks.length} links (from ${fullGraphData.links.length} total links)`)

            // Mark outcome nodes (preserve is_outcome from backend + target_event_id)
            const outcomeNodeId = question.target_event_id
            filteredNodes.forEach(node => {
                // Preserve isOutcome from backend data (outcome events have is_outcome=True)
                // Also mark target_event_id as outcome for backward compatibility
                node.isOutcome = node.properties?.is_outcome || node.id === outcomeNodeId
            })

            // Fetch and apply outcome impacts to color nodes
            try {
                const { fetchOutcomes } = await import('../api/graphApi')
                const outcomes = await fetchOutcomes(questionId)

                // For each outcome, fetch its impacts and color the source events
                for (const outcome of outcomes) {
                    try {
                        const { fetchOutcomeImpacts } = await import('../api/graphApi')
                        const impacts = await fetchOutcomeImpacts(outcome.id)

                        // Apply impact colors to nodes
                        impacts.forEach(impact => {
                            const sourceNode = filteredNodes.find(n => n.id === impact.source_id)
                            if (sourceNode) {
                                const direction = impact.properties?.impact_direction
                                console.log(`Setting impact for node ${sourceNode.name || sourceNode.id}:`, {
                                    direction,
                                    magnitude: impact.properties?.impact_magnitude,
                                    targetOutcome: outcome.id
                                })
                                // If node already has an impact, keep the stronger one
                                if (!sourceNode._impactDirection ||
                                    (direction === 'positive' || direction === 'negative')) {
                                    sourceNode._impactDirection = direction
                                    sourceNode._impactMagnitude = impact.properties?.impact_magnitude || 0

                                    // Verify it was set
                                    if ((sourceNode.name || '').includes('Santa')) {
                                        console.log(`✓ Impact set on Santa node:`, sourceNode._impactDirection, sourceNode)
                                    }
                                }
                            }
                        })
                    } catch (err) {
                        console.warn(`Failed to fetch impacts for outcome ${outcome.id}:`, err)
                    }
                }

                console.log('Applied impact colors to nodes')
            } catch (err) {
                console.warn('Failed to fetch outcomes for impact coloring:', err)
            }

            // Find orphaned nodes (nodes with no causal connections to other nodes)
            const connectedNodeIds = new Set()
            filteredLinks.forEach(link => {
                const sourceId = typeof link.source === 'object' ? link.source.id : link.source
                const targetId = typeof link.target === 'object' ? link.target.id : link.target
                connectedNodeIds.add(sourceId)
                connectedNodeIds.add(targetId)
            })

            // Identify orphaned nodes and create synthetic edges to outcome
            const syntheticLinks = []
            if (outcomeNodeId) {
                filteredNodes.forEach(node => {
                    // Node is orphaned if it's not connected AND it's not the outcome itself
                    if (!connectedNodeIds.has(node.id) && node.id !== outcomeNodeId) {
                        syntheticLinks.push({
                            source: node.id,
                            target: outcomeNodeId,
                            type: 'potentially_relevant',
                            weight: 0.3,
                            label: 'potentially relevant',
                            properties: { synthetic: true },
                            isSynthetic: true
                        })
                    }
                })
            }

            // Update with new filtered data including synthetic links
            const combinedLinks = [...filteredLinks, ...syntheticLinks]

            console.log(`Created ${syntheticLinks.length} synthetic links for orphaned nodes`)
            console.log(`Final graph data: ${filteredNodes.length} nodes, ${combinedLinks.length} links`)

            // Verify Santa node has impact before setting graph data
            const santaNode = filteredNodes.find(n => (n.name || '').includes('Santa'))
            if (santaNode) {
                console.log(`Santa node before setGraphData:`, {
                    name: santaNode.name,
                    hasImpactDirection: !!santaNode._impactDirection,
                    impactDirection: santaNode._impactDirection,
                    impactMagnitude: santaNode._impactMagnitude
                })
            }

            const questionFilteredData = {
                nodes: filteredNodes,
                links: combinedLinks,
            }
            setGraphData(questionFilteredData)

        } catch (error) {
            console.error('Failed to fetch question events:', error)
            // Fallback to old behavior using only related_event_ids
            const seedEventIds = new Set()
            if (question.target_event_id) {
                seedEventIds.add(question.target_event_id)
            }
            if (question.related_event_ids) {
                question.related_event_ids.forEach(id => seedEventIds.add(id))
            }

            const filteredNodes = fullGraphData.nodes.filter(node => seedEventIds.has(node.id))

            // Mark outcome nodes (preserve is_outcome from backend + target_event_id)
            const outcomeNodeId = question.target_event_id
            filteredNodes.forEach(node => {
                // Preserve isOutcome from backend data (outcome events have is_outcome=True)
                // Also mark target_event_id as outcome for backward compatibility
                node.isOutcome = node.properties?.is_outcome || node.id === outcomeNodeId
            })

            // Fetch and apply outcome impacts to color nodes (fallback path)
            try {
                const { fetchOutcomes } = await import('../api/graphApi')
                const outcomes = await fetchOutcomes(questionId)

                for (const outcome of outcomes) {
                    try {
                        const { fetchOutcomeImpacts } = await import('../api/graphApi')
                        const impacts = await fetchOutcomeImpacts(outcome.id)

                        impacts.forEach(impact => {
                            const sourceNode = filteredNodes.find(n => n.id === impact.source_id)
                            if (sourceNode) {
                                const direction = impact.properties?.impact_direction
                                if (!sourceNode._impactDirection ||
                                    (direction === 'positive' || direction === 'negative')) {
                                    sourceNode._impactDirection = direction
                                    sourceNode._impactMagnitude = impact.properties?.impact_magnitude || 0
                                }
                            }
                        })
                    } catch (err) {
                        console.warn(`Failed to fetch impacts for outcome ${outcome.id}:`, err)
                    }
                }
            } catch (err) {
                console.warn('Failed to fetch outcomes for impact coloring (fallback):', err)
            }

            const nodeIds = new Set(filteredNodes.map(n => n.id))
            const filteredLinks = fullGraphData.links.filter(link => {
                const sourceId = typeof link.source === 'object' ? link.source.id : link.source
                const targetId = typeof link.target === 'object' ? link.target.id : link.target
                return nodeIds.has(sourceId) && nodeIds.has(targetId)
            })

            // Find orphaned nodes and create synthetic links
            const connectedNodeIds = new Set()
            filteredLinks.forEach(link => {
                const sourceId = typeof link.source === 'object' ? link.source.id : link.source
                const targetId = typeof link.target === 'object' ? link.target.id : link.target
                connectedNodeIds.add(sourceId)
                connectedNodeIds.add(targetId)
            })

            const syntheticLinks = []
            if (outcomeNodeId) {
                filteredNodes.forEach(node => {
                    if (!connectedNodeIds.has(node.id) && node.id !== outcomeNodeId) {
                        syntheticLinks.push({
                            source: node.id,
                            target: outcomeNodeId,
                            type: 'potentially_relevant',
                            weight: 0.3,
                            label: 'potentially relevant',
                            properties: { synthetic: true },
                            isSynthetic: true
                        })
                    }
                })
            }

            const fallbackData = { nodes: filteredNodes, links: [...filteredLinks, ...syntheticLinks] }
            setGraphData(fallbackData)

            setTimeFilter(null)
        }
    }, [fullGraphData, questions, setGraphData, setSelectedQuestionId, setQuestionRelatedEvents, setPriceHistoryData, setTimeFilter, setPriceHistoryInterval])

    return {
        handleShowNeighborhood,
        handleQuestionFilter
    }
}
