import React, { useState } from 'react'
import './CollectionConfigPanel.css'

/**
 * CollectionConfigPanel - Configuration panel for question collection
 *
 * Allows users to configure:
 * - Number of questions to fetch
 * - Domain/category filters
 * - Question type filters
 * - Difficulty range
 * - Source-specific options (e.g., search query, resolved markets)
 */
function CollectionConfigPanel({ source, onFetch, loading }) {
  const [config, setConfig] = useState({
    count: 20,
    domains: [],
    question_types: [],
    min_difficulty: 1,
    max_difficulty: 5,
    include_resolved: true,
    search_query: '',
    lookback_days: 730, // Default: 2 years
  })

  // Available options (must match backend enums in src/domain/models/)
  const availableDomains = [
    'finance', 'politics', 'tech', 'health', 'climate',
    'culture', 'business', 'science', 'sports', 'general'
  ]

  const availableQuestionTypes = [
    'binary', 'mcq', 'quantity', 'timeframe'
  ]

  const handleInputChange = (field, value) => {
    setConfig(prev => ({ ...prev, [field]: value }))
  }

  const handleMultiSelect = (field, value) => {
    setConfig(prev => {
      const currentValues = prev[field] || []
      const newValues = currentValues.includes(value)
        ? currentValues.filter(v => v !== value)
        : [...currentValues, value]
      return { ...prev, [field]: newValues }
    })
  }

  const handleFetch = () => {
    // Clean up config before sending
    const cleanConfig = {
      count: config.count,
      ...(config.domains.length > 0 && { domains: config.domains }),
      ...(config.question_types.length > 0 && { question_types: config.question_types }),
      ...(config.min_difficulty > 1 && { min_difficulty: config.min_difficulty }),
      ...(config.max_difficulty < 5 && { max_difficulty: config.max_difficulty }),
    }

    // Add source-specific options
    if (source === 'polymarket') {
      cleanConfig.include_resolved = config.include_resolved
      if (config.search_query.trim()) {
        cleanConfig.search_query = config.search_query.trim()
      }
    }

    onFetch(cleanConfig)
  }

  return (
    <div className="collection-config">
      <h3>⚙️ Collection Settings</h3>

      {/* Polymarket Search (only show for Polymarket source) */}
      {source === 'polymarket' && (
        <>
          <div className="config-section">
            <label className="config-label">
              Search Markets
              <span className="label-hint">(optional)</span>
            </label>
            <input
              type="text"
              value={config.search_query}
              onChange={(e) => handleInputChange('search_query', e.target.value)}
              className="config-input"
              placeholder="e.g., Bitcoin, US Election, AI..."
              disabled={loading}
            />
            <p className="config-description">
              Search for specific markets by keywords. Leave empty to fetch all markets.
            </p>
          </div>

          {/* Time Window */}
          <div className="config-section">
            <label className="config-label">
              Max Age of Markets
              <span className="label-hint">(how far back to search)</span>
            </label>
            <select
              value={config.lookback_days}
              onChange={(e) => handleInputChange('lookback_days', parseInt(e.target.value))}
              className="config-input"
              disabled={loading}
            >
              <option value="30">Last 30 days</option>
              <option value="90">Last 90 days</option>
              <option value="180">Last 6 months</option>
              <option value="365">Last year</option>
              <option value="730">Last 2 years</option>
              <option value="1825">Last 5 years</option>
              <option value="3650">All time (10 years)</option>
            </select>
            <p className="config-description">
              Only include markets that closed within this time window.
            </p>
          </div>
        </>
      )}

      {/* Count */}
      <div className="config-section">
        <label className="config-label">
          Number of Questions
          <span className="label-hint">(1-500)</span>
        </label>
        <input
          type="number"
          min="1"
          max="500"
          value={config.count}
          onChange={(e) => handleInputChange('count', parseInt(e.target.value))}
          className="config-input"
          disabled={loading}
        />
      </div>

      {/* Difficulty Range */}
      <div className="config-section">
        <label className="config-label">
          Difficulty Range
          <span className="label-hint">(1=Easy, 5=Hard)</span>
        </label>
        <div className="range-inputs">
          <input
            type="number"
            min="1"
            max="5"
            value={config.min_difficulty}
            onChange={(e) => handleInputChange('min_difficulty', parseInt(e.target.value))}
            className="config-input range-input"
            disabled={loading}
            placeholder="Min"
          />
          <span className="range-separator">to</span>
          <input
            type="number"
            min="1"
            max="5"
            value={config.max_difficulty}
            onChange={(e) => handleInputChange('max_difficulty', parseInt(e.target.value))}
            className="config-input range-input"
            disabled={loading}
            placeholder="Max"
          />
        </div>
      </div>

      {/* Domains */}
      <div className="config-section">
        <label className="config-label">
          Domains
          <span className="label-hint">(optional)</span>
        </label>
        <div className="multi-select-grid">
          {availableDomains.map(domain => (
            <button
              key={domain}
              className={`chip ${config.domains.includes(domain) ? 'selected' : ''}`}
              onClick={() => handleMultiSelect('domains', domain)}
              disabled={loading}
            >
              {domain}
            </button>
          ))}
        </div>
      </div>

      {/* Question Types */}
      <div className="config-section">
        <label className="config-label">
          Question Types
          <span className="label-hint">(optional)</span>
        </label>
        <div className="multi-select-grid">
          {availableQuestionTypes.map(type => (
            <button
              key={type}
              className={`chip ${config.question_types.includes(type) ? 'selected' : ''}`}
              onClick={() => handleMultiSelect('question_types', type)}
              disabled={loading}
            >
              {type}
            </button>
          ))}
        </div>
      </div>

      {/* Polymarket-specific options */}
      {source === 'polymarket' && (
        <div className="config-section">
          <label className="config-checkbox">
            <input
              type="checkbox"
              checked={config.include_resolved}
              onChange={(e) => handleInputChange('include_resolved', e.target.checked)}
              disabled={loading}
            />
            <span>Include resolved markets</span>
          </label>
        </div>
      )}

      {/* Fetch button */}
      <button
        className="fetch-button"
        onClick={handleFetch}
        disabled={loading}
      >
        {loading ? '⏳ Fetching...' : '🔍 Fetch Questions'}
      </button>

      {/* Instructions */}
      <div className="config-help">
        <h4>💡 Tips</h4>
        <ul>
          <li>Leave filters empty to fetch all available questions</li>
          <li>Combine multiple filters to narrow results</li>
          {source === 'polymarket' && (
            <li>Use the search box to find specific markets by keywords</li>
          )}
          {source === 'news' && (
            <li>News-based questions are generated from recent articles</li>
          )}
        </ul>
      </div>
    </div>
  )
}

export default CollectionConfigPanel
