export const GraphStyles = {
    // Node Colors (Domain based or Type based)
    nodeColors: {
        finance: '#4CAF50',
        politics: '#2196F3', // Blue
        tech: '#9C27B0',    // Purple
        health: '#f44336',  // Red
        climate: '#00BCD4', // Cyan
        business: '#FF9800', // Orange
        general: '#607D8B', // Blue Grey
        default: '#9E9E9E',
        target: '#FFD700',   // Gold for target
        outcome: '#FFC107'   // Amber for outcome
    },

    // Link Colors (Relation based)
    // Positive impact relations (lead toward target)
    linkColors: {
        causes: '#4CAF50',      // Green (neutral-positive)
        enables: '#2196F3',     // Blue (enabling)
        amplifies: '#22c55e',   // Bright green (increases intensity)
        triggers: '#10b981',    // Emerald (immediate onset)
        // Negative impact relations (lead away from target)
        prevents: '#ef4444',    // Red (blocks)
        inhibits: '#f97316',    // Orange-red (reduces likelihood)
        // Neutral relations
        correlates_with: '#8b5cf6', // Purple (correlation)
        correlates: '#8b5cf6',      // Alias for correlates_with
        conditional: '#ec4899', // Pink (conditional)
        // Outcome impact relations
        impact_positive: '#22c55e', // Bright green - makes outcome more likely
        impact_negative: '#ef4444', // Bright red - makes outcome less likely
        impact_neutral: '#94a3b8',  // Slate gray - no clear directional impact
        impact_mixed: '#a855f7',    // Purple - complex/contradictory effects
        default: '#94a3b8'      // Slate grey
    },

    // Node Sizes
    nodeSize: {
        default: 5,
        target: 8,
        outcome: 6,
        hover: 7
    },

    // Fonts
    font: {
        family: "'Inter', 'Roboto', sans-serif",
        size: {
            default: 10,
            target: 12,
            outcome: 11
        },
        weight: {
            default: '500',
            bold: '700'
        },
        color: {
            primary: '#333333',
            secondary: '#666666'
        }
    }
};
