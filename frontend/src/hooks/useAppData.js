import { useState, useEffect, useCallback } from 'react'
import { useGraphStore } from '../stores/graphStore'
import { useQuestionStore } from '../stores/questionStore'
import { useUIStore } from '../stores/uiStore'
import { fetchGraph, fetchStatistics, fetchQuestions, fetchQuestionPriceHistory } from '../api/graphApi'

/**
 * Hook to handle initial data loading, refreshing, and global app state
 */
export const useAppData = () => {
    // Graph store
    const setFullGraphData = useGraphStore(state => state.setFullGraphData)
    const setGraphData = useGraphStore(state => state.setGraphData)
    const setLoading = useGraphStore(state => state.setLoading)
    const setError = useGraphStore(state => state.setError)
    const filters = useGraphStore(state => state.filters)
    const setFilters = useGraphStore(state => state.setFilters)
    const includeOutcomes = useGraphStore(state => state.includeOutcomes)

    // Question store
    const setSelectedNode = useGraphStore(state => state.setSelectedNode)
    const setSelectedQuestionId = useQuestionStore(state => state.setSelectedQuestion)
    const setPriceHistoryData = useQuestionStore(state => state.setPriceHistoryData)
    const setLoadingPriceHistory = useQuestionStore(state => state.setLoadingPriceHistory)
    const setQuestionRelatedEvents = useQuestionStore(state => state.setQuestionRelatedEvents)
    const setPreviewQuestions = useQuestionStore(state => state.setPreviewQuestions)
    const setPreviewSourceTab = useQuestionStore(state => state.setPreviewSourceTab)
    const setCurrentDatabasePath = useUIStore(state => state.setCurrentDatabasePath)
    const setPreviewSource = useQuestionStore(state => state.setPreviewSource)
    const selectedQuestionId = useQuestionStore(state => state.selectedQuestionId)
    const priceHistoryInterval = useQuestionStore(state => state.priceHistoryInterval)

    // Local state for statistics and questions
    const [statistics, setStatistics] = useState(null)
    const [questions, setQuestions] = useState([])

    // Load full graph data
    const loadGraph = useCallback(async (queryParams = {}) => {
        setLoading(true)
        setError(null)

        try {
            // Include outcomes parameter in the request
            const params = {
                ...queryParams,
                includeOutcomes: includeOutcomes
            }
            const data = await fetchGraph(params)

            // Convert to react-force-graph format
            const graphFormatted = {
                nodes: data.nodes.map(node => ({
                    id: node.id,
                    name: node.label,
                    type: node.node_type,
                    domain: node.properties?.domain || node.domain || 'general',
                    size: node.size,
                    color: node.color,
                    properties: node.properties,
                })),
                links: data.edges.map(edge => ({
                    source: edge.source_id,
                    target: edge.target_id,
                    type: edge.edge_type,
                    edge_type: edge.edge_type, // Also set edge_type for impact edge detection
                    weight: edge.weight,
                    label: edge.label,
                    properties: edge.properties,
                })),
            }


            // Ensure no synthetic links in the full dataset
            const cleanLinks = graphFormatted.links.filter(link =>
                !link.isSynthetic && link.type !== 'potentially_relevant'
            )
            const cleanNodes = graphFormatted.nodes.map(node => ({
                ...node,
                isOutcome: node.properties?.is_outcome || false
            }))

            const cleanGraphData = {
                nodes: cleanNodes,
                links: cleanLinks
            }


            setFullGraphData(cleanGraphData)
            setGraphData(cleanGraphData) // Initially show all

        } catch (err) {
            setError(`Failed to load graph: ${err.message}`)
            console.error('Graph load error:', err)
        } finally {
            setLoading(false)
        }
    }, [setFullGraphData, setGraphData, setLoading, setError, includeOutcomes])

    // Load statistics
    const loadStatistics = useCallback(async () => {
        try {
            const stats = await fetchStatistics()
            setStatistics(stats)
        } catch (err) {
            console.error('Failed to load statistics:', err)
        }
    }, [])

    // Load questions
    const loadQuestions = useCallback(async () => {
        try {
            const questionsData = await fetchQuestions()
            setQuestions(questionsData)
        } catch (err) {
            console.error('Failed to load questions:', err)
        }
    }, [])

    // Initial load
    useEffect(() => {
        loadGraph(filters)
        loadStatistics()
        loadQuestions()
    }, [loadGraph, loadStatistics, loadQuestions]) // filters is included in loadGraph dependency via closure? No, explicitly passed.
    // Wait, loadGraph depends on nothing but setters. logic above uses `queryParams` arg.
    // Setup useEffect correctly.

    // Handle filter changes
    const handleFilterChange = useCallback((newFilters) => {
        setFilters(newFilters)
        loadGraph(newFilters)
    }, [loadGraph, setFilters])

    // Handle database change
    const handleDatabaseChange = useCallback(async (dbPath) => {
        // Reload all data from the new database
        setLoading(true)
        setError(null)
        setSelectedNode(null)
        setSelectedQuestionId(null)
        setPriceHistoryData(null)
        setQuestionRelatedEvents([])
        setPreviewQuestions([]) // Clear preview questions when switching database
        setPreviewSourceTab('polymarket')
        setCurrentDatabasePath(dbPath) // Update database path for search index status
        setPreviewSource(null)

        try {
            // Reload graph, statistics, and questions
            await Promise.all([
                loadGraph(filters),
                loadStatistics(),
                loadQuestions()
            ])
        } catch (err) {
            setError('Failed to load data from new database: ' + err.message)
        }
    }, [filters, loadGraph, loadStatistics, loadQuestions, setLoading, setError, setSelectedNode, setSelectedQuestionId, setPriceHistoryData, setQuestionRelatedEvents, setPreviewQuestions, setPreviewSourceTab, setCurrentDatabasePath, setPreviewSource])

    // Handle pipeline job completion
    const handleJobComplete = useCallback((results) => {
        // Refresh graph data after pipeline completion
        loadGraph(filters)
        loadStatistics()
    }, [filters, loadGraph, loadStatistics])

    // Handle questions added from collection page
    const handleQuestionsAdded = useCallback((count) => {
        loadQuestions() // Reload questions list
    }, [loadQuestions])

    // Handle question updated
    const handleQuestionUpdated = useCallback((updatedQuestion) => {
        // Update questions list in state
        setQuestions(prevQuestions =>
            prevQuestions.map(q => q.id === updatedQuestion.id ? { ...q, ...updatedQuestion } : q)
        )
    }, [])

    // Fetch price history for selected question with given interval
    const fetchPriceHistory = useCallback(async (questionId, interval) => {
        const question = questions.find(q => q.id === questionId)
        if (!question || question.source !== 'polymarket') {
            setPriceHistoryData(null)
            return
        }

        setLoadingPriceHistory(true)

        try {
            // Fetch with turning points for full history view
            const includeTurningPoints = interval === 'max'
            const priceData = await fetchQuestionPriceHistory(
                questionId,
                interval,
                includeTurningPoints,
                5.0  // min change for turning points (5 percentage points)
            )
            if (includeTurningPoints && priceData.turning_points) {
            }
            setPriceHistoryData(priceData)
        } catch (error) {
            console.warn('✗ Failed to load price history:', error.message || error)
            setPriceHistoryData(null)
        } finally {
            setLoadingPriceHistory(false)
        }
    }, [questions, setPriceHistoryData, setLoadingPriceHistory])

    // Refetch price history when interval changes
    useEffect(() => {
        if (selectedQuestionId) {
            fetchPriceHistory(selectedQuestionId, priceHistoryInterval)
        }
    }, [priceHistoryInterval, selectedQuestionId, fetchPriceHistory])

    // Helper to remove question from local state
    const removeQuestion = useCallback((questionId) => {
        setQuestions(prevQuestions => prevQuestions.filter(q => q.id !== questionId))
    }, [])

    return {
        questions,
        statistics,
        loadGraph,
        handleFilterChange,
        handleDatabaseChange,
        handleJobComplete,
        handleQuestionsAdded,
        handleQuestionUpdated,
        removeQuestion
    }
}
