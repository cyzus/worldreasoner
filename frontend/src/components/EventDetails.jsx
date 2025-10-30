import React from 'react'
import './EventDetails.css'

const EventDetails = ({ node, onClose, onShowNeighborhood }) => {
  if (!node) return null

  const formatDate = (dateString) => {
    if (!dateString) return 'Unknown'
    return new Date(dateString).toLocaleDateString()
  }

  return (
    <div className="event-details">
      <div className="details-header">
        <h3>{node.name}</h3>
        <button className="close-btn" onClick={onClose}>
          ×
        </button>
      </div>

      <div className="details-content">
        <div className="detail-row">
          <span className="label">Type:</span>
          <span className="value">{node.type}</span>
        </div>

        <div className="detail-row">
          <span className="label">Importance:</span>
          <span className="value">{node.properties?.importance?.toFixed(2) || 'N/A'}</span>
        </div>

        {node.properties?.description && (
          <div className="detail-row">
            <span className="label">Description:</span>
            <span className="value">{node.properties.description}</span>
          </div>
        )}

        {node.properties?.occurred_date && (
          <div className="detail-row">
            <span className="label">Occurred:</span>
            <span className="value">{formatDate(node.properties.occurred_date)}</span>
          </div>
        )}

        {node.properties?.predicted_date && (
          <div className="detail-row">
            <span className="label">Predicted:</span>
            <span className="value">{formatDate(node.properties.predicted_date)}</span>
          </div>
        )}

        {node.properties?.event_type && (
          <div className="detail-row">
            <span className="label">Event Type:</span>
            <span className="value">{node.properties.event_type}</span>
          </div>
        )}

        {node.properties?.status && (
          <div className="detail-row">
            <span className="label">Status:</span>
            <span className="value">{node.properties.status}</span>
          </div>
        )}

        <div className="detail-row">
          <span className="label">Causes:</span>
          <span className="value">{node.properties?.num_causes || 0} events</span>
        </div>

        <div className="detail-row">
          <span className="label">Caused by:</span>
          <span className="value">{node.properties?.num_caused_by || 0} events</span>
        </div>

        <div className="button-group">
          <button onClick={() => onShowNeighborhood(node.id, 1)}>
            Show Immediate Links
          </button>
          <button onClick={() => onShowNeighborhood(node.id, 2)}>
            Show 2-Hop Neighborhood
          </button>
        </div>
      </div>
    </div>
  )
}

export default EventDetails
