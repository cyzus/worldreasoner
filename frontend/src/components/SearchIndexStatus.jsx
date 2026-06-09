import React, { useState, useEffect } from 'react'
import { fetchSearchIndexStatus, buildSearchIndex, cleanupOrphanedEmbeddings } from '../api/graphApi'
import './SearchIndexStatus.css'

const SearchIndexStatus = ({ databasePath }) => {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [buildingFts, setBuildingFts] = useState(false)
  const [buildingEmbeddings, setBuildingEmbeddings] = useState(false)
  const [cleaning, setCleaning] = useState(false)
  const [error, setError] = useState(null)

  const isBusy = buildingFts || buildingEmbeddings || cleaning

  useEffect(() => {
    loadStatus()
  }, [databasePath])

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

  const busyLabel = buildingFts ? 'Building FTS…'
    : buildingEmbeddings ? 'Building Embeddings…'
    : cleaning ? 'Cleaning up…'
    : null

  const ftsMissing = status && status.total_articles > status.fts_indexed
  const embeddingsMissing = status && status.total_articles > status.embeddings_indexed
  const needsIndexing = ftsMissing || embeddingsMissing
  const hasOrphans = status && status.embeddings_indexed > status.total_articles

  return (
    <div className="search-index-card">
      <div className="search-index-card-header">
        <span className="search-index-card-title">
          {isBusy
            ? busyLabel
            : needsIndexing
            ? '⚠ Search Index'
            : '✓ Search Index'}
        </span>
        {status && (
          <span className="search-index-card-counts">
            FTS {status.fts_indexed}/{status.total_articles} · Emb {status.embeddings_indexed}/{status.total_articles}
          </span>
        )}
        <button
          className="search-index-refresh-btn"
          onClick={loadStatus}
          disabled={isBusy || loading}
          title="Refresh"
        >
          🔄
        </button>
      </div>

      {error && (
        <div className="search-index-error">{error}</div>
      )}

      {isBusy && (
        <div className="search-index-progress">
          <div className="search-index-progress-fill" />
        </div>
      )}

      {!isBusy && status && status.total_articles > 0 && (
        <div className="search-index-actions">
          <div className="search-index-btn-group">
            <span className="search-index-btn-label">FTS</span>
            <button className="search-index-btn primary" onClick={() => handleBuildFts(false)} title="Index new articles">Build</button>
            <button className="search-index-btn secondary" onClick={() => handleBuildFts(true)} title="Rebuild from scratch">Rebuild</button>
          </div>
          <div className="search-index-btn-group">
            <span className="search-index-btn-label">Embeddings</span>
            <button className="search-index-btn primary" onClick={() => handleBuildEmbeddings(false)} title="Generate embeddings for new articles">Build</button>
            <button className="search-index-btn secondary" onClick={() => handleBuildEmbeddings(true)} title="Regenerate all embeddings">Rebuild</button>
          </div>
          {hasOrphans && (
            <button className="search-index-btn warning" onClick={handleCleanup} title="Remove embeddings for deleted articles">🗑 Cleanup</button>
          )}
        </div>
      )}
    </div>
  )
}

export default SearchIndexStatus
