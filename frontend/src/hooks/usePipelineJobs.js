import { useState, useEffect, useCallback } from 'react';

/**
 * Hook to manage pipeline jobs fetching and details.
 * @param {string} pipelineType - Optional pipeline type to filter by (e.g. 'forecast', 'evidence')
 * @param {number} refreshInterval - Polling interval in ms (default 5000)
 */
export const usePipelineJobs = (pipelineType = null, refreshInterval = 5000) => {
    const [jobs, setJobs] = useState([]);
    const [loadingJobs, setLoadingJobs] = useState(false);
    const [selectedJobId, setSelectedJobId] = useState(null);
    const [jobDetails, setJobDetails] = useState(null);
    const [loadingDetails, setLoadingDetails] = useState(false);

    // Fetch recent jobs list
    const fetchJobs = useCallback(async () => {
        // Ideally we shouldn't show loading spinner on background polls, only first load
        // But we need to know if it's loading initially.
        // We'll manage local 'isPolling' if needed, but for now simple logic.
        try {
            const response = await fetch('/api/pipelines/jobs?limit=20');
            if (!response.ok) throw new Error('Failed to fetch jobs');

            const data = await response.json();

            // Filter if type specified
            let filtered = data;
            if (pipelineType) {
                filtered = data.filter(job => job.pipeline_type === pipelineType);
            }

            setJobs(filtered);
        } catch (error) {
            console.error('Error fetching jobs:', error);
        }
    }, [pipelineType]);

    // Initial load wrapper
    const loadJobs = async () => {
        setLoadingJobs(true);
        await fetchJobs();
        setLoadingJobs(false);
    };

    // Poll for updates
    useEffect(() => {
        loadJobs();
        if (refreshInterval > 0) {
            const interval = setInterval(fetchJobs, refreshInterval);
            return () => clearInterval(interval);
        }
    }, [fetchJobs, refreshInterval]);

    // Handle job selection
    const selectJob = async (jobId) => {
        if (!jobId) {
            setSelectedJobId(null);
            setJobDetails(null);
            setLoadingDetails(false); // Ensure loading state is reset
            return;
        }

        setSelectedJobId(jobId);
        setLoadingDetails(true);
        try {
            const response = await fetch(`/api/pipelines/jobs/${jobId}`);
            if (response.ok) {
                const data = await response.json();
                setJobDetails(data);
            } else {
                console.error('Failed to load job details');
                setJobDetails(null);
            }
        } catch (error) {
            console.error('Error loading job details:', error);
            setJobDetails(null);
        } finally {
            setLoadingDetails(false);
        }
    };

    return {
        jobs,
        loadingJobs,
        loadJobs,        // Manual refresh function
        selectedJobId,
        jobDetails,
        loadingDetails,
        selectJob        // Use this instead of manual separate set states
    };
};
