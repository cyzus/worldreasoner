import React, { useState, useEffect } from 'react'
import { fetchSearchIndexStatus, buildSearchIndex, cleanupOrphanedEmbeddings } from '../api/graphApi'
import './SearchIndexStatus.css'

/**
 * SearchIndexStatus - Banner showing search index status and build controls
 */
const SearchIndexStatus = ({ databasePath, visible = true }) => {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [building, setBuilding] = useState(false)
  const [cleaning, setCleaning] = useState(false)
  const [error, setError] = useState(null)
  const [dismissed, setDismissed] = useState(false)
  const [showDetails, setShowDetails] = useState(false)

  useEffect(() => {
    if (visible && !dismissed) {
      loadStatus()
    }
  }, [databasePath, visible])

  const loadStatus = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await fetchSearchIndexStatus()
      setStatus(data)
    } catch (err) {
      console.error('Error loading search index status:', err)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleBuildIndex = async (rebuild = false) => {
    try {
      setBuilding(true)
      setError(null)
      const result = await buildSearchIndex(rebuild)

      if (result.success) {
        // Reload status after building
        await loadStatus()
      } else {
        setError(result.message)
      }
    } catch (err) {
      console.error('Error building index:', err)
      setError(err.message)
    } finally {
      setBuilding(false)
    }
  }

  const handleCleanup = async () => {
    try {
      setCleaning(true)
      setError(null)
      const result = await cleanupOrphanedEmbeddings()

      if (result.success) {
        // Reload status after cleanup
        await loadStatus()
      } else {
        setError(result.message)
      }
    } catch (err) {
      console.error('Error cleaning up orphaned embeddings:', err)
      setError(err.message)
    } finally {
      setCleaning(false)
    }
  }

  const handleDismiss = () => {
    setDismissed(true)
  }

  const handleRefresh = () => {
    setDismissed(false)
    loadStatus()
  }

  // Don't show if dismissed or not visible
  if (dismissed || !visible) {
    return null
  }

  // Don't show if loading initially
  if (loading && !status) {
    return null
  }

  // Don't show if no status data
  if (!status) {
    return null
  }

  // Determine banner type and message
  const needsIndexing = status.needs_indexing
  const isUpToDate = !needsIndexing && status.total_articles > 0
  const noArticles = status.total_articles === 0
  
  // Check if there are orphaned embeddings (more embeddings than articles)
  const hasOrphans = status.embeddings_indexed > status.total_articles

  // Don't show banner if up to date (unless user wants to see details)
  if (isUpToDate && !showDetails) {
    return (
      <div className="search-index-status compact">
        <button className="status-show-btn" onClick={() => setShowDetails(true)}>
          <span className="status-icon">🔍</span>
          <span className="status-text">Search Index: {status.embeddings_indexed}/{status.total_articles} indexed</span>
        </button>
      </div>
    )
  }

  return (
    <div className={`search-index-status ${needsIndexing ? 'warning' : 'info'} ${showDetails ? 'expanded' : ''}`}>
      <div className="status-header">
        <div className="status-left">
          <span className="status-icon">
            {building ? '⏳' : needsIndexing ? '⚠️' : noArticles ? 'ℹ️' : '✅'}
          </span>
          <div className="status-info">
            <div className="status-title">
              {building ? 'Building Search Index...' :
               needsIndexing ? 'Search Index Needs Update' :
               noArticles ? 'No Articles to Index' :
               'Search Index Up to Date'}
            </div>
            <div className="status-details">
              {status.embeddings_indexed} of {status.total_articles} articles indexed
              {status.embedding_model && ` • Model: ${status.embedding_model}`}
            </div>
          </div>
        </div>

        <div className="status-actions">
          {needsIndexing && !building && !cleaning && (
            <button
              className="status-btn primary"
              onClick={() => handleBuildIndex(false)}
              title="Index new articles only"
            >
              Build Index
            </button>
          )}

          {!building && !cleaning && status.total_articles > 0 && (
            <button
              className="status-btn secondary"
              onClick={() => handleBuildIndex(true)}
              title="Rebuild all indexes from scratch"
            >
              Rebuild All
            </button>
          )}

          {!building && !cleaning && hasOrphans && (
            <button
              className="status-btn warning"
              onClick={handleCleanup}
              title="Remove embeddings for deleted articles"
            >
              🗑️ Cleanup
            </button>
          )}

          <button
            className="status-btn icon-btn"
            onClick={handleRefresh}
            disabled={building || cleaning}
            title="Refresh status"
          >
            🔄
          </button>

          {showDetails && (
            <button
              className="status-btn icon-btn"
              onClick={() => setShowDetails(false)}
              title="Hide details"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="status-error">
          <span className="error-icon">❌</span>
          <span className="error-message">{error}</span>
        </div>
      )}

      {showDetails && (
        <div className="status-expanded">
          <div className="status-stats">
            <div className="stat-item">
              <div className="stat-label">Total Articles</div>
              <div className="stat-value">{status.total_articles}</div>
            </div>
            <div className="stat-item">
              <div className="stat-label">FTS Indexed</div>
              <div className="stat-value">{status.fts_indexed}</div>
            </div>
            <div className="stat-item">
              <div className="stat-label">Embeddings Indexed</div>
              <div className="stat-value">{status.embeddings_indexed}</div>
            </div>
            <div className="stat-item">
              <div className="stat-label">Models</div>
              <div className="stat-value">
                {Object.keys(status.models).length > 0
                  ? Object.entries(status.models).map(([model, count]) => `${model} (${count})`).join(', ')
                  : 'None'}
              </div>
            </div>
          </div>
        </div>
      )}

      {(building || cleaning) && (
        <div className="status-progress">
          <div className="progress-bar">
            <div className="progress-fill"></div>
          </div>
          <div className="progress-text">
            {building ? 'Indexing articles...' : 'Cleaning up orphaned embeddings...'}
          </div>
        </div>
      )}
    </div>
  )
}

export default SearchIndexStatus
