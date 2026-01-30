import { create } from 'zustand'
import { devtools } from 'zustand/middleware'

export const useGraphStore = create(
  devtools((set, get) => ({
    // State
    fullGraphData: { nodes: [], links: [] },
    graphData: { nodes: [], links: [] },
    selectedNode: null,
    centerNode: null,
    filters: {
      nodeTypes: [],
      maxNodes: 3000,  // Increased from 1000 to include more events (backend allows up to 10000)
      maxEdges: 8000,  // Increased proportionally (backend allows up to 20000)
      minEdgeWeight: 0,
    },
    includeOutcomes: false, // Show outcome impact edges
    timeFilter: null, // { start: Date, end: Date }
    loading: false,
    error: null,

    // Actions
    setFullGraphData: (data) => set({ fullGraphData: data }),
    setGraphData: (data) => set({ graphData: data }),
    setSelectedNode: (node) => set({
      selectedNode: node,
      centerNode: node
    }),
    clearSelectedNode: () => set({ selectedNode: null }),
    setFilters: (filters) => set({ filters }),
    setIncludeOutcomes: (includeOutcomes) => set({ includeOutcomes }),
    setTimeFilter: (timeFilter) => set({ timeFilter }),
    setLoading: (loading) => set({ loading }),
    setError: (error) => set({ error }),

    // Computed selectors
    getNodeById: (id) => {
      const { graphData } = get()
      return graphData.nodes.find(n => n.id === id)
    },
  }), {
    name: 'graph-store'
  })
)
