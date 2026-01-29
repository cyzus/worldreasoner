import { useState, useEffect, useCallback } from 'react'
import { fetchSatisfaction, fetchForecastReadiness, fetchEvidenceNeeds, fetchModelStats } from '../api/monitorApi'

/**
 * Hook to monitor question evidence and forecast readiness.
 * @param {string} questionId - Optional question ID for specific question status
 */
export const useQuestionMonitor = (questionId) => {
    const [satisfaction, setSatisfaction] = useState(null)
    const [readiness, setReadiness] = useState(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)

    // Fetch status when question changes
    useEffect(() => {
        if (!questionId) {
            setSatisfaction(null)
            setReadiness(null)
            setError(null)
            return
        }

        setLoading(true)
        setError(null)

        Promise.all([
            fetchSatisfaction(questionId),
            fetchForecastReadiness(questionId)
        ])
            .then(([sat, ready]) => {
                setSatisfaction(sat)
                setReadiness(ready)
            })
            .catch(err => {
                console.error('Error fetching question status:', err)
                setError(err.message)
            })
            .finally(() => {
                setLoading(false)
            })
    }, [questionId])

    // Refresh function
    const refresh = useCallback(() => {
        if (!questionId) return

        setLoading(true)
        setError(null)

        Promise.all([
            fetchSatisfaction(questionId),
            fetchForecastReadiness(questionId)
        ])
            .then(([sat, ready]) => {
                setSatisfaction(sat)
                setReadiness(ready)
            })
            .catch(err => {
                setError(err.message)
            })
            .finally(() => {
                setLoading(false)
            })
    }, [questionId])

    return {
        satisfaction,
        readiness,
        loading,
        error,
        refresh
    }
}

/**
 * Hook to fetch questions needing evidence collection.
 * @param {Object} filters - Optional filters
 */
export const useEvidenceNeeds = (filters = {}) => {
    const [questions, setQuestions] = useState([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)

    useEffect(() => {
        setLoading(true)
        setError(null)

        fetchEvidenceNeeds(filters)
            .then(data => {
                setQuestions(data.questions || [])
            })
            .catch(err => {
                console.error('Error fetching evidence needs:', err)
                setError(err.message)
            })
            .finally(() => {
                setLoading(false)
            })
    }, [filters.min_quality, filters.domain, filters.limit])

    return { data: questions, loading, error, refetch: () => fetchEvidenceNeeds(filters).then(d => setQuestions(d.questions || [])) }
}

/**
 * Hook to fetch LLM model usage statistics.
 * @param {string} modelName - Optional filter to specific model
 */
export const useModelStats = (modelName = null) => {
    const [stats, setStats] = useState([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)

    useEffect(() => {
        setLoading(true)
        setError(null)

        fetchModelStats(modelName)
            .then(data => {
                setStats(data.models || [])
            })
            .catch(err => {
                console.error('Error fetching model stats:', err)
                setError(err.message)
            })
            .finally(() => {
                setLoading(false)
            })
    }, [modelName])

    return { data: stats, loading, error }
}

/**
 * Hook to fetch forecast readiness for a specific question.
 * @param {string} questionId 
 */
export const useForecastReadiness = (questionId) => {
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)

    useEffect(() => {
        if (!questionId) {
            setData(null)
            return
        }

        setLoading(true)
        setError(null)

        fetchForecastReadiness(questionId)
            .then(result => setData(result))
            .catch(err => {
                console.error('Error fetching forecast readiness:', err)
                setError(err.message)
            })
            .finally(() => setLoading(false))
    }, [questionId])

    return { data, loading, error }
}

/**
 * Hook to fetch satisfaction status for a specific question.
 * @param {string} questionId 
 */
export const useSatisfaction = (questionId) => {
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)

    useEffect(() => {
        if (!questionId) {
            setData(null)
            return
        }

        setLoading(true)
        setError(null)

        fetchSatisfaction(questionId)
            .then(result => setData(result))
            .catch(err => {
                console.error('Error fetching satisfaction:', err)
                setError(err.message)
            })
            .finally(() => setLoading(false))
    }, [questionId])

    return { data, loading, error }
}
