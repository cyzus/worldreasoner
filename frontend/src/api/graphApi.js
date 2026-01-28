import axios from 'axios'

const API_BASE_URL = '/api'

/**
 * Fetch graph data with optional filters
 */
export async function fetchGraph(params = {}) {
  const queryParams = new URLSearchParams()

  if (params.nodeTypes?.length) {
    queryParams.append('node_types', params.nodeTypes.join(','))
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
 */
export async function fetchQuestionPriceHistory(questionId, interval = '1d') {
  const response = await axios.get(
    `${API_BASE_URL}/questions/${questionId}/price_history?interval=${interval}`
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
 * Fetch search index status
 */
export async function fetchSearchIndexStatus() {
  const response = await axios.get(`${API_BASE_URL}/search/status`)
  return response.data
}

/**
 * Build or rebuild search indexes
 */
export async function buildSearchIndex(rebuild = false, embeddingModel = null, batchSize = 2) {
  const response = await axios.post(`${API_BASE_URL}/search/build-index`, {
    rebuild,
    embedding_model: embeddingModel,
    batch_size: batchSize
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
