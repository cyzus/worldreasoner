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
    linkColors: {
        causes: '#4CAF50',      // Green
        enables: '#2196F3',     // Blue
        prevents: '#f44336',    // Red
        correlates_with: '#FF9800', // Orange
        conditional: '#9C27B0', // Purple
        default: '#BDBDBD'      // Grey
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
