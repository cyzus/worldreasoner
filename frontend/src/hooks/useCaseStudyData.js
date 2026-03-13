import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import { fetchOutcomeImpacts } from '../api/graphApi'
import { useQuestionArticles } from './queries/useQuestionQueries'

/**
 * useCaseStudyData - Encapsulates data fetching, merging, and memoization for CaseStudyView.
 * Uses React Query to standardize caching and fetching.
 */
export function useCaseStudyData(selectedQuestion, graphData) {
    // 1. Fetch Question Articles using React Query
    const {
        data: fetchedArticles = [],
        isLoading: loadingArticles
    } = useQuestionArticles(selectedQuestion?.id)

    // 2. Identify Outcome Nodes
    const outcomeNodes = useMemo(() => {
        return (graphData?.nodes || []).filter(n => {
            const props = n.properties || {}
            const isOutcome = n.isOutcome || props.is_outcome || props.is_actual_outcome
            const qId = n.question_id || props.extracted_for_question_id
            return isOutcome && qId === selectedQuestion?.id
        })
    }, [graphData?.nodes, selectedQuestion?.id])

    // 3. Fetch all Outcome Impacts simultaneously using useQueries array
    const impactQueries = useQueries({
        queries: outcomeNodes.map(node => ({
            queryKey: ['outcomeImpacts', node.id],
            queryFn: () => fetchOutcomeImpacts(node.id).then(data => ({
                id: node.id,
                title: node.title || node.name || node.properties?.title,
                data
            })),
            enabled: !!node.id,
            staleTime: 5 * 60 * 1000
        }))
    })

    const loadingImpacts = impactQueries.some(q => q.isLoading)

    // 4. Process the Impacts into `bySource` dictionary
    const impacts = useMemo(() => {
        const bySource = {}

        impactQueries.forEach(query => {
            if (!query.data) return

            const { id: outcomeId, title: outcomeTitle, data } = query.data
            const outcomeNode = outcomeNodes.find(n => n.id === outcomeId)
            const outcomeScenario = outcomeNode?.properties?.outcome_scenario || ''

            data.forEach(imp => {
                const sourceId = imp.source_id || imp.event_id
                if (!bySource[sourceId]) bySource[sourceId] = []

                bySource[sourceId].push({
                    outcomeId,
                    outcomeTitle,
                    outcomeScenario,
                    outcomeIsActual: Boolean(
                        outcomeNode?.is_actual_outcome ||
                        outcomeNode?.properties?.is_actual_outcome
                    ),
                    impact_direction: imp.impact_direction || imp.properties?.impact_direction,
                    impact_magnitude: imp.impact_magnitude ?? imp.properties?.impact_magnitude ?? imp.weight ?? 0,
                    confidence: imp.confidence ?? imp.properties?.confidence ?? 1.0,
                    reasoning: imp.reasoning || imp.properties?.reasoning,
                    articleIds: imp.evidence_article_ids || imp.properties?.evidence_article_ids || []
                })
            })
        })

        return bySource
    }, [impactQueries, outcomeNodes])

    // Create article lookup map for evidence links
    const articleMap = useMemo(() => {
        const map = {}
        fetchedArticles.forEach(a => { map[a.id] = a })
            ; (graphData?.nodes || []).forEach(n => {
                const isArticle = n.node_type === 'article' || n.properties?.type === 'article' || n.properties?.type === 'Article'
                if (isArticle && !map[n.id]) {
                    map[n.id] = {
                        id: n.id,
                        title: n.title || n.name || n.properties?.title || 'Unknown Article',
                        source: n.source || n.properties?.source || 'Original Source',
                        published_date: n.date || n.properties?.date || n.properties?.published_date,
                        url: n.url || n.properties?.url
                    }
                }
            })
        return map
    }, [fetchedArticles, graphData?.nodes])

    // Process Articles (Information Stream)
    const articles = useMemo(() => {
        const processedFetched = fetchedArticles.map(a => ({
            ...a,
            id: a.id,
            date: a.published_date,
            title: a.title,
            source: a.source,
            summary: a.content
        }))

        const graphArticles = (graphData?.nodes || [])
            .filter(n => {
                const isArticle = n.node_type === 'article' ||
                    n.type === 'article' ||
                    n.node_type === 'Article' ||
                    (n.properties && (n.properties.type === 'article' || n.properties.type === 'Article'))
                const qId = n.question_id || n.properties?.extracted_for_question_id || n.properties?.collected_for_question_id
                return isArticle && qId === selectedQuestion?.id
            })
            .map(n => ({
                id: n.id,
                date: n.date || n.properties?.date || n.properties?.published_date,
                title: n.title || n.name || n.label || n.properties?.title,
                source: n.source || n.properties?.source,
                summary: n.summary || n.properties?.summary || n.properties?.description
            }))

        const combined = [...processedFetched]
        const seenIds = new Set(processedFetched.map(a => a.id))

        graphArticles.forEach(a => {
            if (!seenIds.has(a.id)) {
                combined.push(a)
                seenIds.add(a.id)
            }
        })

        return combined.sort((a, b) => new Date(a.date || 0) - new Date(b.date || 0))
    }, [fetchedArticles, graphData, selectedQuestion?.id])

    // Process Events (Causal Events)
    const events = useMemo(() => {
        if (!graphData?.nodes) return []

        const eventNodes = graphData.nodes.filter(n => {
            const isEvent = n.node_type === 'event' ||
                n.type === 'event' ||
                n.node_type === 'Event' ||
                (n.properties && (n.properties.type === 'event' || n.properties.type === 'Event')) ||
                n.isOutcome ||
                (n.properties && n.properties.is_outcome) ||
                (n.properties && n.properties.is_actual_outcome)

            const qId = n.question_id || n.properties?.extracted_for_question_id
            return isEvent && qId === selectedQuestion?.id
        })

        return eventNodes.sort((a, b) => {
            const dateA = new Date(a.occurred_date || a.predicted_date || a.properties?.occurred_date || a.properties?.predicted_date || 0)
            const dateB = new Date(b.occurred_date || b.predicted_date || b.properties?.occurred_date || b.properties?.predicted_date || 0)
            return dateA - dateB
        })
    }, [graphData, selectedQuestion?.id])

    const groundTruthScenario = useMemo(() => {
        const rawTruth = selectedQuestion?.ground_truth
        if (rawTruth == null || rawTruth === '') return null
        const normalized = String(rawTruth).trim().replace(/^"+|"+$/g, '').toLowerCase()
        if (['yes', 'true', '1'].includes(normalized)) return 'positive_resolution'
        if (['no', 'false', '0'].includes(normalized)) return 'negative_resolution'
        return null
    }, [selectedQuestion?.ground_truth])

    return {
        articles,
        events,
        impacts,
        articleMap,
        groundTruthScenario,
        loadingArticles,
        loadingImpacts
    }
}
