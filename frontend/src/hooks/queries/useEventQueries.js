import { useQuery } from '@tanstack/react-query'
import {
    fetchEventArticles,
    fetchEventQuestions,
    fetchEventImpacts,
    fetchOutcomeImpacts,
    fetchOutcomeTrajectory
} from '../../api/graphApi'

export const useEventArticles = (eventId, enabled = true) => {
    return useQuery({
        queryKey: ['eventArticles', eventId],
        queryFn: () => fetchEventArticles(eventId),
        enabled: !!eventId && enabled,
        staleTime: 5 * 60 * 1000 // 5 minutes
    })
}

export const useEventQuestions = (eventId, enabled = true) => {
    return useQuery({
        queryKey: ['eventQuestions', eventId],
        queryFn: () => fetchEventQuestions(eventId),
        enabled: !!eventId && enabled,
        staleTime: 5 * 60 * 1000
    })
}

export const useEventImpacts = (eventId, enabled = true) => {
    return useQuery({
        queryKey: ['eventImpacts', eventId],
        queryFn: () => fetchEventImpacts(eventId),
        enabled: !!eventId && enabled,
        staleTime: 5 * 60 * 1000
    })
}

export const useOutcomeTrajectory = (outcomeId, enabled = true) => {
    return useQuery({
        queryKey: ['outcomeTrajectory', outcomeId],
        queryFn: () => fetchOutcomeTrajectory(outcomeId),
        enabled: !!outcomeId && enabled,
        staleTime: 5 * 60 * 1000
    })
}

export const useOutcomeImpacts = (outcomeId, minConfidence = null, direction = null, enabled = true) => {
    return useQuery({
        queryKey: ['outcomeImpacts', outcomeId, minConfidence, direction],
        queryFn: () => fetchOutcomeImpacts(outcomeId, minConfidence > 0 ? minConfidence : null, direction),
        enabled: !!outcomeId && enabled,
        staleTime: 5 * 60 * 1000
    })
}
