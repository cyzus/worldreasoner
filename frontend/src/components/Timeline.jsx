import React, { useRef, useEffect, useState, memo } from 'react'
import './Timeline.css'

const Timeline = memo(function Timeline({ graphData, onTimeRangeChange, onEventClick, selectedNode, selectedQuestionId, questionRelatedEvents }) {
  const timelineRef = useRef(null)
  const [timeRange, setTimeRange] = useState({ start: null, end: null })
  const [hoveredEvent, setHoveredEvent] = useState(null)
  const [currentTime, setCurrentTime] = useState(100) // Percentage (0-100)
  const [isPlaying, setIsPlaying] = useState(false)
  const [playbackSpeed, setPlaybackSpeed] = useState(1) // 0.5x, 1x, 2x, 5x
  const playbackIntervalRef = useRef(null)

  // Extract events with dates and sort them
  // Filter by selected question if one is selected
  const questionEventIds = selectedQuestionId && questionRelatedEvents
    ? new Set(questionRelatedEvents.map(e => e.id))
    : null

  const eventsWithDates = graphData.nodes
    .filter(node => {
      // Filter by date availability
      if (!node.properties?.occurred_date && !node.properties?.predicted_date) {
        return false
      }
      // Filter by question if selected
      if (questionEventIds && !questionEventIds.has(node.id)) {
        return false
      }
      return true
    })
    .map(node => ({
      ...node,
      date: new Date(node.properties.occurred_date || node.properties.predicted_date),
    }))
    .sort((a, b) => a.date - b.date)

  useEffect(() => {
    if (eventsWithDates.length > 0) {
      const start = eventsWithDates[0].date
      const end = eventsWithDates[eventsWithDates.length - 1].date
      setTimeRange({ start, end })
    }
  }, [graphData])

  // Calculate current date from slider position
  const getCurrentDate = () => {
    if (!timeRange.start || !timeRange.end) return null
    const totalRange = timeRange.end - timeRange.start
    const offset = (currentTime / 100) * totalRange
    return new Date(timeRange.start.getTime() + offset)
  }

  // Calculate time window (start and end dates)
  // Show all events from the beginning up to current time (cumulative view)
  const getTimeWindow = () => {
    const endDate = getCurrentDate()
    if (!endDate || !timeRange.start) return null

    return { start: timeRange.start, end: endDate }
  }

  // Update graph when time position changes (with debounce for smoother UX)
  useEffect(() => {
    const timer = setTimeout(() => {
      const window = getTimeWindow()
      if (window && onTimeRangeChange) {
        onTimeRangeChange(window.start, window.end)
      }
    }, 30) // 30ms debounce for responsive updates during playback

    return () => clearTimeout(timer)
  }, [currentTime])

  // Playback controls
  useEffect(() => {
    if (isPlaying) {
      // Move forward by 0.2% every 100ms (adjustable by speed)
      const interval = 100 / playbackSpeed
      playbackIntervalRef.current = setInterval(() => {
        setCurrentTime(prev => {
          const next = prev + 0.2
          if (next >= 100) {
            setIsPlaying(false)
            return 100
          }
          return next
        })
      }, interval)
    } else {
      if (playbackIntervalRef.current) {
        clearInterval(playbackIntervalRef.current)
        playbackIntervalRef.current = null
      }
    }

    return () => {
      if (playbackIntervalRef.current) {
        clearInterval(playbackIntervalRef.current)
      }
    }
  }, [isPlaying, playbackSpeed])

  // Handle slider change
  const handleSliderChange = (e) => {
    setCurrentTime(parseFloat(e.target.value))
  }

  // Toggle playback
  const togglePlayback = () => {
    setIsPlaying(!isPlaying)
  }

  // Reset to end
  const resetToEnd = () => {
    setCurrentTime(100)
    setIsPlaying(false)
  }

  // Reset to start
  const resetToStart = () => {
    setCurrentTime(0)
    setIsPlaying(false)
  }

  // Clear filter (reset to show all)
  const handleClearFilter = () => {
    setCurrentTime(100)
    if (onTimeRangeChange) {
      onTimeRangeChange(null, null)
    }
  }

  if (eventsWithDates.length === 0) {
    const message = selectedQuestionId
      ? 'No events with dates for selected question'
      : 'No events with dates available'
    return (
      <div className="timeline-container">
        <div className="timeline-empty">{message}</div>
      </div>
    )
  }

  const { start: minDate, end: maxDate } = timeRange

  // Calculate position of event on timeline (0-100%)
  const getEventPosition = (date) => {
    if (!minDate || !maxDate) return 0
    const totalRange = maxDate - minDate
    if (totalRange === 0) return 50
    const offset = date - minDate
    return (offset / totalRange) * 100
  }

  // Check if event is in current time window
  const isEventInWindow = (event) => {
    const window = getTimeWindow()
    if (!window) return true

    return event.date >= window.start && event.date <= window.end
  }

  // Format date for display
  const formatDate = (date) => {
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  // Group events by year/month for better visualization
  const groupedEvents = eventsWithDates.reduce((acc, event) => {
    const key = `${event.date.getFullYear()}-${event.date.getMonth()}`
    if (!acc[key]) acc[key] = []
    acc[key].push(event)
    return acc
  }, {})

  const currentDate = getCurrentDate()
  const window = getTimeWindow()

  return (
    <div className="timeline-container">
      <div className="timeline-header">
        <div className="timeline-info">
          <span className="timeline-title">Time Traversal</span>
          {selectedQuestionId && (
            <span className="timeline-question-badge">🔍 Question Filtered</span>
          )}
          {window && (
            <div className="timeline-window-display">
              <span className="timeline-window-label">Viewing:</span>
              <span className="timeline-window-range">
                {formatDate(window.start)} → {formatDate(window.end)}
              </span>
            </div>
          )}
        </div>

        <div className="timeline-controls">
          <button
            className="timeline-control-btn"
            onClick={resetToStart}
            title="Go to start"
          >
            ⏮
          </button>
          <button
            className="timeline-control-btn"
            onClick={togglePlayback}
            title={isPlaying ? 'Pause' : 'Play'}
          >
            {isPlaying ? '⏸' : '▶'}
          </button>
          <button
            className="timeline-control-btn"
            onClick={resetToEnd}
            title="Go to end"
          >
            ⏭
          </button>

          <select
            className="timeline-speed-select"
            value={playbackSpeed}
            onChange={(e) => setPlaybackSpeed(parseFloat(e.target.value))}
            title="Playback speed"
          >
            <option value={0.5}>0.5x</option>
            <option value={1}>1x</option>
            <option value={2}>2x</option>
            <option value={5}>5x</option>
          </select>

          <button
            className="timeline-clear-btn"
            onClick={handleClearFilter}
            title="Reset to full view"
          >
            Reset Time
          </button>
        </div>
      </div>

      {/* Time slider */}
      <div className="timeline-slider-container">
        <input
          type="range"
          min="0"
          max="100"
          step="0.1"
          value={currentTime}
          onChange={handleSliderChange}
          className="timeline-slider"
        />
        <div
          className="timeline-current-marker"
          style={{ left: `${currentTime}%` }}
        />
      </div>

      <div className="timeline-track" ref={timelineRef}>
        {/* Timeline line */}
        <div className="timeline-line"></div>

        {/* Time window overlay */}
        {window && (
          <div
            className="timeline-window-overlay"
            style={{
              left: `${getEventPosition(window.start)}%`,
              right: `${100 - getEventPosition(window.end)}%`,
            }}
          />
        )}

        {/* Year markers */}
        {minDate && maxDate && (() => {
          const years = []
          const startYear = minDate.getFullYear()
          const endYear = maxDate.getFullYear()

          for (let year = startYear; year <= endYear; year++) {
            const yearDate = new Date(year, 0, 1)
            if (yearDate >= minDate && yearDate <= maxDate) {
              const position = getEventPosition(yearDate)
              years.push(
                <div
                  key={year}
                  className="timeline-year-marker"
                  style={{ left: `${position}%` }}
                >
                  <div className="timeline-year-tick"></div>
                  <div className="timeline-year-label">{year}</div>
                </div>
              )
            }
          }
          return years
        })()}

        {/* Event markers */}
        {eventsWithDates.map((event) => {
          const position = getEventPosition(event.date)
          const isSelected = selectedNode && selectedNode.id === event.id
          const isHovered = hoveredEvent === event.id
          const inWindow = isEventInWindow(event)

          return (
            <div
              key={event.id}
              className={`timeline-event ${isSelected ? 'selected' : ''} ${isHovered ? 'hovered' : ''} ${inWindow ? 'in-window' : 'out-window'}`}
              style={{
                left: `${position}%`,
              }}
              onClick={() => onEventClick(event)}
              onMouseEnter={() => setHoveredEvent(event.id)}
              onMouseLeave={() => setHoveredEvent(null)}
              title={`${event.name} - ${formatDate(event.date)}`}
            >
              <div
                className="timeline-event-dot"
                style={{ backgroundColor: event.color || '#6c757d' }}
              ></div>
              {(isSelected || isHovered) && (
                <div className="timeline-event-label">
                  <div className="timeline-event-name">{event.name}</div>
                  <div className="timeline-event-date">{formatDate(event.date)}</div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
})

export default Timeline
