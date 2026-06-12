import React, { useState } from 'react'
import { useDatabase } from '../hooks/useDatabase'
import './DatabaseDropdown.css'

/**
 * DatabaseDropdown - Compact dropdown selector for the header
 */
const DatabaseDropdown = ({ onDatabaseChange }) => {
  const [isOpen, setIsOpen] = useState(false)
  const [isCreating, setIsCreating] = useState(false)
  const [newDbName, setNewDbName] = useState('')
  const [createError, setCreateError] = useState(null)

  const {
    databases,
    currentDatabase,
    loading,
    switchDatabase,
    createDatabase
  } = useDatabase(onDatabaseChange)

  const handleDatabaseSwitch = async (dbPath) => {
    if (dbPath === currentDatabase) {
      setIsOpen(false)
      return
    }

    const result = await switchDatabase(dbPath)
    if (result.success) {
      setIsOpen(false)
    }
  }

  const handleCreateDatabase = async (e) => {
    e.preventDefault()
    setCreateError(null)

    const name = newDbName.trim()
    if (!name) {
      setCreateError('Enter a name')
      return
    }

    const result = await createDatabase(name, { switchTo: true })
    if (result.success) {
      setNewDbName('')
      setIsCreating(false)
      setIsOpen(false)
    } else {
      setCreateError(result.message)
    }
  }

  const getCurrentDatabaseName = () => {
    if (!currentDatabase) return 'No database'
    return currentDatabase.split(/[\\/]/).pop() || currentDatabase
  }

  return (
    <div className="database-dropdown">
      <button
        className="db-dropdown-trigger"
        onClick={() => setIsOpen(!isOpen)}
        disabled={loading}
      >
        <span className="db-icon">💾</span>
        <span className="db-name">{getCurrentDatabaseName()}</span>
        <span className="db-arrow">{isOpen ? '▴' : '▾'}</span>
      </button>

      {isOpen && (
        <>
          <div className="db-dropdown-overlay" onClick={() => setIsOpen(false)} />
          <div className="db-dropdown-menu">
            {databases.length === 0 ? (
              <div className="db-dropdown-item disabled">No databases found</div>
            ) : (
              databases.map((db) => (
                <button
                  key={db.path}
                  className={`db-dropdown-item ${db.is_current ? 'current' : ''} ${!db.exists ? 'disabled' : ''}`}
                  onClick={() => db.exists && handleDatabaseSwitch(db.path)}
                  disabled={!db.exists}
                >
                  {db.is_current && <span className="db-check">✓</span>}
                  <span className="db-item-name">{db.name}</span>
                  {!db.exists && <span className="db-missing-badge">Missing</span>}
                </button>
              ))
            )}

            <div className="db-dropdown-divider" />

            {isCreating ? (
              <form className="db-create-form" onSubmit={handleCreateDatabase}>
                <input
                  className="db-create-input"
                  type="text"
                  placeholder="new-database"
                  value={newDbName}
                  onChange={(e) => setNewDbName(e.target.value)}
                  autoFocus
                  disabled={loading}
                />
                <div className="db-create-actions">
                  <button
                    type="submit"
                    className="db-create-confirm"
                    disabled={loading || !newDbName.trim()}
                  >
                    Create
                  </button>
                  <button
                    type="button"
                    className="db-create-cancel"
                    onClick={() => {
                      setIsCreating(false)
                      setNewDbName('')
                      setCreateError(null)
                    }}
                    disabled={loading}
                  >
                    Cancel
                  </button>
                </div>
                {createError && <div className="db-create-error">{createError}</div>}
              </form>
            ) : (
              <button
                className="db-dropdown-item db-create-trigger"
                onClick={() => setIsCreating(true)}
                disabled={loading}
              >
                <span className="db-check">＋</span>
                <span className="db-item-name">New database…</span>
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default DatabaseDropdown
