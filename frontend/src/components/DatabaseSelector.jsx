import React, { useState } from 'react'
import { useDatabase } from '../hooks/useDatabase'
import './DatabaseSelector.css'

const DatabaseSelector = ({ onDatabaseChange }) => {
  const [message, setMessage] = useState(null)
  const [newDbName, setNewDbName] = useState('')
  const [createError, setCreateError] = useState(null)

  const {
    databases,
    currentDatabase,
    loading,
    error,
    loadDatabases,
    switchDatabase,
    createDatabase
  } = useDatabase(onDatabaseChange)

  const handleDatabaseSwitch = async (dbPath) => {
    setMessage(null)
    const result = await switchDatabase(dbPath)

    if (result.success) {
      setMessage(result.message)
    }
  }

  const handleCreateDatabase = async (e) => {
    e.preventDefault()
    setMessage(null)
    setCreateError(null)

    const name = newDbName.trim()
    if (!name) {
      setCreateError('Enter a database name')
      return
    }

    const result = await createDatabase(name, { switchTo: true })
    if (result.success) {
      setNewDbName('')
      setMessage(result.message)
    } else {
      setCreateError(result.message)
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

      {loading && databases.length === 0 ? (
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

      <form className="create-db-form" onSubmit={handleCreateDatabase}>
        <input
          className="create-db-input"
          type="text"
          placeholder="new-database"
          value={newDbName}
          onChange={(e) => setNewDbName(e.target.value)}
          disabled={loading}
        />
        <button
          type="submit"
          className="create-db-btn"
          disabled={loading || !newDbName.trim()}
        >
          Create
        </button>
      </form>
      {createError && <div className="error-message">{createError}</div>}

      <div className="current-db-footer">
        <strong>Current:</strong> {currentDatabase || 'None'}
      </div>
    </div>
  )
}

export default DatabaseSelector
