import React, { useMemo, useEffect, useState } from 'react';
import { fetchQuestionArticles } from '../api/graphApi';
import './CaseStudyView.css';

/**
 * CaseStudyView - Displays a clean, chronological view of articles and events
 * bypassing the heavy force-directed graph. Also handles forecast comparison.
 */
function CaseStudyView({
  graphData,
  forecasts,
  selectedQuestion
}) {
  const [fetchedArticles, setFetchedArticles] = useState([]);
  const [loadingArticles, setLoadingArticles] = useState(false);

  // 1. Fetch articles when question changes
  useEffect(() => {
    if (selectedQuestion?.id) {
      setLoadingArticles(true);
      fetchQuestionArticles(selectedQuestion.id)
        .then(data => {
          setFetchedArticles(data || []);
        })
        .catch(err => {
          console.error("Failed to fetch articles for case study:", err);
          setFetchedArticles([]);
        })
        .finally(() => {
          setLoadingArticles(false);
        });
    } else {
      setFetchedArticles([]);
    }
  }, [selectedQuestion?.id]);

  // 2. Process Articles (Information Stream) - Merge graph articles with fetched articles
  const articles = useMemo(() => {
    // Map fetched articles to a common format
    const processedFetched = fetchedArticles.map(a => ({
      ...a,
      id: a.id,
      date: a.published_date,
      title: a.title,
      source: a.source,
      summary: a.content // Or a summary if available
    }));

    // Filter nodes of type 'article' from graph (if any)
    const graphArticles = (graphData?.nodes || [])
      .filter(n =>
        n.node_type === 'article' ||
        n.type === 'article' ||
        n.node_type === 'Article' ||
        (n.properties && (n.properties.type === 'article' || n.properties.type === 'Article'))
      )
      .map(n => ({
        id: n.id,
        date: n.date || n.properties?.date || n.properties?.published_date,
        title: n.title || n.name || n.label || n.properties?.title,
        source: n.source || n.properties?.source,
        summary: n.summary || n.properties?.summary || n.properties?.description
      }));

    // Combine and deduplicate by ID
    const combined = [...processedFetched];
    const seenIds = new Set(processedFetched.map(a => a.id));

    graphArticles.forEach(a => {
      if (!seenIds.has(a.id)) {
        combined.push(a);
        seenIds.add(a.id);
      }
    });

    // Sort chronologically (oldest first)
    return combined.sort((a, b) => {
      const dateA = new Date(a.date || 0);
      const dateB = new Date(b.date || 0);
      return dateA - dateB;
    });
  }, [fetchedArticles, graphData]);

  // 3. Process Events (Causal Events)
  const events = useMemo(() => {
    if (!graphData?.nodes) return [];

    // Filter nodes of type 'event'
    const eventNodes = graphData.nodes.filter(n =>
      n.node_type === 'event' ||
      n.type === 'event' ||
      n.node_type === 'Event' ||
      (n.properties && (n.properties.type === 'event' || n.properties.type === 'Event')) ||
      n.isOutcome ||
      (n.properties && n.properties.is_outcome) ||
      (n.properties && n.properties.is_actual_outcome)
    );

    // Sort chronologically (oldest first)
    return eventNodes.sort((a, b) => {
      const dateA = new Date(a.occurred_date || a.predicted_date || a.properties?.occurred_date || a.properties?.predicted_date || 0);
      const dateB = new Date(b.occurred_date || b.predicted_date || b.properties?.occurred_date || b.properties?.predicted_date || 0);
      return dateA - dateB;
    });
  }, [graphData]);

  // Format Date cleanly
  const formatDate = (dateString) => {
    if (!dateString) return 'Unknown Date';
    return new Date(dateString).toLocaleDateString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric'
    });
  };

  return (
    <div className="case-study-view">

      {/* 1. Forecast Comparison Section */}
      <div className="cs-section">
        <h3 className="cs-section-title">📊 Forecast Comparison</h3>
        <p className="cs-section-subtitle">How different evaluation conditions performed on this question</p>

        {!forecasts || forecasts.length === 0 ? (
          <div className="cs-empty">No forecasts available for this question.</div>
        ) : (
          <div className="cs-forecast-cards">
            {forecasts.map(fc => (
              <div key={fc.id} className="cs-forecast-card">
                <div className="cs-fc-header">
                  <span className="cs-fc-mode">{fc.mode}</span>
                  <span className="cs-fc-prob">
                    {fc.probability !== null ? `${(fc.probability * 100).toFixed(1)}%` : 'N/A'}
                  </span>
                </div>
                {fc.expected_outcome && (
                  <div className="cs-fc-outcome">
                    <strong>Prediction:</strong> {fc.expected_outcome}
                  </div>
                )}
                {fc.rationale && (
                  <div className="cs-fc-rationale">
                    {fc.rationale.substring(0, 150)}{fc.rationale.length > 150 ? '...' : ''}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 2. Causal Events Section (Chronological) */}
      <div className="cs-section">
        <h3 className="cs-section-title">⚡ Causal Events</h3>
        <p className="cs-section-subtitle">Chronological progression of key events extracted from the evidence</p>

        {events.length === 0 ? (
          <div className="cs-empty">No events found in the current graph.</div>
        ) : (
          <div className="cs-table-container">
            <table className="cs-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Event Summary</th>
                  <th>Impact</th>
                </tr>
              </thead>
              <tbody>
                {events.map(event => {
                  const isOutcome = event.isOutcome || event.properties?.is_outcome || event.properties?.is_actual_outcome;
                  const dateStr = event.occurred_date || event.predicted_date || event.properties?.occurred_date || event.properties?.predicted_date;
                  const title = event.title || event.name || event.properties?.title || 'Unnamed Event';
                  const titleStr = title.length > 100 ? title.substring(0, 100) + '...' : title;

                  // Extract impact if available (from node properties or finding edges)
                  const impactDirection = event.impact_direction || event.properties?.impact_direction || 'mixed';

                  return (
                    <tr key={event.id} className={isOutcome ? 'cs-row-outcome' : ''}>
                      <td className="cs-td-date">{formatDate(dateStr)}</td>
                      <td className="cs-td-main">
                        <div className="cs-event-title">
                          {isOutcome && <span className="cs-badge-outcome">OUTCOME</span>}
                          {titleStr}
                        </div>
                      </td>
                      <td className="cs-td-impact">
                        {!isOutcome && (
                          <span className={`cs-impact-badge cs-impact-${impactDirection}`}>
                            {impactDirection}
                          </span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 3. Information Stream Section (Articles) */}
      <div className="cs-section">
        <h3 className="cs-section-title">📰 Information Stream</h3>
        <p className="cs-section-subtitle">Articles collected chronologically</p>

        {articles.length === 0 ? (
          <div className="cs-empty">No articles found in the current graph.</div>
        ) : (
          <div className="cs-timeline">
            {articles.map(article => {
              const dateStr = article.date || article.properties?.date;
              const title = article.title || article.name || article.properties?.title || 'Unknown Title';
              const source = article.source || article.properties?.source || 'Unknown Source';
              const summary = article.summary || article.properties?.summary;

              return (
                <div key={article.id} className="cs-timeline-item">
                  <div className="cs-timeline-date">{formatDate(dateStr)}</div>
                  <div className="cs-timeline-content">
                    <div className="cs-article-header">
                      <span className="cs-article-source">{source}</span>
                      <h4 className="cs-article-title">{title}</h4>
                    </div>
                    {summary && (
                      <p className="cs-article-summary">
                        {summary.substring(0, 200)}{summary.length > 200 ? '...' : ''}
                      </p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

    </div>
  );
}

export default CaseStudyView;
