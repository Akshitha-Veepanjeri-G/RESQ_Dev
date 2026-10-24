import { useState, useEffect, useRef, useCallback } from 'react';
import type {
  BenchmarkPreset,
  HealthResponse,
  JobDetailResponse,
  JobSummaryResponse,
} from './types/api';
import { resqApi, ApiError } from './services/apiClient';
import { BENCHMARK_PRESETS } from './data/benchmarks';
import { Header } from './components/layout/Header';
import { FileExplorer } from './components/explorer/FileExplorer';
import { CodeViewer } from './components/editor/CodeViewer';
import { PointAndAskPanel } from './components/inspector/PointAndAskPanel';
import { VerificationView } from './components/verification/VerificationView';

export function App() {
  // Backend & Diagnostics State
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobSummaryResponse[]>([]);

  // Workspace & Editor State
  const [currentFile, setCurrentFile] = useState<'target.py' | 'test_target.py'>('target.py');
  const [sourceCode, setSourceCode] = useState<string>(BENCHMARK_PRESETS[0].sourceCode);
  const [invariantsCode, setInvariantsCode] = useState<string>(BENCHMARK_PRESETS[0].invariantsCode);

  // Inspector & Code Selection State
  const [selection, setSelection] = useState<{
    startLine: number;
    endLine: number;
    text: string;
  } | null>(null);

  // Verification & Active Job State
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeJobDetail, setActiveJobDetail] = useState<JobDetailResponse | null>(null);
  const [isLoadingJob, setIsLoadingJob] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [submissionError, setSubmissionError] = useState<string | null>(null);

  // Polling State
  const [isPolling, setIsPolling] = useState<boolean>(false);
  const [pollCount, setPollCount] = useState<number>(0);
  const pollTimerRef = useRef<number | null>(null);

  // 1. Initial Health and Recent Jobs Fetch
  const refreshHealth = useCallback(async () => {
    try {
      const h = await resqApi.checkHealth();
      setHealth(h);
    } catch {
      setHealth({
        status: 'unhealthy',
        database_connected: false,
        docker_available: false,
        version: 'offline',
      });
    }
  }, []);

  const refreshRecentJobs = useCallback(async () => {
    try {
      const jobs = await resqApi.listJobs(25, 0);
      setRecentJobs(jobs);
    } catch {
      // Backend offline or empty
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    const init = async () => {
      try {
        const [h, jobs] = await Promise.all([
          resqApi.checkHealth().catch(() => ({
            status: 'unhealthy' as const,
            database_connected: false,
            docker_available: false,
            version: 'offline',
          })),
          resqApi.listJobs(25, 0).catch(() => []),
        ]);
        if (!ignore) {
          setHealth(h);
          setRecentJobs(jobs);
        }
      } catch {
        // Fallback
      }
    };
    init();
    return () => {
      ignore = true;
    };
  }, []);

  // 2. Fetch Job Details when activeJobId changes
  const loadJobDetail = useCallback(async (jobId: string) => {
    setIsLoadingJob(true);
    try {
      const detail = await resqApi.getJobDetail(jobId);
      setActiveJobDetail(detail);

      // Check if job is still in progress
      const activeStatuses = ['PENDING', 'RUNNING_BASELINE', 'REPAIR_CYCLE_1', 'REPAIR_CYCLE_2'];
      if (activeStatuses.includes(detail.current_status)) {
        setIsPolling(true);
      } else {
        setIsPolling(false);
        setPollCount(0);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setSubmissionError(`Failed to load job ${jobId}: ${err.detail}`);
      }
    } finally {
      setIsLoadingJob(false);
    }
  }, []);

  // 3. Polling loop
  useEffect(() => {
    if (!isPolling || !activeJobId || pollCount >= 60) {
      if (pollTimerRef.current) {
        window.clearTimeout(pollTimerRef.current);
      }
      return;
    }

    pollTimerRef.current = window.setTimeout(async () => {
      try {
        const detail = await resqApi.getJobDetail(activeJobId);
        setActiveJobDetail(detail);

        const terminalStatuses = ['COMPLETED', 'FAILED', 'INTERRUPTED'];
        if (terminalStatuses.includes(detail.current_status)) {
          setIsPolling(false);
          setPollCount(0);
          refreshRecentJobs();
        } else {
          setPollCount((prev) => {
            const next = prev + 1;
            if (next >= 60) {
              setIsPolling(false);
            }
            return next;
          });
        }
      } catch {
        setIsPolling(false);
      }
    }, 2000);

    return () => {
      if (pollTimerRef.current) {
        window.clearTimeout(pollTimerRef.current);
      }
    };
  }, [isPolling, activeJobId, pollCount, refreshRecentJobs]);

  // 4. Job Submission Handler
  const handleRunVerification = async () => {
    setSubmissionError(null);

    if (!sourceCode.trim()) {
      setSubmissionError('Target source code cannot be empty.');
      return;
    }
    if (!invariantsCode.trim()) {
      setSubmissionError('Test harness invariants code cannot be empty.');
      return;
    }
    if (health && !health.database_connected) {
      setSubmissionError('Backend database is unreachable. Check FastAPI service.');
      return;
    }

    setIsSubmitting(true);
    try {
      const summary = await resqApi.submitJob({
        source_code: sourceCode,
        invariants_code: invariantsCode,
        target_filename: 'target.py',
        test_filename: 'test_target.py',
      });

      setActiveJobId(summary.job_id);
      setIsPolling(true);
      setPollCount(0);
      refreshRecentJobs();
      loadJobDetail(summary.job_id);
    } catch (err) {
      if (err instanceof ApiError) {
        setSubmissionError(err.detail);
      } else {
        setSubmissionError('Failed to submit verification job.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // 5. Preset Loader
  const handleLoadPreset = (preset: BenchmarkPreset) => {
    setSourceCode(preset.sourceCode);
    setInvariantsCode(preset.invariantsCode);
    setCurrentFile('target.py');
    setSelection(null);
    setSubmissionError(null);
  };

  // 6. Job Selection
  const handleSelectJob = (jobId: string) => {
    setActiveJobId(jobId);
    setSubmissionError(null);
    loadJobDetail(jobId);
  };

  const latestRun =
    activeJobDetail && activeJobDetail.runs.length > 0
      ? activeJobDetail.runs[activeJobDetail.runs.length - 1]
      : null;

  return (
    <div className="resq-app-container">
      {/* Top Application Bar */}
      <Header
        health={health}
        activeJobId={activeJobId}
        isPolling={isPolling}
        pollCount={pollCount}
        onRefreshHealth={refreshHealth}
      />

      {/* Main IDE Workspace */}
      <div className="resq-ide-body">
        {/* Left Column: Explorer & Presets */}
        <FileExplorer
          currentFile={currentFile}
          onSelectFile={setCurrentFile}
          onLoadPreset={handleLoadPreset}
          recentJobs={recentJobs}
          activeJobId={activeJobId}
          onSelectJob={handleSelectJob}
          onRefreshJobs={refreshRecentJobs}
        />

        {/* Center Column: Source Code Viewer & Editor */}
        <main className="resq-center-stage">
          <CodeViewer
            currentFile={currentFile}
            sourceCode={sourceCode}
            invariantsCode={invariantsCode}
            onSourceChange={setSourceCode}
            onInvariantsChange={setInvariantsCode}
            onSelectRange={setSelection}
            onRunVerification={handleRunVerification}
            isSubmitting={isSubmitting}
            submissionError={submissionError}
          />

          {/* Bottom Pane: Verification View, Diffs & Reproducers */}
          <VerificationView
            job={activeJobDetail}
            isLoading={isLoadingJob}
            isPolling={isPolling}
            pollCount={pollCount}
            originalSource={sourceCode}
          />
        </main>

        {/* Right Column: AI Point-and-Ask Inspector */}
        <PointAndAskPanel
          selection={selection}
          currentFile={currentFile}
          latestRun={latestRun}
        />
      </div>
    </div>
  );
}

export default App;
