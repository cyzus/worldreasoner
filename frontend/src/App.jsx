import React, { useState, useEffect, useCallback, useRef, useMemo, lazy, Suspense } from 'react'
import GraphVisualization from './components/GraphVisualization'
import ControlPanel from './components/ControlPanel'
import EventDetails from './components/EventDetails'
import QuestionList from './components/QuestionList'
import DatabaseDropdown from './components/DatabaseDropdown'
import SearchIndexStatus from './components/SearchIndexStatus'
import Timeline from './components/Timeline'
import TimeSeriesChart from './components/TimeSeriesChart'

// Lazy load heavy page components for code splitting
const PipelinePage = lazy(() => import('./components/PipelinePage'))
const QuestionCollectionPage = lazy(() => import('./components/QuestionCollectionPage'))
const ForecastPage = lazy(() => import('./components/ForecastPage'))
const EventGraphsPage = lazy(() => import('./components/EventGraphsPage'))
import { fetchGraph, fetchStatistics, fetchQuestions, fetchQuestionEvents, fetchQuestionPriceHistory } from './api/graphApi'
import { useGraphStore } from './stores/graphStore'
import { useQuestionStore } from './stores/questionStore'
import { useUIStore } from './stores/uiStore'
import './App.css'

function App() {
  // Graph store
  const fullGraphData = useGraphStore(state => state.fullGraphData)
  const setFullGraphData = useGraphStore(state => state.setFullGraphData)
  const graphData = useGraphStore(state => state.graphData)
  const setGraphData = useGraphStore(state => state.setGraphData)
  const selectedNode = useGraphStore(state => state.selectedNode)
  const setSelectedNode = useGraphStore(state => state.setSelectedNode)
  const loading = useGraphStore(state => state.loading)
  const setLoading = useGraphStore(state => state.setLoading)
  const error = useGraphStore(state => state.error)
  const setError = useGraphStore(state => state.setError)
  const filters = useGraphStore(state => state.filters)
  const setFilters = useGraphStore(state => state.setFilters)
  const timeFilter = useGraphStore(state => state.timeFilter)
  const setTimeFilter = useGraphStore(state => state.setTimeFilter)

  // Question store
  const selectedQuestionId = useQuestionStore(state => state.selectedQuestionId)
  const setSelectedQuestionId = useQuestionStore(state => state.setSelectedQuestion)
  const priceHistoryData = useQuestionStore(state => state.priceHistoryData)
  const setPriceHistoryData = useQuestionStore(state => state.setPriceHistoryData)
  const loadingPriceHistory = useQuestionStore(state => state.loadingPriceHistory)
  const setLoadingPriceHistory = useQuestionStore(state => state.setLoadingPriceHistory)
  const questionRelatedEvents = useQuestionStore(state => state.questionRelatedEvents)
  const setQuestionRelatedEvents = useQuestionStore(state => state.setQuestionRelatedEvents)
  const priceHistoryInterval = useQuestionStore(state => state.priceHistoryInterval)
  const setPriceHistoryInterval = useQuestionStore(state => state.setPriceHistoryInterval)
  const previewQuestions = useQuestionStore(state => state.previewQuestions)
  const setPreviewQuestions = useQuestionStore(state => state.setPreviewQuestions)
  const previewSourceTab = useQuestionStore(state => state.previewSourceTab)
  const setPreviewSourceTab = useQuestionStore(state => state.setPreviewSourceTab)
  const previewSource = useQuestionStore(state => state.previewSource)
  const setPreviewSource = useQuestionStore(state => state.setPreviewSource)

  // UI store
  const leftPanelTab = useUIStore(state => state.leftPanelTab)
  const setLeftPanelTab = useUIStore(state => state.setLeftPanelTab)
  const currentDatabasePath = useUIStore(state => state.currentDatabasePath)
  const setCurrentDatabasePath = useUIStore(state => state.setCurrentDatabasePath)

  // Local state (not in stores)
  const [statistics, setStatistics] = useState(null)
  const [questions, setQuestions] = useState([])

  // Load full graph data once
  const loadGraph = useCallback(async (queryParams = {}) => {
    console.log('Loading graph with params:', queryParams)
    setLoading(true)
    setError(null)

    try {
      const data = await fetchGraph(queryParams)
      console.log('Received graph data:', data)

      // Convert to react-force-graph format
      const graphFormatted = {
        nodes: data.nodes.map(node => ({
          id: node.id,
          name: node.label,
          type: node.node_type,
          size: node.size,
          color: node.color,
          properties: node.properties,
        })),
        links: data.edges.map(edge => ({
          source: edge.source_id,
          target: edge.target_id,
          type: edge.edge_type,
          weight: edge.weight,
          label: edge.label,
          properties: edge.properties,
        })),
      }

      console.log('Formatted graph data:', graphFormatted)

      // Ensure no synthetic links in the full dataset
      const cleanLinks = graphFormatted.links.filter(link =>
        !link.isSynthetic && link.type !== 'potentially_relevant'
      )
      const cleanNodes = graphFormatted.nodes.map(node => ({
        ...node,
        isOutcome: false
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
  }, [])

  // Client-side temporal filtering
  const applyTimeFilter = useCallback((startDate, endDate) => {
    console.log('[TimeFilter] Called with:', { 
      start: startDate?.toISOString(), 
      end: endDate?.toISOString(),
      totalNodes: fullGraphData.nodes.length,
      selectedQuestion: selectedQuestionId 
    })

    if (!startDate || !endDate) {
      // No time filter - if question is selected, re-apply question filter, otherwise show all
      if (selectedQuestionId) {
        console.log('[TimeFilter] Clearing time filter but keeping question filter')
        // Re-trigger question filter by calling handleQuestionFilter
        // This will be handled by the parent - we just clear the time filter state
        setTimeFilter(null)
        return
      }
      
      // No filters at all - show all data and clear outcome markers
      const resetNodes = fullGraphData.nodes
      resetNodes.forEach(node => {
        node.isOutcome = false
      })

      // Filter out synthetic links
      const resetLinks = fullGraphData.links
        .filter(link => !link.isSynthetic && link.type !== 'potentially_relevant')

      console.log('[TimeFilter] Resetting to full data:', resetNodes.length, 'nodes')
      setGraphData({
        nodes: resetNodes,
        links: resetLinks
      })
      setTimeFilter(null)
      setSelectedQuestionId(null)
      return
    }

    setTimeFilter({ start: startDate, end: endDate })

    // IMPORTANT: Time filter should NOT clear question filter
    // Instead, it should apply on top of current graphData (which may already be question-filtered)
    // Use current graphData as the base, not fullGraphData
    const baseData = graphData.nodes.length > 0 ? graphData : fullGraphData
    
    // Filter nodes by date
    const filteredNodes = baseData.nodes
      .filter(node => {
        const eventDate = node.properties?.occurred_date || node.properties?.predicted_date
        if (!eventDate) return false

        const date = new Date(eventDate)
        return date >= startDate && date <= endDate
      })

    console.log('[TimeFilter] Filtered to', filteredNodes.length, 'nodes (from', baseData.nodes.length, 'base nodes)')

    const nodeIds = new Set(filteredNodes.map(n => n.id))

    // Filter links to only include those between visible nodes
    const filteredLinks = baseData.links
      .filter(link => {
        const sourceId = typeof link.source === 'object' ? link.source.id : link.source
        const targetId = typeof link.target === 'object' ? link.target.id : link.target
        return nodeIds.has(sourceId) && nodeIds.has(targetId)
      })

    // Update with new filtered data
    setGraphData({
      nodes: filteredNodes,
      links: filteredLinks,
    })

    // DO NOT clear question filter - time filter works on top of question filter
  }, [fullGraphData, graphData, selectedQuestionId])

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
      console.log('Loaded questions:', questionsData.length)
    } catch (err) {
      console.error('Failed to load questions:', err)
    }
  }, [])

  // Initial load
  useEffect(() => {
    console.log('Initial load with filters:', filters)
    loadGraph(filters)
    loadStatistics()
    loadQuestions()
  }, [loadGraph, loadStatistics, loadQuestions])

  // Handle filter changes
  const handleFilterChange = useCallback((newFilters) => {
    setFilters(newFilters)
    loadGraph(newFilters)
  }, [loadGraph])

  // Handle database change
  const handleDatabaseChange = useCallback(async (dbPath) => {
    console.log('Database changed to:', dbPath)
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
  }, [filters, loadGraph, loadStatistics, loadQuestions])

  // Handle node selection
  const handleNodeClick = useCallback((node) => {
    setSelectedNode(node)
  }, [])

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

    setGraphData({
      nodes: neighborhoodNodes,
      links: neighborhoodLinks,
    })

    // Clear time filter and question filter when showing neighborhood
    setTimeFilter(null)
    setSelectedQuestionId(null)
  }, [fullGraphData])

  // Handle time range change from timeline (client-side filtering)
  const handleTimeRangeChange = useCallback((startDate, endDate) => {
    applyTimeFilter(startDate, endDate)
  }, [applyTimeFilter])

  // Fetch price history for selected question with given interval
  const fetchPriceHistory = useCallback(async (questionId, interval) => {
    const question = questions.find(q => q.id === questionId)
    if (!question || question.source !== 'polymarket') {
      setPriceHistoryData(null)
      return
    }

    console.log(`Fetching price history for question ${questionId} with interval ${interval}`)
    setLoadingPriceHistory(true)

    try {
      const priceData = await fetchQuestionPriceHistory(questionId, interval)
      console.log('✓ Loaded price history:', priceData)
      setPriceHistoryData(priceData)
    } catch (error) {
      console.warn('✗ Failed to load price history:', error.message || error)
      setPriceHistoryData(null)
    } finally {
      setLoadingPriceHistory(false)
    }
  }, [questions])

  // Refetch price history when interval changes
  useEffect(() => {
    if (selectedQuestionId) {
      fetchPriceHistory(selectedQuestionId, priceHistoryInterval)
    }
  }, [priceHistoryInterval, selectedQuestionId, fetchPriceHistory])

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
        .map(link => ({...link}))

      console.log(`Resetting graph: ${resetNodes.length} nodes, ${resetLinks.length} links (filtered from ${fullGraphData.links.length})`)

      setGraphData({
        nodes: resetNodes,
        links: resetLinks
      })
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

    // Price history will be fetched automatically by useEffect when selectedQuestionId changes

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
      console.log(`Causal hypotheses: ${questionEventsData.hypotheses_count}`)
      console.log('Seed event IDs:', Array.from(seedEventIds).slice(0, 5), '...')

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

      // Filter nodes to include the neighborhood
      const filteredNodes = fullGraphData.nodes.filter(node => visited.has(node.id))

      // Filter links to only include those between visible nodes
      const filteredLinks = fullGraphData.links.filter(link => {
        const sourceId = typeof link.source === 'object' ? link.source.id : link.source
        const targetId = typeof link.target === 'object' ? link.target.id : link.target
        return visited.has(sourceId) && visited.has(targetId)
      })

      // Mark the outcome node (target_event_id)
      const outcomeNodeId = question.target_event_id
      if (outcomeNodeId) {
        filteredNodes.forEach(node => {
          if (node.id === outcomeNodeId) {
            node.isOutcome = true
          } else {
            node.isOutcome = false
          }
        })
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
            console.log(`Creating synthetic edge from orphaned node ${node.id} to outcome ${outcomeNodeId}`)
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

      console.log(`Final result: ${filteredNodes.length} nodes, ${filteredLinks.length} real links, ${syntheticLinks.length} synthetic links`)

      // Update with new filtered data including synthetic links
      const combinedLinks = [...filteredLinks, ...syntheticLinks]
      console.log('Setting graph data with links:', combinedLinks.length, 'total (', filteredLinks.length, 'real +', syntheticLinks.length, 'synthetic)')

      setGraphData({
        nodes: filteredNodes,
        links: combinedLinks,
      })

      // Time filter will be preserved and applied on top if active
    } catch (error) {
      console.error('Failed to fetch question events:', error)
      // Fallback to old behavior using only related_event_ids
      const seedEventIds = new Set()
      if (question.target_event_id) {
        seedEventIds.add(question.target_event_id)
      }
      question.related_event_ids.forEach(id => seedEventIds.add(id))

      const filteredNodes = fullGraphData.nodes.filter(node => seedEventIds.has(node.id))

      // Mark outcome node
      const outcomeNodeId = question.target_event_id
      if (outcomeNodeId) {
        filteredNodes.forEach(node => {
          node.isOutcome = node.id === outcomeNodeId
        })
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

      setGraphData({ nodes: filteredNodes, links: [...filteredLinks, ...syntheticLinks] })
      setTimeFilter(null)
    }
  }, [fullGraphData, questions])

  // Handle pipeline job completion
  const handleJobComplete = useCallback((results) => {
    console.log('Pipeline job completed:', results)
    // Refresh graph data after pipeline completion
    loadGraph(filters)
    loadStatistics()
  }, [filters, loadGraph, loadStatistics])

  // Handle questions added from collection page
  const handleQuestionsAdded = useCallback((count) => {
    console.log(`${count} questions added, refreshing...`)
    loadQuestions() // Reload questions list
  }, [loadQuestions])

  // Handle question updated
  const handleQuestionUpdated = useCallback((updatedQuestion) => {
    console.log('Question updated:', updatedQuestion.id)
    // Update questions list in state
    setQuestions(prevQuestions =>
      prevQuestions.map(q => q.id === updatedQuestion.id ? updatedQuestion : q)
    )
  }, [])

  // Handle question deleted
  const handleQuestionDeleted = useCallback((questionId) => {
    console.log('Question deleted:', questionId)
    // Remove question from list
    setQuestions(prevQuestions => prevQuestions.filter(q => q.id !== questionId))
    // Clear selection if deleted question was selected
    if (selectedQuestionId === questionId) {
      setSelectedQuestionId(null)
      handleQuestionFilter(null)
    }
  }, [selectedQuestionId, handleQuestionFilter])

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
          <h1>WorldReasoner</h1>
          <div className="header-info-bar">
            <DatabaseDropdown onDatabaseChange={handleDatabaseChange} />
            {statistics && (
              <>
                <div className="header-divider"></div>
                <div className="stats-bar">
                  <span>{statistics.total_nodes} events</span>
                  <span>{statistics.total_edges} causal links</span>
                  <span>Avg degree: {statistics.average_out_degree?.toFixed(2)}</span>
                </div>
              </>
            )}
          </div>
        </div>
        <div className="header-right">
        </div>
      </header>

      {/* Search Index Status Banner */}
      <SearchIndexStatus
        databasePath={currentDatabasePath}
        visible={true}
      />

      <div className="app-content">
        {/* Top navigation tabs */}
        <div className="top-tabs">
          <button
            className={`top-tab-btn ${leftPanelTab === 'eventgraphs' ? 'active' : ''}`}
            onClick={() => setLeftPanelTab('eventgraphs')}
          >
            📊 Event Graphs
          </button>
          <button
            className={`top-tab-btn ${leftPanelTab === 'collection' ? 'active' : ''}`}
            onClick={() => setLeftPanelTab('collection')}
          >
            🔍 Collection
          </button>
          <button
            className={`top-tab-btn ${leftPanelTab === 'pipelines' ? 'active' : ''}`}
            onClick={() => setLeftPanelTab('pipelines')}
          >
            🔬 Evidence
          </button>

          <button
            className={`top-tab-btn ${leftPanelTab === 'forecast' ? 'active' : ''}`}
            onClick={() => setLeftPanelTab('forecast')}
          >
            🎯 Forecast
          </button>
        </div>

        <Suspense fallback={<div className="loading-fallback">Loading...</div>}>
          {leftPanelTab === 'eventgraphs' ? (
            /* Event Graphs page with nested tabs */
            <EventGraphsPage
              fullGraphData={fullGraphData}
              graphData={graphData}
              selectedNode={selectedNode}
              onNodeClick={handleNodeClick}
              loading={loading}
              error={error}
              filters={filters}
              onFilterChange={handleFilterChange}
              onRefresh={() => loadGraph(filters)}
              questions={questions}
              selectedQuestionId={selectedQuestionId}
              onQuestionFilter={(questionId) => {
                setSelectedQuestionId(questionId)
                handleQuestionFilter(questionId)
              }}
              onShowNeighborhood={handleShowNeighborhood}
              onTimeRangeChange={handleTimeRangeChange}
              priceHistoryData={priceHistoryData}
              loadingPriceHistory={loadingPriceHistory}
              questionRelatedEvents={questionRelatedEvents}
              priceHistoryInterval={priceHistoryInterval}
              setPriceHistoryInterval={setPriceHistoryInterval}
              onQuestionUpdated={handleQuestionUpdated}
              onQuestionDeleted={handleQuestionDeleted}
            />
          ) : leftPanelTab === 'collection' ? (
            /* Full-width collection page */
            <QuestionCollectionPage
              onQuestionsAdded={handleQuestionsAdded}
              previewQuestions={previewQuestions}
              setPreviewQuestions={setPreviewQuestions}
              sourceTab={previewSourceTab}
              setSourceTab={setPreviewSourceTab}
              previewSource={previewSource}
              setPreviewSource={setPreviewSource}
            />
          ) : leftPanelTab === 'forecast' ? (
            /* Full-width forecast page */
            <ForecastPage />
          ) : leftPanelTab === 'pipelines' ? (
            /* Full-width pipeline page */
            <PipelinePage
              questions={questions}
              onJobComplete={handleJobComplete}
            />
          ) : null}
        </Suspense>
      </div>
    </div>
  )
}

export default App
