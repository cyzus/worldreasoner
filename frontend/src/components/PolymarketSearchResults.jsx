import React from 'react'
import './PolymarketSearchResults.css'

function PolymarketSearchResults({ results, page, onPrev, onNext, loading }) {
  const events = results?.events || []
  const canPrev = page > 1
  // We don't have total pages from API; enable Next if we got a full page
  const canNext = events.length > 0

  const formatCurrency = (value) => {
    if (!value) return '$0'
    const num = parseFloat(value)
    if (isNaN(num)) return '$0'
    if (num >= 1e9) return `$${(num / 1e9).toFixed(2)}B`
    if (num >= 1e6) return `$${(num / 1e6).toFixed(2)}M`
    if (num >= 1e3) return `$${(num / 1e3).toFixed(2)}K`
    return `$${num.toFixed(0)}`
  }

  return (
    <div className="polymarket-results">
      <div className="results-header">
        <h4><span role="img" aria-label="search">🔎</span> Polymarket Event Results</h4>
        <div className="pager">
          <button onClick={onPrev} disabled={loading || !canPrev}>◀ Prev</button>
          <span>Page {page}</span>
          <button onClick={onNext} disabled={loading || !canNext}>Next ▶</button>
        </div>
      </div>

      {loading && (
        <div className="loading-state">
          Fetching markets...
        </div>
      )}

      {!loading && events.length === 0 && (
        <div className="empty-state">
          No events found for this query.
        </div>
      )}

      <div className="events-grid">
        {events.map((evt) => {
          const title = evt.title || evt.name || evt.question || 'Untitled event'
          const volume = evt.volume || evt.volume24hr || 0
          const isActive = evt.active || !evt.closed
          const imageUrl = evt.image || evt.icon

          return (
            <a
              key={evt.id}
              className="event-card"
              href={`https://polymarket.com/event/${evt.slug || evt.id}`}
              target="_blank"
              rel="noreferrer"
            >
              <div className="event-image-container">
                {imageUrl ? (
                  <img src={imageUrl} alt={title} className="event-image" loading="lazy" />
                ) : (
                  <div className="event-image-placeholder">📊</div>
                )}
                <div className={`event-status ${isActive ? 'active' : 'closed'}`}>
                  {isActive ? 'Active' : 'Closed'}
                </div>
              </div>

              <div className="event-content">
                <h3 className="event-title" title={title}>
                  {title}
                </h3>

                <div className="event-meta">
                  <div className="event-volume">
                    <span className="volume-label">Volume</span>
                    <span className="volume-value">{formatCurrency(volume)}</span>
                  </div>
                </div>
              </div>
            </a>
          )
        })}
      </div>
    </div>
  )
}

export default PolymarketSearchResults
