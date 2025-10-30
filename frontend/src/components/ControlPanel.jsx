import React, { useState } from 'react'
import './ControlPanel.css'

const ControlPanel = ({ filters, onFilterChange, onRefresh, loading }) => {
  const [localFilters, setLocalFilters] = useState(filters)
  const [isExpanded, setIsExpanded] = useState(true)

  const handleApply = () => {
    onFilterChange(localFilters)
  }

  const handleReset = () => {
    const defaultFilters = {
      nodeTypes: [],
      maxNodes: 100,
      maxEdges: 500,
      minEdgeWeight: 0,
    }
    setLocalFilters(defaultFilters)
    onFilterChange(defaultFilters)
  }

  return (
    <div className={`control-panel ${isExpanded ? 'expanded' : 'collapsed'}`}>
      <div className="panel-header">
        <h3>Controls</h3>
        <button
          className="toggle-btn"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          {isExpanded ? '◀' : '▶'}
        </button>
      </div>

      {isExpanded && (
        <div className="panel-content">
          <div className="filter-section">
            <label>Node Types</label>
            <select
              multiple
              value={localFilters.nodeTypes}
              onChange={(e) => {
                const selected = Array.from(e.target.selectedOptions, option => option.value)
                setLocalFilters({ ...localFilters, nodeTypes: selected })
              }}
            >
              <option value="politics">Politics</option>
              <option value="economics">Economics</option>
              <option value="technology">Technology</option>
              <option value="science">Science</option>
              <option value="climate">Climate</option>
              <option value="health">Health</option>
            </select>
            <small>Hold Ctrl/Cmd to select multiple</small>
          </div>

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

          <div className="button-group">
            <button onClick={handleApply} disabled={loading}>
              Apply Filters
            </button>
            <button onClick={handleReset} disabled={loading}>
              Reset
            </button>
            <button onClick={onRefresh} disabled={loading}>
              Refresh
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default ControlPanel
