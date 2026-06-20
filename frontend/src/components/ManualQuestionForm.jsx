import React, { useState } from 'react'
import './ManualQuestionForm.css'

/**
 * ManualQuestionForm - Form for manually creating forecast questions
 *
 * Features:
 * - All required question fields
 * - Dynamic form fields based on question type
 * - Validation before submission
 * - Direct save to database
 */
function ManualQuestionForm({ onQuestionCreated }) {
  // Question types
  const QUESTION_TYPES = ['binary', 'mcq', 'quantity', 'timeframe']

  // Domains
  const DOMAINS = [
    'finance', 'politics', 'tech', 'health', 'climate',
    'culture', 'business', 'science', 'sports', 'general'
  ]

  // Form state
  const [formData, setFormData] = useState({
    question_text: '',
    question_type: 'binary',
    domain: 'general',
    difficulty: 3,
    source: 'manual',
    resolution_date: '',
    ground_truth: '',
    resolution_criteria: '',
    context: '',
    related_event_ids: '',
    // MCQ specific
    options: '',
    // Quantity specific
    quantity_unit: '',
    quantity_min: '',
    quantity_max: '',
  })

  const [errors, setErrors] = useState({})
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(null)
  const [error, setError] = useState(null)

  /**
   * Handle form field changes
   */
  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData(prev => ({
      ...prev,
      [name]: value
    }))
    // Clear error for this field
    if (errors[name]) {
      setErrors(prev => {
        const newErrors = { ...prev }
        delete newErrors[name]
        return newErrors
      })
    }
  }

  /**
   * Validate form data
   */
  const validateForm = () => {
    const newErrors = {}

    // Required fields
    if (!formData.question_text.trim()) {
      newErrors.question_text = 'Question text is required'
    } else if (formData.question_text.trim().length < 20) {
      newErrors.question_text = 'Question text must be at least 20 characters'
    }
    if (!formData.resolution_date) {
      newErrors.resolution_date = 'Resolution date is required'
    }

    // Type-specific validation
    if (formData.question_type === 'mcq') {
      if (!formData.options.trim()) {
        newErrors.options = 'Options are required for MCQ questions'
      } else {
        const optionsList = formData.options.split(',').map(o => o.trim()).filter(o => o)
        if (optionsList.length < 3) {
          newErrors.options = 'MCQ questions need at least 3 options (comma-separated)'
        }
      }
    }

    if (formData.question_type === 'quantity') {
      if (!formData.quantity_unit.trim()) {
        newErrors.quantity_unit = 'Unit is required for quantity questions'
      }
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  /**
   * Handle form submission
   */
  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)
    setSuccess(null)

    // Validate form
    if (!validateForm()) {
      setError('Please fix the validation errors')
      return
    }

    setLoading(true)

    try {
      // Auto-generate a unique question ID
      const generatedId = `q_manual_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`

      // Prepare question data
      const questionData = {
        id: generatedId,
        question_text: formData.question_text.trim(),
        question_type: formData.question_type,
        domain: formData.domain,
        difficulty: parseInt(formData.difficulty),
        source: formData.source,
        resolution_date: new Date(formData.resolution_date).toISOString(),
        resolution_criteria: formData.resolution_criteria.trim() || null,
        context: formData.context.trim() || null,
        related_event_ids: formData.related_event_ids
          ? formData.related_event_ids.split(',').map(id => id.trim()).filter(id => id)
          : [],
        metadata: {},
      }

      // Add ground_truth as string (database handles serialization)
      if (formData.ground_truth !== '') {
        questionData.ground_truth = formData.ground_truth.trim()
      } else {
        questionData.ground_truth = null
      }

      // Add type-specific fields
      if (formData.question_type === 'mcq' && formData.options) {
        questionData.options = formData.options.split(',').map(o => o.trim()).filter(o => o)
      }

      if (formData.question_type === 'quantity') {
        if (formData.quantity_unit) {
          questionData.quantity_unit = formData.quantity_unit.trim()
        }
        if (formData.quantity_min !== '' || formData.quantity_max !== '') {
          questionData.quantity_bounds = {}
          if (formData.quantity_min !== '') {
            questionData.quantity_bounds.min = parseFloat(formData.quantity_min)
          }
          if (formData.quantity_max !== '') {
            questionData.quantity_bounds.max = parseFloat(formData.quantity_max)
          }
        }
      }

      // Send to API
      const response = await fetch('/api/questions/batch-save', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          question_ids: [questionData.id],
          questions: [questionData],
        }),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to save question')
      }

      const data = await response.json()

      if (data.success) {
        setSuccess(`Question created successfully: ${questionData.id}`)

        // Reset form
        setFormData({
          question_text: '',
          question_type: 'binary',
          domain: 'general',
          difficulty: 3,
          source: 'manual',
          resolution_date: '',
          ground_truth: '',
          resolution_criteria: '',
          context: '',
          target_event_id: '',
          related_event_ids: '',
          options: '',
          quantity_unit: '',
          quantity_min: '',
          quantity_max: '',
        })

        // Notify parent
        if (onQuestionCreated) {
          onQuestionCreated(questionData)
        }
      } else {
        setError(data.errors?.join('; ') || 'Failed to save question')
      }
    } catch (err) {
      setError(`Error: ${err.message}`)
      console.error('Question creation error:', err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="manual-question-form">
      <div className="form-header">
        <h3>Create Question Manually</h3>
        <p className="form-subtitle">
          Fill in the form below to create a custom forecast question
        </p>
      </div>

      {/* Status messages */}
      {error && (
        <div className="message error-message">
          {error}
        </div>
      )}
      {success && (
        <div className="message success-message">
          {success}
        </div>
      )}

      <form onSubmit={handleSubmit} className="question-form">
        {/* Question Text */}
        <div className="form-group full-width">
          <label htmlFor="question_text">
            Question Text <span className="required">*</span>
          </label>
          <textarea
            id="question_text"
            name="question_text"
            value={formData.question_text}
            onChange={handleChange}
            placeholder="Enter your forecast question (minimum 20 characters)"
            rows="3"
            className={errors.question_text ? 'error' : ''}
            disabled={loading}
          />
          {errors.question_text && <span className="error-text">{errors.question_text}</span>}
          <span className="char-count">{formData.question_text.length} characters</span>
        </div>

        {/* Question Type */}
        <div className="form-row">
          <div className="form-group">
            <label htmlFor="question_type">
              Question Type <span className="required">*</span>
            </label>
            <select
              id="question_type"
              name="question_type"
              value={formData.question_type}
              onChange={handleChange}
              disabled={loading}
            >
              {QUESTION_TYPES.map(type => (
                <option key={type} value={type}>
                  {type.charAt(0).toUpperCase() + type.slice(1)}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="domain">
              Domain <span className="required">*</span>
            </label>
            <select
              id="domain"
              name="domain"
              value={formData.domain}
              onChange={handleChange}
              disabled={loading}
            >
              {DOMAINS.map(domain => (
                <option key={domain} value={domain}>
                  {domain.charAt(0).toUpperCase() + domain.slice(1)}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="difficulty">
              Difficulty <span className="required">*</span>
            </label>
            <select
              id="difficulty"
              name="difficulty"
              value={formData.difficulty}
              onChange={handleChange}
              disabled={loading}
            >
              {[1, 2, 3, 4, 5].map(level => (
                <option key={level} value={level}>
                  {level} / 5
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Resolution Date */}
        <div className="form-group">
          <label htmlFor="resolution_date">
            Resolution Date <span className="required">*</span>
          </label>
          <input
            type="datetime-local"
            id="resolution_date"
            name="resolution_date"
            value={formData.resolution_date}
            onChange={handleChange}
            className={errors.resolution_date ? 'error' : ''}
            disabled={loading}
          />
          {errors.resolution_date && <span className="error-text">{errors.resolution_date}</span>}
          <span className="help-text">When will this question be resolved?</span>
        </div>

        {/* Ground Truth */}
        <div className="form-group">
          <label htmlFor="ground_truth">Ground Truth (optional)</label>
          <input
            type="text"
            id="ground_truth"
            name="ground_truth"
            value={formData.ground_truth}
            onChange={handleChange}
            placeholder={
              formData.question_type === 'binary'
                ? 'Enter "true" or "false"'
                : formData.question_type === 'quantity'
                ? 'Enter numeric value'
                : 'Enter ground truth value'
            }
            disabled={loading}
          />
          <span className="help-text">The actual outcome as string (leave empty if unresolved)</span>
        </div>

        {/* Type-specific fields */}
        {formData.question_type === 'mcq' && (
          <div className="form-group">
            <label htmlFor="options">
              Options <span className="required">*</span>
            </label>
            <input
              type="text"
              id="options"
              name="options"
              value={formData.options}
              onChange={handleChange}
              placeholder="Option 1, Option 2, Option 3, ..."
              className={errors.options ? 'error' : ''}
              disabled={loading}
            />
            {errors.options && <span className="error-text">{errors.options}</span>}
            <span className="help-text">Comma-separated list (minimum 3 options)</span>
          </div>
        )}

        {formData.question_type === 'quantity' && (
          <>
            <div className="form-group">
              <label htmlFor="quantity_unit">
                Unit <span className="required">*</span>
              </label>
              <input
                type="text"
                id="quantity_unit"
                name="quantity_unit"
                value={formData.quantity_unit}
                onChange={handleChange}
                placeholder="e.g., USD, people, GW, %"
                className={errors.quantity_unit ? 'error' : ''}
                disabled={loading}
              />
              {errors.quantity_unit && <span className="error-text">{errors.quantity_unit}</span>}
            </div>

            <div className="form-row">
              <div className="form-group">
                <label htmlFor="quantity_min">Minimum (optional)</label>
                <input
                  type="number"
                  id="quantity_min"
                  name="quantity_min"
                  value={formData.quantity_min}
                  onChange={handleChange}
                  placeholder="Min value"
                  disabled={loading}
                />
              </div>

              <div className="form-group">
                <label htmlFor="quantity_max">Maximum (optional)</label>
                <input
                  type="number"
                  id="quantity_max"
                  name="quantity_max"
                  value={formData.quantity_max}
                  onChange={handleChange}
                  placeholder="Max value"
                  disabled={loading}
                />
              </div>
            </div>
          </>
        )}

        {/* Resolution Criteria */}
        <div className="form-group full-width">
          <label htmlFor="resolution_criteria">Resolution Criteria (optional)</label>
          <textarea
            id="resolution_criteria"
            name="resolution_criteria"
            value={formData.resolution_criteria}
            onChange={handleChange}
            placeholder="How will this question be resolved? e.g., 'Based on official announcement from...'"
            rows="2"
            disabled={loading}
          />
          <span className="help-text">Objective rules for verifying the answer</span>
        </div>

        {/* Context */}
        <div className="form-group full-width">
          <label htmlFor="context">Context (optional)</label>
          <textarea
            id="context"
            name="context"
            value={formData.context}
            onChange={handleChange}
            placeholder="Background information for forecasters"
            rows="3"
            disabled={loading}
          />
          <span className="help-text">Additional background information</span>
        </div>

        {/* Submit Button */}
        <div className="form-actions">
          <button
            type="submit"
            className="btn-submit"
            disabled={loading}
          >
            {loading ? 'Creating...' : 'Create Question'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default ManualQuestionForm
