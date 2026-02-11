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

    const buildChartEvents = useCallback((nodes, seedEventIds) => {
        return nodes
            .filter(node => seedEventIds.has(node.id))
            .map(node => ({
                id: node.id,
                title: node.name,
                occurred_date: node.properties?.occurred_date,
                predicted_date: node.properties?.predicted_date,
                status: node.properties?.status || node.status,
                domain: node.domain || node.properties?.domain,
                properties: node.properties || {},
                _impactDirection: node._impactDirection,
                _impactMagnitude: node._impactMagnitude,
                isOutcome: node.isOutcome || node.properties?.is_outcome || false,
                color: node.color,
            }))
    }, [])

    const applyOutcomeAwareImpactColors = useCallback(async (nodes, questionId, outcomeNodeId = null) => {
        try {
            const { fetchOutcomes, fetchOutcomeImpacts } = await import('../api/graphApi')
            const outcomes = await fetchOutcomes(questionId)

            if (!Array.isArray(outcomes) || outcomes.length === 0) {
                return
            }

            // Determine which outcome(s) are actual ground truth.
            const actualOutcomeIds = new Set(
                outcomes
                    .filter(o => o.properties?.is_actual_outcome === true)
                    .map(o => o.id)
            )
            // Fallback: infer actual outcome from question.ground_truth when DB flags are missing.
            if (actualOutcomeIds.size === 0) {
                const question = questions.find(q => q.id === questionId)
                const rawTruth = question?.ground_truth
                const normalizedTruth = String(rawTruth ?? '')
                    .trim()
                    .replace(/^"+|"+$/g, '')
                    .toLowerCase()

                if (normalizedTruth) {
                    let matched = null

                    if (['yes', 'true', '1'].includes(normalizedTruth)) {
                        matched = outcomes.find(o =>
                            (o.properties?.outcome_scenario || '').toLowerCase() === 'positive_resolution'
                        )
                    } else if (['no', 'false', '0'].includes(normalizedTruth)) {
                        matched = outcomes.find(o =>
                            (o.properties?.outcome_scenario || '').toLowerCase() === 'negative_resolution'
                        )
                    }

                    if (!matched) {
                        matched = outcomes.find(o => {
                            const label = String(o.label || '').toLowerCase()
                            return label.startsWith(`${normalizedTruth} -`) || label === normalizedTruth
                        })
                    }

                    if (matched) {
                        actualOutcomeIds.add(matched.id)
                    }
                }
            }
            if (actualOutcomeIds.size === 0 && outcomeNodeId) {
                actualOutcomeIds.add(outcomeNodeId)
            }

            const nodeById = new Map(nodes.map(n => [n.id, n]))
            const nodeScores = new Map() // node_id -> { score, positive, negative }
            const MIN_IMPACT_CONFIDENCE = 0.55
            const CONFIDENCE_EXPONENT = 1.5

            for (const outcome of outcomes) {
                const isActualOutcome = actualOutcomeIds.has(outcome.id)
                const outcomeSign = isActualOutcome ? 1 : -1

                let impacts = []
                try {
                    impacts = await fetchOutcomeImpacts(outcome.id)
                } catch (err) {
                    console.warn(`Failed to fetch impacts for outcome ${outcome.id}:`, err)
                    continue
                }

                impacts.forEach(impact => {
                    const sourceNode = nodeById.get(impact.source_id)
                    if (!sourceNode) return

                    const direction = impact.properties?.impact_direction
                    const magnitude = Number(impact.properties?.impact_magnitude ?? impact.weight ?? 0)
                    const confidence = Number(impact.properties?.confidence ?? 1.0)
                    if (!Number.isFinite(confidence) || confidence < MIN_IMPACT_CONFIDENCE) return

                    // Confidence-aware weighting:
                    // - low-confidence impacts are filtered out
                    // - remaining impacts are weighted non-linearly by confidence
                    const confidenceWeight = Math.pow(Math.max(0, Math.min(1, confidence)), CONFIDENCE_EXPONENT)
                    const strength = Math.max(0, magnitude) * confidenceWeight

                    let impactToOutcomeSign = 0
                    if (direction === 'positive') impactToOutcomeSign = 1
                    else if (direction === 'negative') impactToOutcomeSign = -1
                    else if (direction === 'mixed' || direction === 'neutral') impactToOutcomeSign = 0
                    else return

                    // Reframe impact relative to actual outcome.
                    // Positive impact on non-actual outcome should count as negative (red), and vice versa.
                    const contribution = impactToOutcomeSign * outcomeSign * strength

                    const current = nodeScores.get(sourceNode.id) || { score: 0, positive: 0, negative: 0 }
                    current.score += contribution
                    if (contribution > 0) current.positive += contribution
                    else if (contribution < 0) current.negative += Math.abs(contribution)
                    nodeScores.set(sourceNode.id, current)
                })
            }

            // Set node impact direction based on aggregate support/opposition to actual outcome.
            nodeScores.forEach((acc, nodeId) => {
                const node = nodeById.get(nodeId)
                if (!node) return

                const absScore = Math.abs(acc.score)
                const total = acc.positive + acc.negative
                const balance = total > 0 ? Math.min(acc.positive, acc.negative) / Math.max(acc.positive, acc.negative) : 0

                if (total === 0 || absScore < 1e-8) {
                    node._impactDirection = 'mixed'
                    node._impactMagnitude = 0
                    return
                }

                // If both directions are substantial, mark as mixed.
                if (acc.positive > 0 && acc.negative > 0 && balance >= 0.35) {
                    node._impactDirection = 'mixed'
                    node._impactMagnitude = Math.min(1, absScore / total)
                    return
                }

                node._impactDirection = acc.score > 0 ? 'positive' : 'negative'
                node._impactMagnitude = Math.min(1, absScore / total)
            })

            console.log('Applied outcome-aware impact colors to nodes')
        } catch (err) {
            console.warn('Failed to apply outcome-aware impact coloring:', err)
        }
    }, [questions])

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

            // Apply impact colors relative to actual outcome.
            await applyOutcomeAwareImpactColors(filteredNodes, questionId, outcomeNodeId)

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

            // Build chart events AFTER impact coloring so marker colors match graph semantics.
            const relatedEvents = buildChartEvents(filteredNodes, seedEventIds)
            setQuestionRelatedEvents(relatedEvents)
            console.log(`Stored ${relatedEvents.length} events for TimeSeriesChart`)

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

            // Apply impact colors relative to actual outcome (fallback path).
            await applyOutcomeAwareImpactColors(filteredNodes, questionId, outcomeNodeId)

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

            // Keep chart events in sync in fallback mode as well.
            const fallbackSeedIds = new Set(seedEventIds)
            const relatedEvents = buildChartEvents(filteredNodes, fallbackSeedIds)
            setQuestionRelatedEvents(relatedEvents)

            setTimeFilter(null)
        }
    }, [fullGraphData, questions, setGraphData, setSelectedQuestionId, setQuestionRelatedEvents, setPriceHistoryData, setTimeFilter, setPriceHistoryInterval, buildChartEvents, applyOutcomeAwareImpactColors])

    return {
        handleShowNeighborhood,
        handleQuestionFilter
    }
}
