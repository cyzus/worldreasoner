import { useQuery } from '@tanstack/react-query'
import {
    fetchQuestionArticles,
    fetchForecastGraph,
    fetchQuestionPriceHistory
} from '../../api/graphApi'

export const useQuestionPriceHistory = (questionId, enabled = true) => {
    return useQuery({
        queryKey: ['questionPriceHistory', questionId],
        queryFn: () => fetchQuestionPriceHistory(questionId, 'max', false),
        enabled: !!questionId && enabled,
        staleTime: 10 * 60 * 1000
    })
}

export const useQuestionArticles = (questionId, enabled = true) => {
    return useQuery({
        queryKey: ['questionArticles', questionId],
        queryFn: () => fetchQuestionArticles(questionId),
        enabled: !!questionId && enabled,
        staleTime: 5 * 60 * 1000 // 5 minutes
    })
}

export const useForecastGraph = (forecastId, enabled = true) => {
    return useQuery({
        queryKey: ['forecastGraph', forecastId],
        queryFn: () => fetchForecastGraph(forecastId),
        enabled: !!forecastId && enabled,
        staleTime: 5 * 60 * 1000 // 5 minutes
    })
}
