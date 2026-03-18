import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const formatDate = (dateString) => {
    if (!dateString) return 'Unknown Date'
    return new Date(dateString).toLocaleDateString(undefined, {
        month: 'short', day: 'numeric', year: 'numeric'
    })
}

export function InformationStream({ articles, showHeader = true }) {
    const [expandedArticles, setExpandedArticles] = useState(new Set())

    const toggleArticle = (id) => {
        const newExpanded = new Set(expandedArticles)
        if (newExpanded.has(id)) newExpanded.delete(id)
        else newExpanded.add(id)
        setExpandedArticles(newExpanded)
    }

    return (
        <div className="cs-section">
            {showHeader && (
                <>
                    <h3 className="cs-section-title">Information Stream</h3>
                    <p className="cs-section-subtitle">Articles collected chronologically</p>
                </>
            )}

            {articles.length === 0 ? (
                <div className="cs-empty">No articles found in the current graph.</div>
            ) : (
                <div className="cs-timeline">
                    {articles.map(article => {
                        const dateStr = article.date || article.properties?.date
                        const title = article.title || article.name || article.properties?.title || 'Unknown Title'
                        const source = article.source || article.properties?.source || 'Unknown Source'
                        const summary = article.summary || article.properties?.summary

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
                                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{summary}</ReactMarkdown>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
