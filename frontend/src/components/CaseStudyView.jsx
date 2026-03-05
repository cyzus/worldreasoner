import React, { useMemo, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { fetchQuestionArticles, fetchOutcomeImpacts, fetchForecastGraph } from '../api/graphApi';
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
  const [impacts, setImpacts] = useState({}); // outcomeId -> list of impacts
  const [loadingImpacts, setLoadingImpacts] = useState(false);
  const [activeForecastGraph, setActiveForecastGraph] = useState(null);
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [expandedRows, setExpandedRows] = useState(new Set());
  const [expandedArticles, setExpandedArticles] = useState(new Set());

  // 1. Fetch articles and impacts when question changes
  useEffect(() => {
    if (selectedQuestion?.id) {
      setLoadingArticles(true);
      setLoadingImpacts(true);

      // Fetch articles
      fetchQuestionArticles(selectedQuestion.id)
        .then(data => setFetchedArticles(data || []))
        .catch(err => console.error("Failed to fetch articles:", err))
        .finally(() => setLoadingArticles(false));

      // Fetch outcomes first to get their impacts
      // CRITICAL: Filter by selectedQuestion.id to prevent fetching all outcomes in the full graph
      const outcomeNodes = (graphData?.nodes || []).filter(n => {
        const props = n.properties || {};
        const isOutcome = n.isOutcome || props.is_outcome || props.is_actual_outcome;
        const qId = n.question_id || props.extracted_for_question_id;
        return isOutcome && qId === selectedQuestion.id;
      });

      const impactPromises = outcomeNodes.map(node =>
        fetchOutcomeImpacts(node.id).then(data => ({ id: node.id, title: node.title || node.name || node.properties?.title, data }))
      );

      Promise.all(impactPromises)
        .then(results => {
          const bySource = {};
          results.forEach(r => {
            const outcomeId = r.id;
            const outcomeTitle = r.title || 'Unknown Outcome';

            r.data.forEach(imp => {
              const sourceId = imp.source_id || imp.event_id;
              if (!bySource[sourceId]) bySource[sourceId] = [];

              bySource[sourceId].push({
                outcomeId,
                outcomeTitle,
                impact_direction: imp.impact_direction || imp.properties?.impact_direction,
                impact_magnitude: imp.impact_magnitude ?? imp.properties?.impact_magnitude ?? imp.weight ?? 0,
                confidence: imp.confidence ?? imp.properties?.confidence ?? 1.0,
                reasoning: imp.reasoning || imp.properties?.reasoning,
                articleIds: imp.evidence_article_ids || imp.properties?.evidence_article_ids || []
              });
            });
          });
          setImpacts(bySource);
        })
        .catch(err => console.error("Failed to fetch impacts:", err))
        .finally(() => setLoadingImpacts(false));

    } else {
      setFetchedArticles([]);
      setImpacts({});
    }
  }, [selectedQuestion?.id, graphData?.nodes]);

  const toggleRow = (id) => {
    const newExpanded = new Set(expandedRows);
    if (newExpanded.has(id)) newExpanded.delete(id);
    else newExpanded.add(id);
    setExpandedRows(newExpanded);
  };

  const toggleArticle = (id) => {
    const newExpanded = new Set(expandedArticles);
    if (newExpanded.has(id)) newExpanded.delete(id);
    else newExpanded.add(id);
    setExpandedArticles(newExpanded);
  };

  const handleViewForecastGraph = async (forecastId) => {
    setLoadingGraph(true);
    try {
      const graph = await fetchForecastGraph(forecastId);
      setActiveForecastGraph(graph);
    } catch (err) {
      console.error("Failed to fetch forecast graph:", err);
      alert("Could not load reasoning graph for this forecast.");
    } finally {
      setLoadingGraph(false);
    }
  };

  // 1.5 Create article lookup map for evidence links
  const articleMap = useMemo(() => {
    const map = {};
    fetchedArticles.forEach(a => { map[a.id] = a; });
    // Also include articles from graphData if they exist as nodes
    (graphData?.nodes || []).forEach(n => {
      const isArticle = n.node_type === 'article' || n.properties?.type === 'article' || n.properties?.type === 'Article';
      if (isArticle && !map[n.id]) {
        map[n.id] = {
          id: n.id,
          title: n.title || n.name || n.properties?.title || 'Unknown Article',
          source: n.source || n.properties?.source || 'Original Source',
          published_date: n.date || n.properties?.date || n.properties?.published_date,
          url: n.url || n.properties?.url
        };
      }
    });
    return map;
  }, [fetchedArticles, graphData?.nodes]);

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
      .filter(n => {
        const isArticle = n.node_type === 'article' ||
          n.type === 'article' ||
          n.node_type === 'Article' ||
          (n.properties && (n.properties.type === 'article' || n.properties.type === 'Article'));
        const qId = n.question_id || n.properties?.extracted_for_question_id || n.properties?.collected_for_question_id;
        return isArticle && qId === selectedQuestion.id;
      })
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

    // Filter nodes of type 'event' and restrict to current question
    const eventNodes = graphData.nodes.filter(n => {
      const isEvent = n.node_type === 'event' ||
        n.type === 'event' ||
        n.node_type === 'Event' ||
        (n.properties && (n.properties.type === 'event' || n.properties.type === 'Event')) ||
        n.isOutcome ||
        (n.properties && n.properties.is_outcome) ||
        (n.properties && n.properties.is_actual_outcome);

      const qId = n.question_id || n.properties?.extracted_for_question_id;
      return isEvent && qId === selectedQuestion.id;
    });

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
                  <div className="cs-fc-rationale markdown-body">
                    <ReactMarkdown>{fc.rationale}</ReactMarkdown>
                  </div>
                )}
                <div className="cs-fc-footer">
                  <button
                    className="cs-btn-view-graph"
                    onClick={() => handleViewForecastGraph(fc.id)}
                    disabled={loadingGraph}
                  >
                    {loadingGraph ? 'Loading...' : '🔍 View Reasoning Graph'}
                  </button>
                </div>
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

                  // Extract impact if available
                  const impactDirection = event.impact_direction || event.properties?.impact_direction || 'mixed';
                  const isExpanded = expandedRows.has(event.id);
                  const outcomeImpacts = impacts[event.id] || [];

                  return (
                    <React.Fragment key={event.id}>
                      <tr
                        className={`${isOutcome ? 'cs-row-outcome' : ''} ${isExpanded ? 'cs-row-expanded' : ''}`}
                        onClick={() => toggleRow(event.id)}
                        style={{ cursor: 'pointer' }}
                      >
                        <td className="cs-td-date">{formatDate(dateStr)}</td>
                        <td className="cs-td-main">
                          <div className="cs-event-title">
                            {isOutcome && <span className="cs-badge-outcome">OUTCOME</span>}
                            {titleStr}
                            <span className={`cs-expand-icon ${isExpanded ? 'open' : ''}`}>▼</span>
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
                      {isExpanded && (
                        <tr className="cs-row-details">
                          <td colSpan="3">
                            <div className="cs-details-content">
                              <div className="cs-details-header">
                                <p><strong>Description:</strong> {event.description || event.properties?.description || 'No description available.'}</p>

                                {/* Event Source Evidence */}
                                <div className="cs-evidence-section">
                                  <span className="cs-evidence-label">Source Evidence:</span>
                                  <div className="cs-evidence-links">
                                    {Array.from(new Set([
                                      ...(event.article_ids || []),
                                      ...(event.properties?.article_ids || []),
                                      event.source_article_id,
                                      event.properties?.source_article_id
                                    ])).filter(Boolean).map(id => {
                                      const art = articleMap[id];
                                      return (
                                        <a
                                          key={id}
                                          href={art?.url || `#art-${id}`}
                                          target={art?.url ? "_blank" : "_self"}
                                          rel={art?.url ? "noopener noreferrer" : ""}
                                          className="cs-evidence-pill"
                                          title={art?.title}
                                        >
                                          {art ? `${art.source || 'Source'}: ${art.title.substring(0, 30)}...` : `Doc ${id.substring(0, 6)}`}
                                        </a>
                                      );
                                    })}
                                    {(!event.article_ids?.length && !event.properties?.article_ids?.length && !event.source_article_id) &&
                                      <span className="cs-no-evidence">No direct sources linked.</span>
                                    }
                                  </div>
                                </div>
                              </div>

                              {outcomeImpacts.length > 0 && (
                                <div className="cs-impact-details">
                                  <h4>Impact Analysis</h4>
                                  {outcomeImpacts.map((imp, idx) => (
                                    <div key={idx} className="cs-impact-item">
                                      <div className="cs-impact-meta">
                                        <span className="cs-impact-on">Affects <strong>{imp.outcomeTitle}</strong></span>
                                        <span className={`cs-impact-badge cs-impact-${imp.impact_direction}`}>
                                          {imp.impact_direction} ({Math.round(imp.impact_magnitude * 100)}%)
                                        </span>
                                        <span className="cs-impact-confidence">
                                          Confidence: {Math.round(imp.confidence * 100)}%
                                        </span>
                                      </div>
                                      <div className="cs-impact-reasoning markdown-body">
                                        <ReactMarkdown>{imp.reasoning}</ReactMarkdown>
                                      </div>

                                      {/* Impact Evidence Articles */}
                                      {imp.articleIds?.length > 0 && (
                                        <div className="cs-impact-evidence">
                                          <span className="cs-evidence-label">Evidence for this impact:</span>
                                          <div className="cs-evidence-links">
                                            {imp.articleIds.map(id => {
                                              const art = articleMap[id];
                                              return (
                                                <a
                                                  key={id}
                                                  href={art?.url || `#art-${id}`}
                                                  target={art?.url ? "_blank" : "_self"}
                                                  rel={art?.url ? "noopener noreferrer" : ""}
                                                  className="cs-evidence-pill cs-pill-sm"
                                                >
                                                  {art ? art.title.substring(0, 40) + '...' : `Evidence ${id.substring(0, 6)}`}
                                                </a>
                                              );
                                            })}
                                          </div>
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
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
                <div key={article.id} id={`art-${article.id}`} className="cs-timeline-item">
                  <div className="cs-timeline-date">{formatDate(dateStr)}</div>
                  <div className="cs-timeline-content">
                    <div
                      className="cs-article-header"
                      onClick={() => toggleArticle(article.id)}
                      style={{ cursor: 'pointer' }}
                    >
                      <span className="cs-article-source">{source}</span>
                      <h4 className="cs-article-title">{title}</h4>
                      <span className={`cs-expand-icon ${expandedArticles.has(article.id) ? 'open' : ''}`}>▼</span>
                    </div>
                    {summary && expandedArticles.has(article.id) && (
                      <div className="cs-article-summary markdown-body">
                        <ReactMarkdown>{summary}</ReactMarkdown>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* 4. Forecast Graph Modal */}
      {activeForecastGraph && (
        <div className="cs-modal-overlay" onClick={() => setActiveForecastGraph(null)}>
          <div className="cs-modal" onClick={e => e.stopPropagation()}>
            <div className="cs-modal-header">
              <h3>Reasoning Graph: {activeForecastGraph.forecast_id}</h3>
              <button className="cs-modal-close" onClick={() => setActiveForecastGraph(null)}>×</button>
            </div>
            <div className="cs-modal-body">
              <div className="cs-graph-summary">
                <div className="cs-stat"><strong>Events:</strong> {activeForecastGraph.events.length}</div>
                <div className="cs-stat"><strong>Hypotheses:</strong> {activeForecastGraph.hypotheses.length}</div>
              </div>
              <div className="cs-graph-list">
                <h4>Causal Relationships Found:</h4>
                {activeForecastGraph.hypotheses.length === 0 ? (
                  <p>No explicit causal hypotheses recorded for this forecast.</p>
                ) : (
                  activeForecastGraph.hypotheses.map(hyp => {
                    const src = activeForecastGraph.events.find(e => e.id === hyp.source_event_id);
                    const tgt = activeForecastGraph.events.find(e => e.id === hyp.target_event_id);
                    return (
                      <div key={hyp.id} className="cs-hyp-item">
                        <div className="cs-hyp-path">
                          <span className="cs-hyp-node">{src?.title || hyp.source_event_id}</span>
                          <span className="cs-hyp-arrow">⎯⎯ {hyp.relation_type} ({Math.round(hyp.strength * 100)}%) ⎯→</span>
                          <span className="cs-hyp-node">{tgt?.title || hyp.target_event_id}</span>
                        </div>
                        <div className="cs-hyp-reasoning markdown-body">
                          <ReactMarkdown>{hyp.reasoning}</ReactMarkdown>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default CaseStudyView;
