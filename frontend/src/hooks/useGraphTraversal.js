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
    const graphData     = useGraphStore(state => state.graphData)
    const setGraphData  = useGraphStore(state => state.setGraphData)
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

            const impactResults = await Promise.all(outcomes.map(async (outcome) => {
                try {
                    const impacts = await fetchOutcomeImpacts(outcome.id);
                    return { outcome, impacts };
                } catch (err) {
                    console.warn(`Failed to fetch impacts for outcome ${outcome.id}:`, err);
                    return { outcome, impacts: [] };
                }
            }));

            for (const { outcome, impacts } of impactResults) {
                const isActualOutcome = actualOutcomeIds.has(outcome.id)
                const outcomeSign = isActualOutcome ? 1 : -1

                impacts.forEach(impact => {
                    const sourceNode = nodeById.get(impact.source_id || impact.event_id) // Support both naming conventions
                    if (!sourceNode) return

                    const direction = impact.impact_direction || impact.properties?.impact_direction
                    const magnitude = Number(impact.impact_magnitude ?? impact.properties?.impact_magnitude ?? impact.weight ?? 0)
                    const confidence = Number(impact.confidence ?? impact.properties?.confidence ?? 1.0)
                    if (!Number.isFinite(confidence) || confidence < MIN_IMPACT_CONFIDENCE) return

                    const confidenceWeight = Math.pow(Math.max(0, Math.min(1, confidence)), CONFIDENCE_EXPONENT)
                    const strength = Math.max(0, magnitude) * confidenceWeight

                    let impactToOutcomeSign = 0
                    if (direction === 'positive') impactToOutcomeSign = 1
                    else if (direction === 'negative') impactToOutcomeSign = -1
                    else if (direction === 'mixed' || direction === 'neutral') impactToOutcomeSign = 0
                    else return

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

        } catch (err) {
            console.warn('Failed to apply outcome-aware impact coloring:', err)
        }
    }, [questions])

    // Handle neighborhood view (client-side filtering)
    const handleShowNeighborhood = useCallback((nodeId, depth = 2) => {
        // Use fullGraphData when populated (global graph view), otherwise
        // fall back to the current graphData (per-question evidence graph).
        const sourceGraph = (fullGraphData?.nodes?.length > 0) ? fullGraphData : graphData

        const centerNode = sourceGraph.nodes.find(n => n.id === nodeId)
        if (!centerNode) return

        // BFS to find neighborhood
        const visited = new Set([nodeId])
        const queue = [{ id: nodeId, depth: 0 }]

        // Only use real links, not synthetic ones
        const realLinks = sourceGraph.links.filter(link => !link.isSynthetic && link.type !== 'potentially_relevant')

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
        const neighborhoodNodes = sourceGraph.nodes
            .filter(n => visited.has(n.id))
            .map(node => ({ ...node, isOutcome: false }))

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
    }, [fullGraphData, graphData, setGraphData, setTimeFilter, setSelectedQuestionId])

    // Handle question filter
    const handleQuestionFilter = useCallback(async (questionId, depth = 2) => {
        if (!questionId) {
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


        try {
            // Fetch all events related to this question (including from metadata and hypotheses)
            const questionEventsData = await fetchQuestionEvents(questionId)
            const seedEventIds = new Set(questionEventsData.event_ids)



            // Debug: Check if seed events exist in fullGraphData
            const missingEventIds = Array.from(seedEventIds).filter(id => !fullGraphData.nodes.find(n => n.id === id))

            // Local copy of graph data that we might augment
            let currentGraphNodes = [...fullGraphData.nodes]
            let currentGraphLinks = [...fullGraphData.links]

            if (missingEventIds.length > 0) {
                console.warn(`⚠️ ${missingEventIds.length} seed events NOT found in fullGraphData. Fetching them...`)
                try {
                    const { fetchGraph } = await import('../api/graphApi')
                    const missingSubgraph = await fetchGraph({
                        nodeIds: Array.from(seedEventIds),
                        includeOutcomes: true,
                        maxNodes: 2000,
                        maxEdges: 5000
                    })

                    // Merge missing nodes into currentGraphNodes
                    const currentNodesMap = new Map(currentGraphNodes.map(n => [n.id, n]))
                    missingSubgraph.nodes.forEach(node => {
                        currentNodesMap.set(node.id, {
                            id: node.id,
                            name: node.label,
                            type: node.node_type,
                            domain: node.properties?.domain || node.domain || 'general',
                            size: node.size,
                            color: node.color,
                            properties: node.properties,
                            isOutcome: node.properties?.is_outcome || false
                        })
                    })
                    currentGraphNodes = Array.from(currentNodesMap.values())

                    // Merge missing links into currentGraphLinks
                    const currentLinksMap = new Map()
                    currentGraphLinks.forEach(l => {
                        const src = typeof l.source === 'object' ? l.source.id : l.source
                        const tgt = typeof l.target === 'object' ? l.target.id : l.target
                        currentLinksMap.set(`${src}-${tgt}-${l.type}`, l)
                    })

                    if (missingSubgraph.edges) {
                        missingSubgraph.edges.forEach(e => {
                            const src = e.source_id
                            const tgt = e.target_id
                            currentLinksMap.set(`${src}-${tgt}-${e.edge_type}`, {
                                source: src,
                                target: tgt,
                                type: e.edge_type,
                                label: e.label,
                                weight: e.weight,
                                properties: e.properties
                            })
                        })
                    }
                    currentGraphLinks = Array.from(currentLinksMap.values())

                } catch (err) {
                    console.error('Failed to fetch missing subgraph for question:', err)
                }
            }

            // BFS to find neighborhood around these events
            const visited = new Set(seedEventIds)
            const queue = Array.from(seedEventIds).map(id => ({ id, depth: 0 }))

            while (queue.length > 0) {
                const { id: currentId, depth: currentDepth } = queue.shift()

                if (currentDepth >= depth) continue

                // Find connected nodes (both incoming and outgoing)
                currentGraphLinks.forEach(link => {
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


            // Filter nodes to include the neighborhood
            const filteredNodes = currentGraphNodes.filter(node => visited.has(node.id))

            // Filter links to only include those between visible nodes
            const filteredLinks = currentGraphLinks.filter(link => {
                const sourceId = typeof link.source === 'object' ? link.source.id : link.source
                const targetId = typeof link.target === 'object' ? link.target.id : link.target
                return visited.has(sourceId) && visited.has(targetId)
            })


            // Mark outcome nodes from backend is_outcome / is_actual_outcome properties
            const outcomeNodeId = filteredNodes.find(n => n.properties?.is_actual_outcome)?.id
            filteredNodes.forEach(node => {
                node.isOutcome = node.properties?.is_outcome || false
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


            // Verify Santa node has impact before setting graph data
            const santaNode = filteredNodes.find(n => (n.name || '').includes('Santa'))
            if (santaNode) {
            }

            const questionFilteredData = {
                nodes: filteredNodes,
                links: combinedLinks,
            }
            setGraphData(questionFilteredData)

            // Build chart events AFTER impact coloring so marker colors match graph semantics.
            const relatedEvents = buildChartEvents(filteredNodes, seedEventIds)
            setQuestionRelatedEvents(relatedEvents)

        } catch (error) {
            console.error('Failed to fetch question events:', error)
            // Fallback to old behavior using only related_event_ids
            const seedEventIds = new Set()
            if (question.outcome_event_ids) {
                question.outcome_event_ids.forEach(id => seedEventIds.add(id))
            }
            if (question.target_event_id) {
                seedEventIds.add(question.target_event_id)
            }
            if (question.related_event_ids) {
                question.related_event_ids.forEach(id => seedEventIds.add(id))
            }

            const filteredNodes = fullGraphData.nodes.filter(node => seedEventIds.has(node.id))

            // Mark outcome nodes from backend is_outcome / is_actual_outcome properties
            const outcomeNodeId = filteredNodes.find(n => n.properties?.is_actual_outcome)?.id
            filteredNodes.forEach(node => {
                node.isOutcome = node.properties?.is_outcome || false
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
