import React from 'react'
import { useEventArticles, useEventQuestions } from '../../hooks/queries/useEventQueries'

export const formatDate = (dateString) => {
    if (!dateString) return 'Unknown'
    return new Date(dateString).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    })
}

export const truncateText = (text, maxLength = 150) => {
    if (!text) return ''
    if (text.length <= maxLength) return text
    return text.substring(0, maxLength) + '...'
}

export const RelatedArticles = ({ eventId, show, onToggle }) => {
    const { data, isLoading, isFetched } = useEventArticles(eventId, show)
    const articles = data?.articles || []

    return (
        <div className="expandable-section">
            <button
                className={`section-toggle ${show ? 'active' : ''}`}
                onClick={onToggle}
                style={{ padding: '8px 12px', fontSize: '0.9rem' }}
            >
                <span className="toggle-text">Related Articles</span>
                <span className="toggle-meta" style={{ fontSize: '0.8rem' }}>
                    {isFetched ? articles.length : ''}
                    <span className="toggle-icon">{show ? '−' : '+'}</span>
                </span>
            </button>

            {show && (
                <div className="section-content">
                    {isLoading ? (
                        <div className="loading-message">Loading...</div>
                    ) : articles.length === 0 ? (
                        <div className="empty-message">No articles</div>
                    ) : (
                        <div className="articles-list">
                            {articles.map(article => (
                                <div key={article.id} className="article-card" style={{ padding: '10px' }}>
                                    <div className="article-header">
                                        <h4 className="article-title" style={{ fontSize: '0.9rem' }}>{article.title}</h4>
                                        <span className="article-date" style={{ fontSize: '0.75rem' }}>{formatDate(article.published_date)}</span>
                                    </div>
                                    <div className="article-source-badge" style={{ fontSize: '0.7rem' }}>{article.source}</div>
                                    <p className="article-excerpt" style={{ fontSize: '0.8rem', marginTop: '4px' }}>{truncateText(article.content)}</p>
                                    {article.url && (
                                        <a
                                            href={article.url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="article-link"
                                            style={{ fontSize: '0.8rem' }}
                                        >
                                            Source ↗
                                        </a>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

export const RelatedQuestions = ({ eventId, show, onToggle }) => {
    const { data, isLoading, isFetched } = useEventQuestions(eventId, show)
    const questions = data?.questions || []

    return (
        <div className="expandable-section">
            <button
                className={`section-toggle ${show ? 'active' : ''}`}
                onClick={onToggle}
                style={{ padding: '8px 12px', fontSize: '0.9rem' }}
            >
                <span className="toggle-text">Related Questions</span>
                <span className="toggle-meta" style={{ fontSize: '0.8rem' }}>
                    {isFetched ? questions.length : ''}
                    <span className="toggle-icon">{show ? '−' : '+'}</span>
                </span>
            </button>

            {show && (
                <div className="section-content">
                    {isLoading ? (
                        <div className="loading-message">Loading...</div>
                    ) : questions.length === 0 ? (
                        <div className="empty-message">No questions</div>
                    ) : (
                        <div className="questions-list">
                            {questions.map(question => (
                                <div key={question.id} className="question-card" style={{ padding: '10px' }}>
                                    <div className="question-text" style={{ fontSize: '0.9rem' }}>{question.question_text}</div>
                                    <div className="question-tags">
                                        <span className="tag domain" style={{ fontSize: '0.7rem' }}>{question.domain}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
