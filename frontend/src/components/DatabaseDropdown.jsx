import React, { useState, useEffect } from 'react'
import { fetchDatabaseList, switchDatabase } from '../api/graphApi'
import './DatabaseDropdown.css'

/**
 * DatabaseDropdown - Compact dropdown selector for the header
 */
const DatabaseDropdown = ({ onDatabaseChange }) => {
  const [databases, setDatabases] = useState([])
  const [currentDatabase, setCurrentDatabase] = useState('')
  const [loading, setLoading] = useState(false)
  const [isOpen, setIsOpen] = useState(false)

  useEffect(() => {
    loadDatabases()
  }, [])

  const loadDatabases = async () => {
    try {
      setLoading(true)
      const data = await fetchDatabaseList()
      setDatabases(data.databases)
      setCurrentDatabase(data.current_database)
    } catch (err) {
      console.error('Error loading databases:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleDatabaseSwitch = async (dbPath) => {
    if (dbPath === currentDatabase) {
      setIsOpen(false)
      return
    }

    try {
      setLoading(true)
      const response = await switchDatabase(dbPath)

      if (response.success) {
        setCurrentDatabase(response.db_path)

        // Notify parent component to reload data
        if (onDatabaseChange) {
          onDatabaseChange(response.db_path)
        }

        // Reload database list to update status
        await loadDatabases()
        setIsOpen(false)
      }
    } catch (err) {
      console.error('Error switching database:', err)
    } finally {
      setLoading(false)
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
