import React from 'react'

function PolymarketSearchResults({ results, page, onPrev, onNext, loading }) {
  const events = results?.events || []
  const canPrev = page > 1
  // We don't have total pages from API; enable Next if we got a full page
  const canNext = events.length > 0

  return (
    <div className="polymarket-results">
      <div className="results-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h4 style={{ margin: 0 }}>🔎 Search Results</h4>
        <div className="pager" style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button onClick={onPrev} disabled={loading || !canPrev}>◀ Prev</button>
          <span>Page {page}</span>
          <button onClick={onNext} disabled={loading || !canNext}>Next ▶</button>
        </div>
      </div>

      {loading && <div style={{ marginTop: 8 }}>Loading…</div>}

      {!loading && events.length === 0 && (
        <div style={{ marginTop: 8 }}>No events found.</div>
      )}

      <ul style={{ marginTop: 8, paddingLeft: 16 }}>
        {events.map((evt) => (
          <li key={evt.id} style={{ marginBottom: 6 }}>
            <a
              href={`https://polymarket.com/event/${evt.slug || evt.id}`}
              target="_blank"
              rel="noreferrer"
            >
              {evt.title || evt.name || evt.question || 'Untitled event'}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default PolymarketSearchResults
