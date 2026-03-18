import { useQuery } from '@tanstack/react-query'
import { fetchForecasts, fetchForecastGraph } from '../../api/graphApi'

export const useQuestionForecasts = (questionId, enabled = true) => {
    return useQuery({
        queryKey: ['questionForecasts', questionId],
        queryFn: () => fetchForecasts(questionId).then(d => d.forecasts || []),
        enabled: !!questionId && enabled,
        staleTime: 2 * 60 * 1000,
    })
}

export const useForecastGraph = (forecastId, enabled = true) => {
    return useQuery({
        queryKey: ['forecastGraph', forecastId],
        queryFn: () => fetchForecastGraph(forecastId),
        enabled: !!forecastId && enabled,
        staleTime: 5 * 60 * 1000,
    })
}
