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
      '< 1 Month': 0,
      '1-6 Months': 0,
      '> 6 Months': 0,
      'Unknown': 0
    }

    questions.forEach(q => {
      if (!q.resolution_date) {
        horizons['Unknown']++
        return
      }

      const resDate = new Date(q.resolution_date)
      if (isNaN(resDate.getTime())) {
        horizons['Unknown']++
        return
      }

      const diffTime = resDate - now
      const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))

      if (diffDays < 0) {
        horizons['Past']++
      } else if (diffDays <= 30) {
        horizons['< 1 Month']++
      } else if (diffDays <= 180) {
        horizons['1-6 Months']++
      } else {
        horizons['> 6 Months']++
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
