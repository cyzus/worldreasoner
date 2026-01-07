import React, { useMemo } from 'react'
import './QuestionStatistics.css'

function QuestionStatistics({ questions }) {
  const stats = useMemo(() => {
    if (!questions || questions.length === 0) return null

    const total = questions.length

    // Domain stats
    const domains = {}
    questions.forEach(q => {
      const domain = q.domain || 'unknown'
      domains[domain] = (domains[domain] || 0) + 1
    })

    // Top 3 domains
    const topDomains = Object.entries(domains)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([name, count]) => ({
        name,
        count,
        percent: (count / total) * 100
      }))

    // Type stats
    const types = {}
    questions.forEach(q => {
      const type = q.question_type || 'unknown'
      types[type] = (types[type] || 0) + 1
    })

    const topTypes = Object.entries(types)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([name, count]) => ({
        name,
        count,
        percent: (count / total) * 100
      }))

    // Time Horizon (based on resolution date if available)
    const now = new Date()
    const horizons = {
      'Past': 0,
      'Short (< 1 mo)': 0,
      'Medium (1-6 mo)': 0,
      'Long (> 6 mo)': 0,
      'Unknown': 0
    }

    questions.forEach(q => {
      // Use estimated_start_time if available, otherwise fallback to now?
      // User says: resolution date - estimated start date
      if (!q.resolution_date || !q.estimated_start_time) {
        horizons['Unknown']++
        return
      }

      const resDate = new Date(q.resolution_date)
      const startDate = new Date(q.estimated_start_time)

      if (isNaN(resDate.getTime()) || isNaN(startDate.getTime())) {
        horizons['Unknown']++
        return
      }

      const diffTime = resDate - startDate
      const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))

      if (diffDays < 0) {
        // Start date is after resolution date? Or resolution is in past relative to start?
        // Usually this means it's already resolved or invalid data
        // For "Time Horizon", usually we mean the duration of the question.
        // If diffDays is negative, it's weird. Let's assume Past logic doesn't apply the same way.
        // Or maybe "Past" means resolved in the past relative to now?
        // The user asked for "resolution date - estimated start date". This is the *duration* or *length* of the question.
        horizons['Unknown']++
      } else if (diffDays <= 30) {
        horizons['Short (< 1 mo)']++
      } else if (diffDays <= 180) {
        horizons['Medium (1-6 mo)']++
      } else {
        horizons['Long (> 6 mo)']++
      }
    })

    const topHorizons = Object.entries(horizons)
      .filter(([_, count]) => count > 0)
      .sort((a, b) => b[1] - a[1]) // Sort by count desc
      // Custom sort order for labels could be applied here if needed, but count is fine for now
      .slice(0, 4)
      .map(([name, count]) => ({
        name,
        count,
        percent: (count / total) * 100
      }))

    return {
      domains: topDomains,
      types: topTypes,
      horizons: topHorizons,
      total
    }
  }, [questions])

  if (!stats) return null

  return (
    <div className="question-statistics-panel">
      {/* Domain Stats */}
      <div className="stat-card">
        <h4>Domains</h4>
        {stats.domains.length > 0 ? (
          stats.domains.map(item => (
            <div key={item.name} className="stat-item">
              <div className="stat-row">
                <span className="stat-label">{item.name}</span>
                <span className="stat-value">{item.count}</span>
              </div>
              <div className="stat-bar-container">
                <div
                  className="stat-bar"
                  style={{ width: `${item.percent}%`, backgroundColor: '#4dabf7' }}
                ></div>
              </div>
            </div>
          ))
        ) : (
          <div className="stat-empty">No domain data</div>
        )}
      </div>

      {/* Type Stats */}
      <div className="stat-card">
        <h4>Question Types</h4>
        {stats.types.length > 0 ? (
          stats.types.map(item => (
            <div key={item.name} className="stat-item">
              <div className="stat-row">
                <span className="stat-label">{item.name}</span>
                <span className="stat-value">{item.count}</span>
              </div>
              <div className="stat-bar-container">
                <div
                  className="stat-bar"
                  style={{ width: `${item.percent}%`, backgroundColor: '#51cf66' }}
                ></div>
              </div>
            </div>
          ))
        ) : (
          <div className="stat-empty">No type data</div>
        )}
      </div>

      {/* Horizon Stats */}
      <div className="stat-card">
        <h4>Time Horizon</h4>
        {stats.horizons.length > 0 ? (
          stats.horizons.map(item => (
            <div key={item.name} className="stat-item">
              <div className="stat-row">
                <span className="stat-label">{item.name}</span>
                <span className="stat-value">{item.count}</span>
              </div>
              <div className="stat-bar-container">
                <div
                  className="stat-bar"
                  style={{ width: `${item.percent}%`, backgroundColor: '#ff922b' }}
                ></div>
              </div>
            </div>
          ))
        ) : (
          <div className="stat-empty">No horizon data</div>
        )}
      </div>
    </div>
  )
}

export default QuestionStatistics
