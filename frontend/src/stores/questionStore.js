import { create } from 'zustand'
import { devtools } from 'zustand/middleware'

export const useQuestionStore = create(
  devtools((set) => ({
    // State
    selectedQuestionId: null,
    priceHistoryData: null,
    loadingPriceHistory: false,
    questionRelatedEvents: [],
    priceHistoryInterval: 'max', // 'max', '1d', '1h', '5m'

    // Question collection preview state (persists across navigation)
    previewQuestions: [],
    previewSourceTab: 'polymarket',
    previewSource: null,

    // Actions
    setSelectedQuestion: (id) => set({ selectedQuestionId: id }),
    setPriceHistoryData: (data) => set({ priceHistoryData: data }),
    setLoadingPriceHistory: (loading) => set({ loadingPriceHistory: loading }),
    setQuestionRelatedEvents: (events) => set({ questionRelatedEvents: events }),
    setPriceHistoryInterval: (interval) => set({ priceHistoryInterval: interval }),
    setPreviewQuestions: (questions) => set({ previewQuestions: questions }),
    setPreviewSourceTab: (tab) => set({ previewSourceTab: tab }),
    setPreviewSource: (source) => set({ previewSource: source }),

    // Clear question-related state
    clearQuestionData: () => set({
      selectedQuestionId: null,
      priceHistoryData: null,
      questionRelatedEvents: [],
      priceHistoryInterval: 'max'
    }),

    clearPreviewData: () => set({
      previewQuestions: [],
      previewSourceTab: 'polymarket',
      previewSource: null
    }),
  }), {
    name: 'question-store'
  })
)
