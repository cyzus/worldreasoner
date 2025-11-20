import React from 'react'
import './ForceControls.css'

const ForceControls = ({ forceSettings, onForceChange }) => {
  const handleChange = (key, value) => {
    onForceChange({ ...forceSettings, [key]: value })
  }

  return (
    <div className="force-controls">
      <div className="force-controls-header">
        <h3>Graph Forces</h3>
      </div>

      <div className="force-control-group">
        <label>
          <span className="control-label">Center Gravity</span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={forceSettings.centerStrength}
            onChange={(e) => handleChange('centerStrength', parseFloat(e.target.value))}
          />
          <span className="control-value">{forceSettings.centerStrength.toFixed(2)}</span>
        </label>
      </div>

      <div className="force-control-group">
        <label>
          <span className="control-label">Node Repulsion</span>
          <input
            type="range"
            min="-500"
            max="-50"
            step="10"
            value={forceSettings.chargeStrength}
            onChange={(e) => handleChange('chargeStrength', parseFloat(e.target.value))}
          />
          <span className="control-value">{Math.abs(forceSettings.chargeStrength)}</span>
        </label>
      </div>

      <div className="force-control-group">
        <label>
          <span className="control-label">Link Strength</span>
          <input
            type="range"
            min="0"
            max="2"
            step="0.1"
            value={forceSettings.linkStrength}
            onChange={(e) => handleChange('linkStrength', parseFloat(e.target.value))}
          />
          <span className="control-value">{forceSettings.linkStrength.toFixed(1)}</span>
        </label>
      </div>

      <div className="force-control-group">
        <label>
          <span className="control-label">Link Distance</span>
          <input
            type="range"
            min="10"
            max="150"
            step="5"
            value={forceSettings.linkDistance}
            onChange={(e) => handleChange('linkDistance', parseFloat(e.target.value))}
          />
          <span className="control-value">{forceSettings.linkDistance}</span>
        </label>
      </div>

      <button
        className="reset-button"
        onClick={() => onForceChange({
          linkDistance: 40,
          linkStrength: 1,
          chargeStrength: -200,
          centerStrength: 0.05
        })}
      >
        Reset to Defaults
      </button>
    </div>
  )
}

export default ForceControls
