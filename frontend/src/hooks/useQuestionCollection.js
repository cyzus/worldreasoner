import { useState, useCallback, useMemo, useEffect } from 'react'
import { fetchPreviewQuestions, startNewsCollectionJob, saveQuestionsBatch as apiSaveQuestionsBatch } from '../api/graphApi'
import { usePipelineJobs } from './usePipelineJobs'

/**
 * Hook to manage question collection page logic
 */
export const useQuestionCollection = ({
    onQuestionsAdded,
    previewQuestions,
    setPreviewQuestions,
    sourceTab,
    previewSource,
    setPreviewSource
}) => {
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)
    const [success, setSuccess] = useState(null)

    // Job management
    const {
        jobs,
        loadingJobs,
        selectedJobId,
        jobDetails,
        loadingDetails,
        selectJob,
        loadJobs
    } = usePipelineJobs(null);

    // Only show preview questions if they match the current source tab
    const filteredPreviewQuestions = useMemo(() => {
        if (!previewSource) return []
        if (previewSource === sourceTab) return previewQuestions
        return []
    }, [previewQuestions, previewSource, sourceTab])

    // Handle news job completion — merge newly collected questions into preview
    const handleNewsJobCompletion = useCallback(() => {
        if (
            jobDetails &&
            jobDetails.status === 'completed' &&
            jobDetails.pipeline_type === 'news_collection' &&
            sourceTab === 'news'
        ) {
            const results = jobDetails.results || {}
            const questions = results.processed_details || []

            if (questions.length > 0) {
                const mappedQuestions = questions.map(q => ({
                    id: q.id,
                    question_text: q.text || q.question_text,
                    question_type: q.type,
                    domain: q.domain,
                    source: q.source,
                    resolution_date: q.resolution_date,
                    resolution_criteria: q.resolution_criteria,
                    ground_truth: q.ground_truth,
                    resolution_reasoning: q.resolution_reasoning,
                    difficulty: q.difficulty || 1,
                    related_event_ids: q.related_event_ids,
                    estimated_start_time: q.estimated_start_time,
                    metadata: q.metadata || {}
                }))

                const currentQuestions = Array.isArray(previewQuestions) ? previewQuestions : []
                const existingIds = new Set(currentQuestions.map(p => p.id))
                const newUnique = mappedQuestions.filter(q => !existingIds.has(q.id))

                if (newUnique.length > 0) {
                    setPreviewQuestions([...currentQuestions, ...newUnique])
                    setPreviewSource('news')
                    selectJob(null)
                    setSuccess(`✓ Job completed! Added ${newUnique.length} new questions to preview list.`)
                }
            }
        }
    }, [jobDetails, sourceTab, previewQuestions, setPreviewQuestions, setPreviewSource, selectJob])

    // Watch for job completion
    useEffect(() => {
        handleNewsJobCompletion()
    }, [handleNewsJobCompletion])

    /**
     * Handle fetching preview questions from the API
     */
    const handleFetchPreview = useCallback(async (config) => {
        setLoading(true)
        setError(null)
        setSuccess(null)
        setPreviewQuestions([])
        setPreviewSource(null)

        try {
            if (sourceTab === 'news') {
                const data = await startNewsCollectionJob({
                    question_ids: [],
                    pipeline_type: 'news_collection',
                    config: config
                })

                setSuccess(`Started News Collection Job: ${data.job_id}`)
                await loadJobs()
                selectJob(data.job_id)

            } else {
                const requestBody = {
                    source: sourceTab,
                    ...config,
                }

                const data = await fetchPreviewQuestions(requestBody)

                if (data.success) {
                    setPreviewQuestions(data.questions)
                    setPreviewSource(data.source)
                    setSuccess(`Fetched ${data.total} questions from ${data.source}`)
                } else {
                    setError(data.errors.join('; ') || 'Failed to fetch questions')
                }
            }
        } catch (err) {
            setError(`Error: ${err.message}`)
            console.error('Preview/Job fetch error:', err)
        } finally {
            setLoading(false)
        }
    }, [sourceTab, setPreviewQuestions, setPreviewSource, loadJobs, selectJob])

    /**
     * Handle manual question creation
     */
    const handleManualQuestionCreated = useCallback((question) => {
        setSuccess(`Question created: ${question.id}`)
        if (onQuestionsAdded) {
            onQuestionsAdded(1)
        }
    }, [onQuestionsAdded])

    /**
     * Handle saving selected questions to database
     */
    const handleSaveSelected = useCallback(async (selectedQuestions) => {
        setLoading(true)
        setError(null)
        setSuccess(null)

        try {
            const data = await apiSaveQuestionsBatch({
                question_ids: selectedQuestions.map(q => q.id),
                questions: selectedQuestions,
            })

            if (data.success) {
                setSuccess(
                    `✓ Saved ${data.saved_count} questions${data.skipped_count > 0 ? ` (${data.skipped_count} duplicates skipped)` : ''}`
                )

                const savedIds = new Set(selectedQuestions.map(q => q.id))
                setPreviewQuestions(prevQuestions => {
                    const current = Array.isArray(prevQuestions) ? prevQuestions : []
                    return current.filter(q => !savedIds.has(q.id))
                })

                if (onQuestionsAdded) {
                    onQuestionsAdded(data.saved_count)
                }
            } else {
                setError(data.errors?.join('; ') || 'Failed to save questions')
            }
        } catch (err) {
            setError(`Error: ${err.message}`)
            console.error('Batch save error:', err)
        } finally {
            setLoading(false)
        }
    }, [onQuestionsAdded, setPreviewQuestions])

    return {
        loading,
        error,
        success,
        setError,
        setSuccess,
        filteredPreviewQuestions,
        handleFetchPreview,
        handleManualQuestionCreated,
        handleSaveSelected,
        // Job props exposed for UI
        jobs,
        loadingJobs,
        selectedJobId,
        jobDetails,
        loadingDetails,
        selectJob,
        loadJobs
    }
}
