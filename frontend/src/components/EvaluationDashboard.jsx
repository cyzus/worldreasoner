import React, { useState, useEffect } from 'react';
import { fetchEvaluationReport, runEvaluation } from '../api/graphApi';
import './EvaluationDashboard.css';

const EvaluationDashboard = () => {
    const [report, setReport] = useState(null);
    const [loading, setLoading] = useState(false);
    const [runningEval, setRunningEval] = useState(false);
    const [error, setError] = useState(null);

    const loadReport = async () => {
        setLoading(true);
        try {
            const data = await fetchEvaluationReport();
            setReport(data);
        } catch (err) {
            setError('Failed to load evaluation report');
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadReport();
    }, []);

    const handleRunEvaluation = async () => {
        setRunningEval(true);
        try {
            await runEvaluation(true);
            // Wait a bit before reloading to let background task start/finish some work
            // Ideally we should poll or use websockets, but for now a simple delay + reload
            setTimeout(() => {
                loadReport();
            }, 2000);
        } catch (err) {
            setError('Failed to start evaluation');
            console.error(err);
        } finally {
            setRunningEval(false);
        }
    };

    if (loading && !report) return <div className="loading">Loading evaluation metrics...</div>;
    if (error) return <div className="error-message">{error}</div>;

    return (
        <div className="evaluation-dashboard">
            <div className="dashboard-header">
                <h3>📊 Forecast Evaluation Metrics</h3>
                <button
                    className="run-eval-btn"
                    onClick={handleRunEvaluation}
                    disabled={runningEval}
                >
                    {runningEval ? 'Running...' : '🔄 Run Batch Evaluation'}
                </button>
            </div>

            {report && (
                <div className="dashboard-content">
                    <div className="stats-grid">
                        <div className="stat-card">
                            <div className="stat-label">Total Forecasts</div>
                            <div className="stat-value">{report.total_forecasts}</div>
                        </div>
                        <div className="stat-card">
                            <div className="stat-label">Overall Accuracy</div>
                            <div className="stat-value">{(report.overall_accuracy * 100).toFixed(1)}%</div>
                        </div>
                        <div className="stat-card">
                            <div className="stat-label">Avg Brier Score</div>
                            <div className="stat-value">{report.avg_brier_score?.toFixed(4) || 'N/A'}</div>
                            <div className="stat-desc">Lower is better (0-1)</div>
                        </div>
                        <div className="stat-card">
                            <div className="stat-label">Avg Log Score</div>
                            <div className="stat-value">{report.avg_log_score?.toFixed(4) || 'N/A'}</div>
                            <div className="stat-desc">Higher is better</div>
                        </div>
                    </div>

                    <div className="breakdown-section">
                        <div className="breakdown-card">
                            <h4>By Question Type</h4>
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>Type</th>
                                        <th>Count</th>
                                        <th>Accuracy</th>
                                        <th>Brier</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {Object.entries(report.by_question_type || {}).map(([type, stats]) => (
                                        <tr key={type}>
                                            <td>{type}</td>
                                            <td>{stats.count}</td>
                                            <td>{(stats.accuracy * 100).toFixed(1)}%</td>
                                            <td>{stats.avg_brier_score?.toFixed(3) || '-'}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>

                        <div className="breakdown-card">
                            <h4>By Forecast Mode</h4>
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>Mode</th>
                                        <th>Count</th>
                                        <th>Accuracy</th>
                                        <th>Brier</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {Object.entries(report.by_mode || {}).map(([mode, stats]) => (
                                        <tr key={mode}>
                                            <td>
                                                <span style={{
                                                    textTransform: 'capitalize',
                                                    fontWeight: '500',
                                                    color:
                                                        mode === 'real_time' ? '#e67700' :
                                                            mode === 'container' ? '#2b8a3e' :
                                                                '#1c7ed6'
                                                }}>
                                                    {mode.replace('_', ' ')}
                                                </span>
                                            </td>
                                            <td>{stats.count}</td>
                                            <td>{(stats.accuracy * 100).toFixed(1)}%</td>
                                            <td>{stats.avg_brier_score?.toFixed(3) || '-'}</td>
                                        </tr>
                                    ))}
                                    {Object.keys(report.by_mode || {}).length === 0 && (
                                        <tr>
                                            <td colSpan="4" style={{ textAlign: 'center', color: '#888' }}>No mode data available</td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>

                        <div className="breakdown-card">
                            <h4>Calibration (Boolean)</h4>
                            {report.calibration ? (
                                <div className="calibration-stats">
                                    <div className="cal-stat">
                                        <span>Calibration Error:</span>
                                        <strong>{report.calibration.expected_calibration_error?.toFixed(4)}</strong>
                                    </div>
                                    <table className="data-table mini">
                                        <thead>
                                            <tr>
                                                <th>Confidence</th>
                                                <th>Accuracy</th>
                                                <th>Count</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {report.calibration.bins?.map((bin, i) => (
                                                <tr key={i}>
                                                    <td>{bin.range_start}-{bin.range_end}</td>
                                                    <td>{(bin.accuracy * 100).toFixed(1)}%</td>
                                                    <td>{bin.count}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            ) : (
                                <div className="no-data">No calibration data available</div>
                            )}
                        </div>
                    </div>

                    <div className="breakdown-section full-width">
                        <div className="breakdown-card">
                            <h4>Model Performance</h4>
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>Model</th>
                                        <th>Version</th>
                                        <th>Count</th>
                                        <th>Accuracy</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {Object.entries(report.model_info?.models || {}).map(([name, stats]) => (
                                        <tr key={name}>
                                            <td>{name}</td>
                                            <td>{stats.version || '-'}</td>
                                            <td>{stats.count}</td>
                                            <td>{(stats.accuracy * 100).toFixed(1)}%</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div className="meta-info">
                        Last evaluated: {new Date(report.evaluation_timestamp).toLocaleString()}
                    </div>
                </div>
            )}
        </div>
    );
};

export default EvaluationDashboard;
