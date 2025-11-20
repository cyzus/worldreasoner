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
