import axios from 'axios'

const API_BASE_URL = '/api'

/**
 * Fetch graph data with optional filters
 */
export async function fetchGraph(params = {}) {
  const queryParams = new URLSearchParams()

  if (params.nodeTypes !== undefined) {
    queryParams.append('node_types', params.nodeTypes.join(','))
  }
  if (params.nodeIds && params.nodeIds.length > 0) {
    queryParams.append('node_ids', params.nodeIds.join(','))
  }
  if (params.center_node_id) {
    queryParams.append('center_node_id', params.center_node_id)
  }
  if (params.max_depth) {
    queryParams.append('max_depth', params.max_depth)
  }
  if (params.maxNodes) {
    queryParams.append('max_nodes', params.maxNodes)
  }
  if (params.maxEdges) {
    queryParams.append('max_edges', params.maxEdges)
  }
  if (params.minEdgeWeight) {
    queryParams.append('min_edge_weight', params.minEdgeWeight)
  }
  if (params.start_date) {
    queryParams.append('start_date', params.start_date)
  }
  if (params.end_date) {
    queryParams.append('end_date', params.end_date)
  }
  if (params.includeOutcomes !== undefined) {
    queryParams.append('include_outcomes', params.includeOutcomes)
  }
  if (params.outcomeQuestionId) {
    queryParams.append('outcome_question_id', params.outcomeQuestionId)
  }

  const response = await axios.get(
    `${API_BASE_URL}/graph/?${queryParams.toString()}`
  )
  return response.data
}

/**
 * Fetch single node details
 */
export async function fetchNode(nodeId) {
  const response = await axios.get(`${API_BASE_URL}/graph/node/${nodeId}`)
  return response.data
}

/**
 * Fetch neighborhood around a node
 */
export async function fetchNeighborhood(nodeId, maxDepth = 1, direction = 'both') {
  const response = await axios.get(
    `${API_BASE_URL}/graph/neighborhood/${nodeId}?max_depth=${maxDepth}&direction=${direction}`
  )
  return response.data
}

/**
 * Find paths between two nodes
 */
export async function fetchPaths(sourceId, targetId, maxDepth = 5) {
  const response = await axios.get(
    `${API_BASE_URL}/graph/paths/${sourceId}/${targetId}?max_depth=${maxDepth}`
  )
  return response.data
}

/**
 * Fetch graph statistics
 */
export async function fetchStatistics() {
  const response = await axios.get(`${API_BASE_URL}/graph/statistics`)
  return response.data
}

/**
 * Fetch event details
 */
export async function fetchEvent(eventId) {
  const response = await axios.get(`${API_BASE_URL}/events/${eventId}`)
  return response.data
}

/**
 * Fetch all questions
 */
export async function fetchQuestions(domain = null) {
  const params = domain ? { domain } : {}
  const response = await axios.get(`${API_BASE_URL}/questions/`, { params })
  return response.data
}

/**
 * Fetch single question details
 */
export async function fetchQuestion(questionId) {
  const response = await axios.get(`${API_BASE_URL}/questions/${questionId}`)
  return response.data
}

/**
 * Fetch all events related to a question (including from causal hypotheses)
 */
export async function fetchQuestionEvents(questionId) {
  const response = await axios.get(`${API_BASE_URL}/questions/${questionId}/events`)
  return response.data
}

/**
 * Fetch all articles related to an event
 */
export async function fetchEventArticles(eventId) {
  const response = await axios.get(`${API_BASE_URL}/events/${eventId}/articles`)
  return response.data
}

/**
 * Fetch all questions related to an event
 */
export async function fetchEventQuestions(eventId) {
  const response = await axios.get(`${API_BASE_URL}/events/${eventId}/questions`)
  return response.data
}

/**
 * Fetch price history for a Polymarket question
 * @param {string} questionId - Question ID
 * @param {string} interval - Time interval (1h, 6h, 1d, 1w, max)
 * @param {boolean} includeTurningPoints - Include turning point analysis
 * @param {number} minTurningPointChange - Minimum change for turning points (percentage points)
 */
export async function fetchQuestionPriceHistory(
  questionId,
  interval = '1d',
  includeTurningPoints = false,
  minTurningPointChange = 5.0
) {
  const params = new URLSearchParams()
  params.append('interval', interval)
  if (includeTurningPoints) {
    params.append('include_turning_points', 'true')
    params.append('min_turning_point_change', minTurningPointChange.toString())
  }
  const response = await axios.get(
    `${API_BASE_URL}/questions/${questionId}/price_history?${params.toString()}`
  )
  return response.data
}

/**
 * Fetch and analyze price turning points for a question
 * @param {string} questionId - Question ID
 * @param {number} minChangePct - Minimum price change for turning points
 * @param {boolean} createEvents - Create Event records from turning points
 */
export async function fetchPriceTurningPoints(
  questionId,
  minChangePct = 5.0,
  createEvents = false
) {
  const params = new URLSearchParams()
  params.append('min_change_pct', minChangePct.toString())
  params.append('create_events', createEvents.toString())
  const response = await axios.get(
    `${API_BASE_URL}/questions/${questionId}/price_turning_points?${params.toString()}`
  )
  return response.data
}

/**
 * Fetch current database information
 */
export async function fetchCurrentDatabase() {
  const response = await axios.get(`${API_BASE_URL}/database/current`)
  return response.data
}

/**
 * Fetch list of available database files
 */
export async function fetchDatabaseList() {
  const response = await axios.get(`${API_BASE_URL}/database/list`)
  return response.data
}

/**
 * Switch to a different database file
 */
export async function switchDatabase(dbPath) {
  const response = await axios.post(`${API_BASE_URL}/database/switch`, {
    db_path: dbPath
  })
  return response.data
}

/**
 * Create a new database file (optionally switching to it)
 */
export async function createDatabase(name, { switchTo = true } = {}) {
  const response = await axios.post(`${API_BASE_URL}/database/create`, {
    name,
    switch: switchTo
  })
  return response.data
}

/**
 * Fetch search index status
 */
export async function fetchSearchIndexStatus() {
  const response = await axios.get(`${API_BASE_URL}/search/status`)
  return response.data
}

/**
 * Build or rebuild search indexes
 */
export async function buildSearchIndex(rebuild = false, embeddingModel = null, batchSize = 2, ftsOnly = true) {
  const response = await axios.post(`${API_BASE_URL}/search/build-index`, {
    rebuild,
    embedding_model: embeddingModel,
    batch_size: batchSize,
    fts_only: ftsOnly
  })
  return response.data
}

/**
 * Clean up orphaned embeddings (embeddings for deleted articles)
 */
export async function cleanupOrphanedEmbeddings() {
  const response = await axios.post(`${API_BASE_URL}/search/cleanup`)
  return response.data
}
/**
 * Fetch forecast evaluation report
 */
export async function fetchEvaluationReport() {
  const response = await axios.get(`${API_BASE_URL}/evaluation/report`)
  return response.data
}

/**
 * Trigger batch evaluation
 */
export async function runEvaluation(updateForecasts = true) {
  const response = await axios.post(`${API_BASE_URL}/evaluation/run`, {
    update_forecasts: updateForecasts
  })
  return response.data
}

/**
 * Fetch forecasts for a question
 */
export async function fetchForecasts(questionId) {
  const response = await axios.get(`${API_BASE_URL}/questions/${questionId}/forecasts`)
  return response.data
}

/**
 * Fetch forecast reasoning graph
 */
export async function fetchForecastGraph(forecastId) {
  const response = await axios.get(`${API_BASE_URL}/forecasts/${forecastId}/graph`)
  return response.data
}

/**
 * Fetch preview questions
 */
export async function fetchPreviewQuestions(config) {
  const response = await axios.post(`${API_BASE_URL}/questions/preview`, config)
  return response.data
}

/**
 * Save batch of questions
 */
export async function saveQuestionsBatch(data) {
  const response = await axios.post(`${API_BASE_URL}/questions/batch-save`, data)
  return response.data
}

/**
 * Start a news collection job
 */
export async function startNewsCollectionJob(payload) {
  const response = await axios.post(`${API_BASE_URL}/pipelines/jobs`, payload)
  return response.data
}

/**
 * Fetch outcome events for a question
 */
export async function fetchOutcomes(questionId) {
  const response = await axios.get(`${API_BASE_URL}/outcomes/questions/${questionId}/outcomes`)
  return response.data
}

/**
 * Fetch outcome impact edges for a specific outcome event
 */
export async function fetchOutcomeImpacts(outcomeId, minConfidence = null, impactDirection = null) {
  const params = new URLSearchParams()
  if (minConfidence !== null) {
    params.append('min_confidence', minConfidence)
  }
  if (impactDirection) {
    params.append('impact_direction', impactDirection)
  }
  const response = await axios.get(
    `${API_BASE_URL}/outcomes/outcomes/${outcomeId}/impacts?${params.toString()}`
  )
  return response.data
}

/**
 * Fetch chronological causal-pressure trajectory toward an outcome event.
 * Returns sorted trajectory points with cumulative_pressure and a summary.
 */
export async function fetchOutcomeTrajectory(outcomeId) {
  const response = await axios.get(`${API_BASE_URL}/outcomes/${outcomeId}/trajectory`)
  return response.data
}

/**
 * Fetch impact edges from a specific event
 */
export async function fetchEventImpacts(eventId, minConfidence = null, impactDirection = null) {
  const params = new URLSearchParams()
  if (minConfidence !== null) {
    params.append('min_confidence', minConfidence)
  }
  if (impactDirection) {
    params.append('impact_direction', impactDirection)
  }
  const response = await axios.get(
    `${API_BASE_URL}/outcomes/events/${eventId}/impacts?${params.toString()}`
  )
  return response.data
}

/**
 * Mark an outcome event as the actual outcome
 */
export async function markActualOutcome(outcomeId, isActual) {
  const response = await axios.post(
    `${API_BASE_URL}/outcomes/outcomes/${outcomeId}/mark-actual?is_actual=${isActual}`
  )
  return response.data
}

/**
 * Fetch list of saved benchmark results
 */
export async function fetchBenchmarkResults() {
  const response = await axios.get(`${API_BASE_URL}/benchmark/results`)
  return response.data
}

/**
 * Fetch full result data for a specific benchmark run
 */
export async function fetchBenchmarkResult(runId) {
  const response = await axios.get(`${API_BASE_URL}/benchmark/results/${runId}`)
  return response.data
}

export async function fetchBenchmarkResultFiltered(runId) {
  const response = await axios.get(`${API_BASE_URL}/benchmark/results/${runId}/filtered`)
  return response.data
}

/**
 * Fetch available experiment conditions
 */
export async function fetchBenchmarkConditions() {
  const response = await axios.get(`${API_BASE_URL}/benchmark/conditions`)
  return response.data
}
/**
 * Fetch all articles collected for a specific question
 */
export async function fetchQuestionArticles(questionId) {
  const response = await axios.get(`${API_BASE_URL}/questions/${questionId}/articles`)
  return response.data
}

export async function fetchQuestionSlotPreview(questionId, slot = 'mid') {
  const response = await axios.get(
    `${API_BASE_URL}/questions/${questionId}/slot_preview?slot=${slot}`
  )
  return response.data
}

/**
 * Review a single event using LLM
 */
export async function reviewEvent(eventId) {
  const response = await axios.post(`${API_BASE_URL}/events/${eventId}/review`)
  return response.data
}

/**
 * Review all pending events for a question using LLM
 */
export async function reviewQuestionEvents(questionId) {
  const response = await axios.post(`${API_BASE_URL}/questions/${questionId}/events/review`)
  return response.data
}
