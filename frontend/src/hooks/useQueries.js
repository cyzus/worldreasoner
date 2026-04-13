import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as api from '../api/graphApi'

// Graph queries
export function useGraph(filters) {
  return useQuery({
    queryKey: ['graph', filters],
    queryFn: () => api.fetchGraph(filters),
    staleTime: 1000 * 60 * 5,
  })
}

export function useQuestions(domain = null) {
  return useQuery({
    queryKey: ['questions', domain],
    queryFn: () => api.fetchQuestions(domain),
  })
}

export function usePriceHistory(questionId, interval, includeTurningPoints = false) {
  return useQuery({
    queryKey: ['priceHistory', questionId, interval, includeTurningPoints],
    queryFn: () => api.fetchQuestionPriceHistory(
      questionId,
      interval,
      includeTurningPoints,
      5.0  // min change for turning points
    ),
    enabled: !!questionId,
  })
}

export function useStatistics() {
  return useQuery({
    queryKey: ['statistics'],
    queryFn: () => api.fetchStatistics(),
  })
}

export function useQuestionEvents(questionId) {
  return useQuery({
    queryKey: ['questionEvents', questionId],
    queryFn: () => api.fetchQuestionEvents(questionId),
    enabled: !!questionId,
  })
}

// Polling for jobs
export function useForecastJobs() {
  return useQuery({
    queryKey: ['forecastJobs'],
    queryFn: () => fetch('/api/forecast/jobs').then(r => r.json()),
    refetchInterval: 5000,
    refetchIntervalInBackground: false, // Pause when tab hidden
  })
}

export function usePipelineJobs() {
  return useQuery({
    queryKey: ['pipelineJobs'],
    queryFn: () => fetch('/api/pipelines/jobs').then(r => r.json()),
    refetchInterval: (data) => {
      // Smart polling: faster when jobs running, slower when idle
      const hasActiveJobs = data?.some(j => j.status === 'running')
      return hasActiveJobs ? 5000 : 30000
    },
  })
}
