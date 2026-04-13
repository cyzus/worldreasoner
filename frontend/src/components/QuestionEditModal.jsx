import React, { useState, useEffect } from 'react'
import './QuestionEditModal.css'

/**
 * QuestionEditModal - Modal dialog for editing question details
 */
function QuestionEditModal({ question, onClose, onSave }) {
  const toInputDateTime = (isoValue) => {
    if (!isoValue) return ''
    const date = new Date(isoValue)
    if (Number.isNaN(date.getTime())) return ''
    const pad = (v) => String(v).padStart(2, '0')
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
  }

  const listToText = (items) => (Array.isArray(items) ? items.join('\n') : '')
  const textToList = (text) =>
    text
      .split('\n')
      .map(item => item.trim())
      .filter(Boolean)

  const [formData, setFormData] = useState({
    question_text: '',
    question_type: '',
    domain: '',
    source: '',
    difficulty: 1,
    resolution_date: '',
    estimated_start_time: '',
    resolution_criteria: '',
    resolution_reasoning: '',
    context: '',
    ground_truth: '',
    target_event_id: '',
    outcome_event_ids: '',
    related_event_ids: '',
    related_article_ids: '',
    options: '',
    quantity_unit: '',
    quantity_bounds: '',
    metadata: '',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Initialize form data when question changes
  useEffect(() => {
    if (question) {
      setFormData({
        question_text: question.question_text || '',
        question_type: question.question_type || '',
        domain: question.domain || '',
        source: question.source || '',
        difficulty: question.difficulty || 1,
        resolution_date: toInputDateTime(question.resolution_date),
        estimated_start_time: toInputDateTime(question.estimated_start_time),
        resolution_criteria: question.resolution_criteria || '',
        resolution_reasoning: question.resolution_reasoning || '',
        context: question.context || '',
        ground_truth: question.ground_truth !== null && question.ground_truth !== undefined
          ? String(question.ground_truth)
          : '',
        target_event_id: question.target_event_id || '',
        outcome_event_ids: listToText(question.outcome_event_ids),
        related_event_ids: listToText(question.related_event_ids),
        related_article_ids: listToText(question.related_article_ids),
        options: listToText(question.options),
        quantity_unit: question.quantity_unit || '',
        quantity_bounds: question.quantity_bounds
          ? JSON.stringify(question.quantity_bounds, null, 2)
          : '',
        metadata: question.metadata
          ? JSON.stringify(question.metadata, null, 2)
          : '',
      })
    }
  }, [question])

  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData(prev => ({
      ...prev,
      [name]: name === 'difficulty' ? parseInt(value) : value
    }))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      // Prepare update payload (only include changed fields)
      const payload = {}

      if (formData.question_text !== question.question_text) {
        payload.question_text = formData.question_text
      }
      if (formData.question_type !== question.question_type) {
        payload.question_type = formData.question_type
      }
      if (formData.domain !== question.domain) {
        payload.domain = formData.domain
      }
      if (formData.source !== (question.source || '')) {
        payload.source = formData.source
      }
      if (formData.difficulty !== question.difficulty) {
        payload.difficulty = formData.difficulty
      }
      if (formData.resolution_date !== toInputDateTime(question.resolution_date)) {
        if (!formData.resolution_date) {
          throw new Error('Resolution date is required and cannot be empty')
        }
        payload.resolution_date = new Date(formData.resolution_date).toISOString()
      }
      if (formData.estimated_start_time !== toInputDateTime(question.estimated_start_time) && formData.estimated_start_time) {
        payload.estimated_start_time = new Date(formData.estimated_start_time).toISOString()
      }
      if (formData.resolution_criteria !== (question.resolution_criteria || '')) {
        payload.resolution_criteria = formData.resolution_criteria
      }
      if (formData.resolution_reasoning !== (question.resolution_reasoning || '')) {
        payload.resolution_reasoning = formData.resolution_reasoning
      }
      if (formData.context !== (question.context || '')) {
        payload.context = formData.context
      }

      // Handle ground_truth conversion
      const currentGroundTruth = question.ground_truth !== null && question.ground_truth !== undefined
        ? String(question.ground_truth)
        : ''
      if (formData.ground_truth !== currentGroundTruth) {
        // Try to parse as JSON if it looks like a boolean or number
        let parsedValue = formData.ground_truth
        if (formData.ground_truth.toLowerCase() === 'true') {
          parsedValue = true
        } else if (formData.ground_truth.toLowerCase() === 'false') {
          parsedValue = false
        } else if (!isNaN(formData.ground_truth) && formData.ground_truth !== '') {
          parsedValue = Number(formData.ground_truth)
        }
        payload.ground_truth = parsedValue
      }

      if (formData.target_event_id !== (question.target_event_id || '') && formData.target_event_id) {
        payload.target_event_id = formData.target_event_id
      }

      const outcomeEventIds = textToList(formData.outcome_event_ids)
      const currentOutcomeEventIds = Array.isArray(question.outcome_event_ids) ? question.outcome_event_ids : []
      if (JSON.stringify(outcomeEventIds) !== JSON.stringify(currentOutcomeEventIds)) {
        payload.outcome_event_ids = outcomeEventIds
      }

      const relatedEventIds = textToList(formData.related_event_ids)
      const currentRelatedEventIds = Array.isArray(question.related_event_ids) ? question.related_event_ids : []
      if (JSON.stringify(relatedEventIds) !== JSON.stringify(currentRelatedEventIds)) {
        payload.related_event_ids = relatedEventIds
      }

      const relatedArticleIds = textToList(formData.related_article_ids)
      const currentRelatedArticleIds = Array.isArray(question.related_article_ids) ? question.related_article_ids : []
      if (JSON.stringify(relatedArticleIds) !== JSON.stringify(currentRelatedArticleIds)) {
        payload.related_article_ids = relatedArticleIds
      }

      const options = textToList(formData.options)
      const currentOptions = Array.isArray(question.options) ? question.options : []
      if (JSON.stringify(options) !== JSON.stringify(currentOptions)) {
        payload.options = options
      }

      if (formData.quantity_unit !== (question.quantity_unit || '')) {
        payload.quantity_unit = formData.quantity_unit
      }

      const currentQuantityBounds = question.quantity_bounds || null
      const quantityBoundsText = formData.quantity_bounds.trim()
      const nextQuantityBounds = quantityBoundsText ? JSON.parse(quantityBoundsText) : null
      if (JSON.stringify(nextQuantityBounds) !== JSON.stringify(currentQuantityBounds) && nextQuantityBounds !== null) {
        payload.quantity_bounds = nextQuantityBounds
      }

      const currentMetadata = question.metadata || null
      const metadataText = formData.metadata.trim()
      const nextMetadata = metadataText ? JSON.parse(metadataText) : null
      if (JSON.stringify(nextMetadata) !== JSON.stringify(currentMetadata) && nextMetadata !== null) {
        payload.metadata = nextMetadata
      }

      // Only send request if there are changes
      if (Object.keys(payload).length === 0) {
        onClose()
        return
      }

      const response = await fetch(`/api/questions/${question.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to update question')
      }

      const updatedQuestion = await response.json()
      onSave(updatedQuestion)
      onClose()
    } catch (err) {
      setError(`Error: ${err.message}`)
      console.error('Update error:', err)
    } finally {
      setLoading(false)
    }
  }

  if (!question) return null

  // Available options for dropdowns
  const questionTypes = ['binary', 'mcq', 'quantity', 'timeframe']
  const domains = ['finance', 'politics', 'tech', 'health', 'climate', 'culture', 'business', 'science', 'sports', 'general']

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Edit Question</h3>
          <button className="close-btn" onClick={onClose}>&times;</button>
        </div>

        {error && (
          <div className="error-message">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="edit-form">
          <div className="form-group">
            <label htmlFor="question_text">Question Text *</label>
            <textarea
              id="question_text"
              name="question_text"
              value={formData.question_text}
              onChange={handleChange}
              required
              rows={3}
              className="form-input"
            />
          </div>

          <div className="form-row">
            <div className="form-group">
              <label htmlFor="question_type">Question Type *</label>
              <select
                id="question_type"
                name="question_type"
                value={formData.question_type}
                onChange={handleChange}
                required
                className="form-input"
              >
                {questionTypes.map(type => (
                  <option key={type} value={type}>{type}</option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="domain">Domain *</label>
              <select
                id="domain"
                name="domain"
                value={formData.domain}
                onChange={handleChange}
                required
                className="form-input"
              >
                {domains.map(domain => (
                  <option key={domain} value={domain}>{domain}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label htmlFor="source">Source *</label>
              <input
                type="text"
                id="source"
                name="source"
                value={formData.source}
                onChange={handleChange}
                required
                className="form-input"
                placeholder="polymarket, news, manual, ..."
              />
            </div>

            <div className="form-group">
              <label htmlFor="difficulty">Difficulty (1-5) *</label>
              <input
                type="number"
                id="difficulty"
                name="difficulty"
                value={formData.difficulty}
                onChange={handleChange}
                min="1"
                max="5"
                required
                className="form-input"
              />
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label htmlFor="resolution_date">Resolution Date *</label>
              <input
                type="datetime-local"
                id="resolution_date"
                name="resolution_date"
                value={formData.resolution_date}
                onChange={handleChange}
                required
                className="form-input"
              />
            </div>

            <div className="form-group">
              <label htmlFor="estimated_start_time">Estimated Start Time</label>
              <input
                type="datetime-local"
                id="estimated_start_time"
                name="estimated_start_time"
                value={formData.estimated_start_time}
                onChange={handleChange}
                className="form-input"
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="resolution_criteria">Resolution Criteria</label>
            <textarea
              id="resolution_criteria"
              name="resolution_criteria"
              value={formData.resolution_criteria}
              onChange={handleChange}
              rows={3}
              className="form-input"
              placeholder="Optional: Criteria for determining the outcome"
            />
          </div>

          <div className="form-group">
            <label htmlFor="ground_truth">Ground Truth</label>
            <input
              type="text"
              id="ground_truth"
              name="ground_truth"
              value={formData.ground_truth}
              onChange={handleChange}
              className="form-input"
              placeholder="Optional: true, false, or a number"
            />
          </div>

          <div className="form-group">
            <label htmlFor="context">Context</label>
            <textarea
              id="context"
              name="context"
              value={formData.context}
              onChange={handleChange}
              rows={2}
              className="form-input"
              placeholder="Optional question context shown to forecasters"
            />
          </div>

          <div className="form-group">
            <label htmlFor="resolution_reasoning">Resolution Reasoning</label>
            <textarea
              id="resolution_reasoning"
              name="resolution_reasoning"
              value={formData.resolution_reasoning}
              onChange={handleChange}
              rows={2}
              className="form-input"
              placeholder="Optional explanation of why the ground truth was resolved this way"
            />
          </div>

          <div className="form-group">
            <label htmlFor="target_event_id">Target Event ID</label>
            <input
              type="text"
              id="target_event_id"
              name="target_event_id"
              value={formData.target_event_id}
              onChange={handleChange}
              className="form-input"
              placeholder="Optional target event id"
            />
          </div>

          <div className="form-row">
            <div className="form-group">
              <label htmlFor="outcome_event_ids">Outcome Event IDs (one per line)</label>
              <textarea
                id="outcome_event_ids"
                name="outcome_event_ids"
                value={formData.outcome_event_ids}
                onChange={handleChange}
                rows={3}
                className="form-input"
              />
            </div>

            <div className="form-group">
              <label htmlFor="related_event_ids">Related Event IDs (one per line)</label>
              <textarea
                id="related_event_ids"
                name="related_event_ids"
                value={formData.related_event_ids}
                onChange={handleChange}
                rows={3}
                className="form-input"
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="related_article_ids">Related Article IDs (one per line)</label>
            <textarea
              id="related_article_ids"
              name="related_article_ids"
              value={formData.related_article_ids}
              onChange={handleChange}
              rows={3}
              className="form-input"
            />
          </div>

          <div className="form-group">
            <label htmlFor="options">Options (for MCQ, one per line)</label>
            <textarea
              id="options"
              name="options"
              value={formData.options}
              onChange={handleChange}
              rows={3}
              className="form-input"
            />
          </div>

          <div className="form-row">
            <div className="form-group">
              <label htmlFor="quantity_unit">Quantity Unit</label>
              <input
                type="text"
                id="quantity_unit"
                name="quantity_unit"
                value={formData.quantity_unit}
                onChange={handleChange}
                className="form-input"
                placeholder="USD, %, people, ..."
              />
            </div>

            <div className="form-group">
              <label htmlFor="quantity_bounds">Quantity Bounds JSON</label>
              <textarea
                id="quantity_bounds"
                name="quantity_bounds"
                value={formData.quantity_bounds}
                onChange={handleChange}
                rows={3}
                className="form-input"
                placeholder='{"min": 0, "max": 100}'
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="metadata">Metadata JSON</label>
            <textarea
              id="metadata"
              name="metadata"
              value={formData.metadata}
              onChange={handleChange}
              rows={4}
              className="form-input"
              placeholder='{"market_slug": "...", "clob_token_ids": ["..."]}'
            />
          </div>

          <div className="form-actions">
            <button
              type="button"
              onClick={onClose}
              className="btn btn-secondary"
              disabled={loading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading}
            >
              {loading ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default QuestionEditModal
