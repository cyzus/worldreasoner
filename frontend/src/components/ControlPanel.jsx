import React, { useState, useEffect, useRef } from 'react'
import './ControlPanel.css'

const ControlPanel = ({ filters, onFilterChange, onRefresh, loading, forceSettings, onForceChange }) => {
  const [localFilters, setLocalFilters] = useState(filters)
  // Debounce filter changes
  useEffect(() => {
    const timer = setTimeout(() => {
      onFilterChange(localFilters)
    }, 500)
    return () => clearTimeout(timer)
  }, [localFilters, onFilterChange])




  const handleResetForces = () => {
    if (onForceChange) {
      onForceChange({
        linkDistance: 40,
        linkStrength: 1,
        chargeStrength: -200,
        centerStrength: 0.05
      })
    }
  }

  const handleForceChange = (key, value) => {
    if (onForceChange && forceSettings) {
      onForceChange({ ...forceSettings, [key]: value })
    }
  }



  return (
    <div className="control-panel-wrapper">
      <div className="panel-content">

        {/* Graph Filters Section */}
        <div className="section-card">
          <div className="section-card-header">
            Graph Filters
          </div>
          <div className="section-card-body">
            <div className="filter-section">
              <label>Max Nodes: {localFilters.maxNodes}</label>
              <input
                type="range"
                min="10"
                max="1000"
                step="10"
                value={localFilters.maxNodes}
                onChange={(e) =>
                  setLocalFilters({ ...localFilters, maxNodes: parseInt(e.target.value) })
                }
              />
            </div>

            <div className="filter-section">
              <label>Max Edges: {localFilters.maxEdges}</label>
              <input
                type="range"
                min="10"
                max="5000"
                step="50"
                value={localFilters.maxEdges}
                onChange={(e) =>
                  setLocalFilters({ ...localFilters, maxEdges: parseInt(e.target.value) })
                }
              />
            </div>

            <div className="filter-section">
              <label>Min Edge Weight: {localFilters.minEdgeWeight.toFixed(2)}</label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={localFilters.minEdgeWeight}
                onChange={(e) =>
                  setLocalFilters({ ...localFilters, minEdgeWeight: parseFloat(e.target.value) })
                }
              />
            </div>
          </div>
        </div>

        {/* Graph Force Controls */}
        {forceSettings && onForceChange && (
          <div className="section-card">
            <div className="section-card-header">
              Graph Forces
            </div>
            <div className="section-card-body">
              <div className="filter-section">
                <label>Center Gravity: {forceSettings.centerStrength.toFixed(2)}</label>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  value={forceSettings.centerStrength}
                  onChange={(e) => handleForceChange('centerStrength', parseFloat(e.target.value))}
                />
              </div>

              <div className="filter-section">
                <label>Node Repulsion: {Math.abs(forceSettings.chargeStrength)}</label>
                <input
                  type="range"
                  min="-500"
                  max="-50"
                  step="10"
                  value={forceSettings.chargeStrength}
                  onChange={(e) => handleForceChange('chargeStrength', parseFloat(e.target.value))}
                />
              </div>

              <div className="filter-section">
                <label>Link Strength: {forceSettings.linkStrength.toFixed(1)}</label>
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.1"
                  value={forceSettings.linkStrength}
                  onChange={(e) => handleForceChange('linkStrength', parseFloat(e.target.value))}
                />
              </div>

              <div className="filter-section">
                <label>Link Distance: {forceSettings.linkDistance}</label>
                <input
                  type="range"
                  min="10"
                  max="150"
                  step="5"
                  value={forceSettings.linkDistance}
                  onChange={(e) => handleForceChange('linkDistance', parseFloat(e.target.value))}
                />
              </div>
            </div>
          </div>
        )}

        <div className="button-group">
          {forceSettings && onForceChange && (
            <button onClick={handleResetForces} disabled={loading} className="secondary-btn">
              Reset Forces
            </button>
          )}
          <button onClick={onRefresh} disabled={loading} className="primary-btn">
            Refresh Data
          </button>
        </div>
      </div>
    </div>
  )
}

export default ControlPanel
