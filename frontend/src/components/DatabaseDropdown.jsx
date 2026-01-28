import React, { useState } from 'react'
import { useDatabase } from '../hooks/useDatabase'
import './DatabaseDropdown.css'

/**
 * DatabaseDropdown - Compact dropdown selector for the header
 */
const DatabaseDropdown = ({ onDatabaseChange }) => {
  const [isOpen, setIsOpen] = useState(false)

  const {
    databases,
    currentDatabase,
    loading,
    switchDatabase
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
          </div>
        </>
      )}
    </div>
  )
}

export default DatabaseDropdown
