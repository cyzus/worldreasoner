import React, { useState, useEffect } from 'react'
import { fetchDatabaseList, switchDatabase } from '../api/graphApi'
import './DatabaseSelector.css'

const DatabaseSelector = ({ onDatabaseChange }) => {
  const [databases, setDatabases] = useState([])
  const [currentDatabase, setCurrentDatabase] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [message, setMessage] = useState(null)

  useEffect(() => {
    loadDatabases()
  }, [])

  const loadDatabases = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await fetchDatabaseList()
      setDatabases(data.databases)
      setCurrentDatabase(data.current_database)
    } catch (err) {
      setError('Failed to load database list: ' + err.message)
      console.error('Error loading databases:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleDatabaseSwitch = async (dbPath) => {
    try {
      setLoading(true)
      setError(null)
      setMessage(null)

      const response = await switchDatabase(dbPath)

      if (response.success) {
        setCurrentDatabase(response.db_path)
        setMessage(response.message)

        // Notify parent component to reload data
        if (onDatabaseChange) {
          onDatabaseChange(response.db_path)
        }

        // Reload database list to update status
        await loadDatabases()
      } else {
        setError(response.message)
      }
    } catch (err) {
      setError('Failed to switch database: ' + err.message)
      console.error('Error switching database:', err)
    } finally {
      setLoading(false)
    }
  }

  const formatFileSize = (bytes) => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
  }

  return (
    <div className="database-selector">
      <div className="selector-header">
        <h3>Database</h3>
        <button
          className="refresh-btn"
          onClick={loadDatabases}
          disabled={loading}
          title="Refresh database list"
        >
          &#8635;
        </button>
      </div>

      {error && <div className="error-message">{error}</div>}
      {message && <div className="success-message">{message}</div>}

      {loading ? (
        <div className="loading-state">Loading...</div>
      ) : (
        <div className="database-list">
          {databases.length === 0 ? (
            <div className="no-databases">No .db files found</div>
          ) : (
            databases.map((db) => (
              <div
                key={db.path}
                className={`database-item ${db.is_current ? 'current' : ''} ${!db.exists ? 'missing' : ''}`}
                onClick={() => !db.is_current && db.exists && handleDatabaseSwitch(db.path)}
                style={{ cursor: db.is_current || !db.exists ? 'default' : 'pointer' }}
              >
                <div className="db-name">
                  {db.is_current && <span className="current-badge">&#10003;</span>}
                  {db.name}
                </div>
                <div className="db-info">
                  {db.exists ? (
                    <span className="db-size">{formatFileSize(db.size_bytes)}</span>
                  ) : (
                    <span className="db-missing">Missing</span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      <div className="current-db-footer">
        <strong>Current:</strong> {currentDatabase || 'None'}
      </div>
    </div>
  )
}

export default DatabaseSelector
