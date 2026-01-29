/**
 * Monitor API for question evidence and forecast readiness.
 */

const API_BASE = '/api/monitor'

/**
 * Fetch questions that need evidence collection.
 * @param {Object} filters - Optional filters
 * @param {number} filters.min_quality - Minimum quality score
 * @param {string} filters.domain - Filter by domain
 * @param {number} filters.limit - Maximum results
 */
export const fetchEvidenceNeeds = async (filters = {}) => {
    const params = new URLSearchParams()
    if (filters.min_quality) params.append('min_quality', filters.min_quality)
    if (filters.domain) params.append('domain', filters.domain)
    if (filters.limit) params.append('limit', filters.limit)

    const url = params.toString() ? `${API_BASE}/evidence-needs?${params}` : `${API_BASE}/evidence-needs`
    const response = await fetch(url)
    if (!response.ok) throw new Error(`Failed to fetch evidence needs: ${response.statusText}`)
    return response.json()
}

/**
 * Check evidence satisfaction status for a question.
 * @param {string} questionId - Question ID
 */
export const fetchSatisfaction = async (questionId) => {
    const response = await fetch(`${API_BASE}/questions/${questionId}/satisfaction`)
    if (!response.ok) throw new Error(`Failed to fetch satisfaction: ${response.statusText}`)
    return response.json()
}

/**
 * Get forecast readiness and available modes for a question.
 * @param {string} questionId - Question ID
 */
export const fetchForecastReadiness = async (questionId) => {
    const response = await fetch(`${API_BASE}/questions/${questionId}/forecast-readiness`)
    if (!response.ok) throw new Error(`Failed to fetch readiness: ${response.statusText}`)
    return response.json()
}

/**
 * Get LLM model usage statistics.
 * @param {string} modelName - Optional filter to specific model
 */
export const fetchModelStats = async (modelName = null) => {
    const url = modelName
        ? `${API_BASE}/model-stats?model_name=${encodeURIComponent(modelName)}`
        : `${API_BASE}/model-stats`
    const response = await fetch(url)
    if (!response.ok) throw new Error(`Failed to fetch model stats: ${response.statusText}`)
    return response.json()
}

/**
 * Start a pipeline job for specific questions.
 * @param {string[]} questionIds - List of question IDs
 * @param {string} pipelineType - Pipeline type (e.g., 'news_collection', 'evidence')
 * @param {Object} config - Optional config
 */
export const startPipeline = async (questionIds, pipelineType, config = {}) => {
    const response = await fetch('/api/pipelines/jobs', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            question_ids: questionIds,
            pipeline_type: pipelineType,
            config
        })
    })

    if (!response.ok) throw new Error(`Failed to start pipeline: ${response.statusText}`)
    return response.json()
}
