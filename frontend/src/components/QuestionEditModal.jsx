import React, { useState, useEffect } from 'react'
import './QuestionEditModal.css'

/**
 * QuestionEditModal - Modal dialog for editing question details
 */
function QuestionEditModal({ question, onClose, onSave }) {
  const [formData, setFormData] = useState({
    question_text: '',
    question_type: '',
    domain: '',
    difficulty: 1,
    resolution_criteria: '',
    ground_truth: '',
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
        difficulty: question.difficulty || 1,
        resolution_criteria: question.resolution_criteria || '',
        ground_truth: question.ground_truth !== null && question.ground_truth !== undefined
          ? String(question.ground_truth)
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
      if (formData.difficulty !== question.difficulty) {
        payload.difficulty = formData.difficulty
      }
      if (formData.resolution_criteria !== (question.resolution_criteria || '')) {
        payload.resolution_criteria = formData.resolution_criteria
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

      // Only send request if there are changes
      if (Object.keys(payload).length === 0) {
        onClose()
        return
      }

      const response = await fetch(`http://localhost:8018/api/questions/${question.id}`, {
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
  const questionTypes = ['binary', 'multiple_choice', 'numeric', 'date']
  const domains = ['politics', 'technology', 'science', 'business', 'sports', 'culture', 'health', 'finance']

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
