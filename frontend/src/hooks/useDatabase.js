import { useState, useEffect, useCallback } from 'react'
import { fetchDatabaseList, switchDatabase as apiSwitchDatabase } from '../api/graphApi'

/**
 * Hook to manage database operations
 */
export const useDatabase = (onDatabaseChange) => {
    const [databases, setDatabases] = useState([])
    const [currentDatabase, setCurrentDatabase] = useState('')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)

    const loadDatabases = useCallback(async () => {
        try {
            setLoading(true)
            setError(null)
            const data = await fetchDatabaseList()
            setDatabases(data.databases)
            setCurrentDatabase(data.current_database)
        } catch (err) {
            console.error('Error loading databases:', err)
            setError('Failed to load database list: ' + err.message)
        } finally {
            setLoading(false)
        }
    }, [])

    // Initial load
    useEffect(() => {
        loadDatabases()
    }, [loadDatabases])

    const switchDatabase = useCallback(async (dbPath) => {
        try {
            setLoading(true)
            setError(null)

            const response = await apiSwitchDatabase(dbPath)

            if (response.success) {
                setCurrentDatabase(response.db_path)

                // Notify callback if provided
                if (onDatabaseChange) {
                    onDatabaseChange(response.db_path)
                }

                // Reload list to update "is_current" flags
                await loadDatabases()
                return { success: true, message: response.message, db_path: response.db_path }
            } else {
                setError(response.message)
                return { success: false, message: response.message }
            }
        } catch (err) {
            console.error('Error switching database:', err)
            setError('Failed to switch database: ' + err.message)
            return { success: false, message: err.message }
        } finally {
            setLoading(false)
        }
    }, [loadDatabases, onDatabaseChange])

    return {
        databases,
        currentDatabase,
        loading,
        error,
        loadDatabases,
        switchDatabase
    }
}
