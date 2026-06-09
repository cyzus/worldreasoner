import { create } from 'zustand'
import { devtools } from 'zustand/middleware'

export const useUIStore = create(
  devtools((set) => ({
    // State
    leftPanelTab: 'questions', // 'questions' | 'data' | 'benchmark'
    currentDatabasePath: null,

    // Actions
    setLeftPanelTab: (tab) => set({ leftPanelTab: tab }),
    setCurrentDatabasePath: (path) => set({ currentDatabasePath: path }),
  }), {
    name: 'ui-store'
  })
)
