import React, { useMemo } from 'react'
import './QuestionStatistics.css'

function QuestionStatistics({ questions }) {
  const stats = useMemo(() => {
    if (!questions || questions.length === 0) return null

    const total = questions.length
    const now = new Date()

    // 1. Domain Stats
    const domains = {}
    questions.forEach(q => {
      const domain = q.domain || 'unknown'
      domains[domain] = (domains[domain] || 0) + 1
    })
    const topDomains = Object.entries(domains)
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => ({ name, count, percent: (count / total) * 100 }))

    // 2. Type Stats
    const types = {}
    questions.forEach(q => {
      const type = q.question_type || 'unknown'
      types[type] = (types[type] || 0) + 1
    })
    const topTypes = Object.entries(types)
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => ({ name, count, percent: (count / total) * 100 }))

    // 3. Source Stats
    const sources = {}
    questions.forEach(q => {
      let source = q.source || 'manual'
      // Normalize source names if needed
      if (source.toLowerCase().includes('news')) source = 'News Pipeline'
      else if (source.toLowerCase().includes('polymarket')) source = 'Polymarket'
      else source = source.charAt(0).toUpperCase() + source.slice(1)

      sources[source] = (sources[source] || 0) + 1
    })
    const topSources = Object.entries(sources)
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => ({ name, count, percent: (count / total) * 100 }))

    // 4. Difficulty Stats
    const difficulties = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 }
    questions.forEach(q => {
      const d = q.difficulty || 0
      if (difficulties[d] !== undefined) difficulties[d]++
    })
    const difficultyStats = Object.entries(difficulties)
      .map(([level, count]) => ({ name: `Level ${level}`, count, percent: (count / total) * 100 }))

    // 5. Status Stats (Active vs Resolved) & Time Horizon
    const horizons = {
      'Past': 0,
      'Short (< 1 mo)': 0,
      'Medium (1-6 mo)': 0,
      'Long (> 6 mo)': 0,
      'Unknown': 0
    }
    const status = { 'Active': 0, 'Resolved': 0, 'Future': 0 }

    questions.forEach(q => {
      // Status Logic
      const resDate = new Date(q.resolution_date)
      if (!isNaN(resDate.getTime())) {
        if (resDate < now) status['Resolved']++
        else status['Active']++
      } else {
        status['Active']++ // Assume active if bad date
      }

      // Time Horizon Logic
      if (isNaN(resDate.getTime())) {
        horizons['Unknown']++
        return
      }

      let startDate
      if (q.estimated_start_time) {
        startDate = new Date(q.estimated_start_time)
      } else {
        // Fallback: resolution date - 30 days
        startDate = new Date(resDate)
        startDate.setDate(resDate.getDate() - 30)
      }
      if (isNaN(startDate.getTime())) {
        horizons['Unknown']++
        return
      }

      const diffTime = resDate - startDate
      const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))

      if (diffDays < 0) {
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
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => ({ name, count, percent: (count / total) * 100 }))

    return {
      domains: topDomains,
      types: topTypes,
      sources: topSources,
      difficulty: difficultyStats,
      horizons: topHorizons,
      status,
      total
    }
  }, [questions])

  if (!stats) return <div className="stats-loading">Loading statistics...</div>

  const StatCard = ({ title, items, color = '#4dabf7' }) => (
    <div className="stat-card">
      <h4>{title}</h4>
      <div className="stat-list">
        {items.map(item => (
          <div key={item.name} className="stat-item">
            <div className="stat-row">
              <span className="stat-label">{item.name}</span>
              <span className="stat-value">{item.count}</span>
            </div>
            <div className="stat-bar-container">
              <div
                className="stat-bar"
                style={{ width: `${item.percent}%`, backgroundColor: color }}
              ></div>
            </div>
          </div>
        ))}
        {items.length === 0 && <div className="stat-empty">No data</div>}
      </div>
    </div>
  )

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h2>Analytics Dashboard</h2>
        <div className="kpi-row">
          <div className="kpi-card">
            <div className="kpi-value">{stats.total}</div>
            <div className="kpi-label">Total Questions</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-value">{stats.status.Active}</div>
            <div className="kpi-label">Active Forecasts</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-value">{stats.status.Resolved}</div>
            <div className="kpi-label">Resolved Events</div>
          </div>
        </div>
      </div>

      <div className="dashboard-grid">
        <StatCard title="Domains" items={stats.domains} color="#4dabf7" />
        <StatCard title="Sources" items={stats.sources} color="#ff6b6b" />
        <StatCard title="Question Types" items={stats.types} color="#51cf66" />
        <StatCard title="Time Horizon" items={stats.horizons} color="#ff922b" />
        <StatCard title="Difficulty" items={stats.difficulty} color="#845ef7" />
      </div>
    </div>
  )
}

export default QuestionStatistics
