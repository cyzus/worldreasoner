import { useState, useEffect, useCallback } from 'react'
import { fetchForecasts, fetchForecastGraph } from '../api/graphApi'

/**
 * Hook to manage forecast data and reasoning graphs
 */
export const useForecasts = (selectedQuestionId) => {
    const [forecasts, setForecasts] = useState([])
    const [selectedForecastId, setSelectedForecastId] = useState(null)
    const [forecastGraphData, setForecastGraphData] = useState(null)
    const [loadingForecastGraph, setLoadingForecastGraph] = useState(false)
    const [loadingForecasts, setLoadingForecasts] = useState(false)
    const [forecastsError, setForecastsError] = useState(null)
    const [graphView, setGraphView] = useState('evidence') // 'evidence', 'forecast', 'both'

    // Fetch forecasts for the selected question
    useEffect(() => {
        if (!selectedQuestionId) {
            setForecasts([])
            setSelectedForecastId(null)
            setForecastGraphData(null)
            setGraphView('evidence')
            setForecastsError(null)
            return
        }

        // Fetch forecasts for this question
        setLoadingForecasts(true)
        setForecastsError(null)

        fetchForecasts(selectedQuestionId)
            .then(data => {
                setForecasts(data.forecasts || [])
                // Auto-select first forecast if available
                if (data.forecasts && data.forecasts.length > 0) {
                    setSelectedForecastId(data.forecasts[0].id)
                } else {
                    setSelectedForecastId(null)
                    setForecastGraphData(null)
                }
            })
            .catch(err => {
                console.error('Error fetching forecasts:', err)
                setForecastsError(err.message)
                setForecasts([])
            })
            .finally(() => {
                setLoadingForecasts(false)
            })
    }, [selectedQuestionId])

    // Fetch forecast graph data when forecast is selected
    useEffect(() => {
        if (!selectedForecastId) {
            setForecastGraphData(null)
            return
        }

        setLoadingForecastGraph(true)
        fetchForecastGraph(selectedForecastId)
            .then(data => {
                if (data) {
                    setForecastGraphData(data)
                }
            })
            .catch(err => {
                // Handle 404 gracefully (no graph for this forecast)
                if (err.response && err.response.status === 404) {
                    setForecastGraphData(null)
                    return
                }
                console.error('Error fetching forecast graph:', err)
                setForecastGraphData(null)
            })
            .finally(() => {
                setLoadingForecastGraph(false)
            })
    }, [selectedForecastId])

    return {
        forecasts,
        selectedForecastId,
        setSelectedForecastId,
        forecastGraphData,
        loadingForecastGraph,
        loadingForecasts,
        forecastsError,
        graphView,
        setGraphView
    }
}
