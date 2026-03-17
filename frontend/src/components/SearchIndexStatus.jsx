import React, { useState, useEffect } from 'react'
import { fetchSearchIndexStatus, buildSearchIndex, cleanupOrphanedEmbeddings } from '../api/graphApi'
import './SearchIndexStatus.css'

/**
 * SearchIndexStatus - Banner showing search index status and build controls
 */
const SearchIndexStatus = ({ databasePath, visible = true }) => {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [buildingFts, setBuildingFts] = useState(false)
  const [buildingEmbeddings, setBuildingEmbeddings] = useState(false)
  const [cleaning, setCleaning] = useState(false)
  const [error, setError] = useState(null)
  const [dismissed, setDismissed] = useState(false)
  const [showDetails, setShowDetails] = useState(false)

  const isBusy = buildingFts || buildingEmbeddings || cleaning

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

  const handleBuildFts = async (rebuild = false) => {
    try {
      setBuildingFts(true)
      setError(null)
      const result = await buildSearchIndex(rebuild, null, 2, true)
      if (result.success) {
        await loadStatus()
      } else {
        setError(result.message)
      }
    } catch (err) {
      console.error('Error building FTS index:', err)
      setError(err.message)
    } finally {
      setBuildingFts(false)
    }
  }

  const handleBuildEmbeddings = async (rebuild = false) => {
    try {
      setBuildingEmbeddings(true)
      setError(null)
      const result = await buildSearchIndex(rebuild, null, 2, false)
      if (result.success) {
        await loadStatus()
      } else {
        setError(result.message)
      }
    } catch (err) {
      console.error('Error building embeddings:', err)
      setError(err.message)
    } finally {
      setBuildingEmbeddings(false)
    }
  }

  const handleCleanup = async () => {
    try {
      setCleaning(true)
      setError(null)
      const result = await cleanupOrphanedEmbeddings()
      if (result.success) {
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

  const handleRefresh = () => {
    setDismissed(false)
    loadStatus()
  }

  if (dismissed || !visible) return null
  if (loading && !status) return null
  if (!status) return null

  const ftsMissing = status.total_articles > status.fts_indexed
  const embeddingsMissing = status.total_articles > status.embeddings_indexed
  const needsIndexing = ftsMissing || embeddingsMissing
  const noArticles = status.total_articles === 0
  const hasOrphans = status.embeddings_indexed > status.total_articles

  if (!needsIndexing && !showDetails) {
    return (
      <div className="search-index-status compact">
        <button className="status-show-btn" onClick={() => setShowDetails(true)}>
          <span className="status-icon">🔍</span>
          <span className="status-text">
            FTS: {status.fts_indexed}/{status.total_articles} · Embeddings: {status.embeddings_indexed}/{status.total_articles}
          </span>
        </button>
      </div>
    )
  }

  const busyLabel = buildingFts ? 'Building FTS Index...'
    : buildingEmbeddings ? 'Building Embeddings...'
    : cleaning ? 'Cleaning up...'
    : null

  return (
    <div className={`search-index-status ${needsIndexing ? 'warning' : 'info'} ${showDetails ? 'expanded' : ''}`}>
      <div className="status-header">
        <div className="status-left">
          <span className="status-icon">
            {isBusy ? '⏳' : needsIndexing ? '⚠️' : noArticles ? 'ℹ️' : '✅'}
          </span>
          <div className="status-info">
            <div className="status-title">
              {busyLabel || (needsIndexing ? 'Search Index Needs Update' : noArticles ? 'No Articles to Index' : 'Search Index Up to Date')}
            </div>
            <div className="status-details">
              FTS: {status.fts_indexed}/{status.total_articles}
              {' · '}
              Embeddings: {status.embeddings_indexed}/{status.total_articles}
            </div>
          </div>
        </div>

        <div className="status-actions">
          {!isBusy && status.total_articles > 0 && (
            <>
              <div className="status-btn-group">
                <span className="btn-group-label">FTS</span>
                <button
                  className="status-btn primary"
                  onClick={() => handleBuildFts(false)}
                  title="Index new articles into FTS"
                >
                  Build
                </button>
                <button
                  className="status-btn secondary"
                  onClick={() => handleBuildFts(true)}
                  title="Rebuild FTS index from scratch"
                >
                  Rebuild
                </button>
              </div>

              <div className="status-btn-group">
                <span className="btn-group-label">Embeddings</span>
                <button
                  className="status-btn primary"
                  onClick={() => handleBuildEmbeddings(false)}
                  title="Generate embeddings for new articles"
                >
                  Build
                </button>
                <button
                  className="status-btn secondary"
                  onClick={() => handleBuildEmbeddings(true)}
                  title="Regenerate all embeddings from scratch"
                >
                  Rebuild
                </button>
              </div>

              {hasOrphans && (
                <button
                  className="status-btn warning"
                  onClick={handleCleanup}
                  title="Remove embeddings for deleted articles"
                >
                  🗑️ Cleanup
                </button>
              )}
            </>
          )}

          <button
            className="status-btn icon-btn"
            onClick={handleRefresh}
            disabled={isBusy}
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

      {isBusy && (
        <div className="status-progress">
          <div className="progress-bar">
            <div className="progress-fill"></div>
          </div>
          <div className="progress-text">{busyLabel}</div>
        </div>
      )}
    </div>
  )
}

export default SearchIndexStatus
