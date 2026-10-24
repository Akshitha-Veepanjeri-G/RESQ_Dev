import React, { useState } from 'react';
import type { JobDetailResponse, Verdict } from '../../types/api';

interface VerificationViewProps {
  job: JobDetailResponse | null;
  isLoading: boolean;
  isPolling: boolean;
  pollCount: number;
  originalSource: string;
}

export const VerificationView: React.FC<VerificationViewProps> = ({
  job,
  isLoading,
  isPolling,
  pollCount,
  originalSource,
}) => {
  const [activeTab, setActiveTab] = useState<'trace' | 'diff' | 'sideBySide' | 'evidence' | 'logs'>('trace');

  const getToolIcon = (action: string) => {
    switch (action) {
      case 'inspect_source':
        return '🔍';
      case 'inspect_tests':
        return '🧪';
      case 'run_baseline_tests':
        return '⚙️';
      case 'analyze_failure':
        return '🔬';
      case 'inspect_ast':
        return '🌳';
      case 'run_hypothesis_analysis':
        return '🎲';
      case 'generate_candidate_patch':
        return '💡';
      case 'validate_candidate_patch':
        return '🛡️';
      case 'run_verification_tests':
        return '🚀';
      case 'summarize_evidence':
        return '📊';
      case 'stop':
        return '🛑';
      default:
        return '⚡';
    }
  };


  if (isLoading && !job) {
    return (
      <div className="resq-verification-view view-loading">
        <div className="spinner-large" />
        <p>Fetching verification record from backend...</p>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="resq-verification-view view-empty">
        <div className="empty-icon">🛡️</div>
        <h3>No Active Verification Selected</h3>
        <p>
          Select a benchmark preset from the left explorer and click{' '}
          <strong>"Run Verification Gate"</strong>, or choose a past run from history.
        </p>
      </div>
    );
  }

  const latestRun = job.runs.length > 0 ? job.runs[job.runs.length - 1] : null;
  const failureArtifact = latestRun?.failure_artifact;
  const unifiedDiff = latestRun?.unified_diff;
  const execResult = latestRun?.execution_result;
  const patchCode = latestRun?.candidate_patch?.patch_code;

  // Pipeline Stepper calculations
  const getStepClass = (step: 'submit' | 'baseline' | 'discovery' | 'synthesis' | 'reverify' | 'gate') => {
    const status = job.current_status;
    const verdict = job.final_verdict;

    if (step === 'submit') return 'step-done';

    if (step === 'baseline') {
      if (status === 'RUNNING_BASELINE') return 'step-active';
      if (['REPAIR_CYCLE_1', 'REPAIR_CYCLE_2', 'COMPLETED', 'FAILED'].includes(status)) {
        return 'step-done';
      }
      return 'step-pending';
    }

    if (step === 'discovery') {
      if (status === 'RUNNING_BASELINE') return 'step-pending';
      if (['REPAIR_CYCLE_1', 'REPAIR_CYCLE_2', 'COMPLETED'].includes(status)) return 'step-done';
      return 'step-pending';
    }

    if (step === 'synthesis') {
      if (['REPAIR_CYCLE_1', 'REPAIR_CYCLE_2'].includes(status)) return 'step-active';
      if (status === 'COMPLETED' && verdict !== 'NO_FAILURE_FOUND') return 'step-done';
      return 'step-pending';
    }

    if (step === 'reverify') {
      if (['REPAIR_CYCLE_1', 'REPAIR_CYCLE_2'].includes(status)) return 'step-active';
      if (status === 'COMPLETED' && verdict !== 'NO_FAILURE_FOUND') return 'step-done';
      return 'step-pending';
    }

    if (step === 'gate') {
      if (status === 'COMPLETED') {
        return verdict === 'VERIFIED' ? 'step-verified' : 'step-done';
      }
      return 'step-pending';
    }

    return 'step-pending';
  };

  const getVerdictBannerClass = (verdict: Verdict | null) => {
    if (!verdict) return 'verdict-in-progress';
    if (verdict === 'VERIFIED') return 'verdict-verified';
    if (verdict === 'NO_FAILURE_FOUND') return 'verdict-clean';
    if (verdict.startsWith('REJECTED')) return 'verdict-rejected';
    return 'verdict-error';
  };

  const handleDownloadPatch = () => {
    if (!unifiedDiff) return;
    const blob = new Blob([unifiedDiff], { type: 'text/x-diff' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `resq_${job.id.slice(0, 8)}.patch`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleDownloadPy = () => {
    if (!patchCode) return;
    const blob = new Blob([patchCode], { type: 'text/x-python' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = job.target_filename || 'candidate_patch.py';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="resq-verification-view">
      {/* 1. Pipeline Stepper */}
      <div className="stepper-container">
        <div className={`step-item ${getStepClass('submit')}`}>1. Ingestion</div>
        <div className="step-arrow">→</div>
        <div className={`step-item ${getStepClass('baseline')}`}>2. Docker Baseline</div>
        <div className="step-arrow">→</div>
        <div className={`step-item ${getStepClass('discovery')}`}>3. Hypothesis Shrink</div>
        <div className="step-arrow">→</div>
        <div className={`step-item ${getStepClass('synthesis')}`}>4. Patch Synthesis</div>
        <div className="step-arrow">→</div>
        <div className={`step-item ${getStepClass('reverify')}`}>5. Sandbox Re-verify</div>
        <div className="step-arrow">→</div>
        <div className={`step-item ${getStepClass('gate')}`}>6. Human Review Gate</div>
      </div>

      {/* 2. Verdict Banner */}
      <div className={`verdict-banner ${getVerdictBannerClass(job.final_verdict)}`}>
        <div className="verdict-main">
          <div className="verdict-badge-label">
            {job.final_verdict ? `VERDICT: ${job.final_verdict}` : `STATUS: ${job.current_status}`}
          </div>
          <div className="verdict-subtext">
            {job.final_verdict === 'VERIFIED' && (
              <span>
                🎉 Candidate patch resolved concrete reproducer and passed all regression test gates inside the Docker sandbox.
              </span>
            )}
            {job.final_verdict === 'NO_FAILURE_FOUND' && (
              <span>
                ⚪ All baseline tests and property-based invariants passed cleanly. No bug detected.
              </span>
            )}
            {job.final_verdict?.startsWith('REJECTED') && (
              <span>
                🛡️ Verification Gate rejected candidate patch to prevent silent bugs or regressions.
              </span>
            )}
            {!job.final_verdict && isPolling && (
              <span>
                ⏳ In-flight verification in isolated Docker sandbox (Cycle {pollCount}/60)...
              </span>
            )}
          </div>
        </div>

        {execResult && (
          <div className="exec-metrics">
            <span className="metric-pill">Exit Code: {execResult.exit_code}</span>
            <span className="metric-pill">Duration: {execResult.duration_seconds.toFixed(2)}s</span>
            <span className="metric-pill">
              Timed Out: {execResult.timed_out ? 'Yes' : 'No'}
            </span>
          </div>
        )}
      </div>

      {/* 2.5 Agent Objective & Execution Mode Banner */}
      <div className="agent-objective-banner">

        <div className="agent-objective-header">
          <div className="agent-objective-title">
            <span>🎯 Verification Objective</span>
          </div>
          <span
            className={`agent-mode-badge ${
              job.execution_mode === 'live_gemini' ? 'agent-mode-live' : 'agent-mode-mock'
            }`}
          >
            {job.execution_mode === 'live_gemini'
              ? '🤖 Live Gemini Agentic Loop'
              : '🛡️ Mock Deterministic Agent Loop'}
          </span>
        </div>
        <div className="agent-objective-text">
          {job.objective ||
            'Investigate failure, evaluate defect hypothesis, and verify candidate patch against edge-case invariants.'}
        </div>
        {job.termination_reason && (
          <div className="agent-termination-banner">
            <strong>Termination:</strong> {job.termination_reason}
          </div>
        )}
      </div>

      {/* 3. Tab navigation for Results */}
      <div className="verification-tabs">
        <button
          className={`vtab ${activeTab === 'trace' ? 'vtab-active' : ''}`}
          onClick={() => setActiveTab('trace')}
        >
          🤖 Agent Decision Trace ({job.agent_steps?.length || 0})
        </button>
        <button
          className={`vtab ${activeTab === 'diff' ? 'vtab-active' : ''}`}
          onClick={() => setActiveTab('diff')}
        >
          📄 Unified Diff (.patch)
        </button>
        <button
          className={`vtab ${activeTab === 'sideBySide' ? 'vtab-active' : ''}`}
          onClick={() => setActiveTab('sideBySide')}
        >
          ⚖️ Side-by-Side Comparison
        </button>
        <button
          className={`vtab ${activeTab === 'evidence' ? 'vtab-active' : ''}`}
          onClick={() => setActiveTab('evidence')}
        >
          🔍 Failure Evidence {failureArtifact ? '(Captured)' : ''}
        </button>
        <button
          className={`vtab ${activeTab === 'logs' ? 'vtab-active' : ''}`}
          onClick={() => setActiveTab('logs')}
        >
          📋 Sandbox Output Logs
        </button>
      </div>

      {/* 4. Tab Content */}
      <div className="verification-tab-content">
        {activeTab === 'trace' && (
          <div className="agent-trace-tab">
            {job.agent_steps && job.agent_steps.length > 0 ? (
              <div className="agent-steps-timeline">
                {job.agent_steps.map((step) => (
                  <div key={step.id || step.cycle_index} className="agent-step-card">
                    <div className="agent-step-card-header">
                      <div className="agent-step-lead">
                        <span className="agent-step-cycle-badge">Cycle {step.cycle_index}</span>
                        <span className="agent-tool-badge">
                          {getToolIcon(step.decision.action)} {step.decision.action}
                        </span>
                      </div>
                      <div className="agent-step-meta">
                        <span
                          className={`agent-status-pill ${
                            step.observation.success ? 'status-success' : 'status-failure'
                          }`}
                        >
                          {step.observation.success ? 'Success' : 'Failed / Blocked'}
                        </span>
                        <span className="agent-step-duration">
                          ⏱️ {step.duration_seconds.toFixed(2)}s
                        </span>
                      </div>
                    </div>
                    <div className="agent-step-body">
                      <div className="agent-reason-row">
                        <span className="agent-field-title">Model Rationale (Why this action):</span>
                        <p className="agent-reason-text">{step.decision.reason}</p>
                      </div>
                      <div className="agent-expected-row">
                        <span className="agent-field-title">Expected Observation:</span>
                        <p className="agent-expected-text">{step.decision.expected_observation}</p>
                      </div>
                      <div className="agent-obs-row">
                        <span className="agent-field-title">Tool Observation:</span>
                        <div className="agent-obs-summary">{step.observation.summary}</div>
                        {step.observation.evidence_payload &&
                          Object.keys(step.observation.evidence_payload).length > 0 && (
                            <div className="agent-evidence-tags">
                              {Object.entries(step.observation.evidence_payload).map(
                                ([key, val]) => (
                                  <span key={key} className="agent-evidence-tag">
                                    {key}: {String(val)}
                                  </span>
                                )
                              )}
                            </div>
                          )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-diff-notice">
                No autonomous agent decision steps recorded for this job.
              </div>
            )}
          </div>
        )}

        {activeTab === 'diff' && (

          <div className="diff-view-tab">
            {unifiedDiff ? (
              <>
                <div className="diff-toolbar">
                  <div className="git-apply-snippet">
                    <span className="snippet-label">Terminal command:</span>
                    <code>git apply resq_{job.id.slice(0, 8)}.patch</code>
                  </div>
                  <div className="download-actions">
                    <button className="btn-download" onClick={handleDownloadPatch}>
                      📥 Download .patch
                    </button>
                    {patchCode && (
                      <button className="btn-download" onClick={handleDownloadPy}>
                        📄 Download Fixed .py
                      </button>
                    )}
                  </div>
                </div>
                <pre className="diff-code-block">
                  <code>{unifiedDiff}</code>
                </pre>
              </>
            ) : (
              <div className="empty-diff-notice">
                No unified diff available for this verification run.
              </div>
            )}
          </div>
        )}

        {activeTab === 'sideBySide' && (
          <div className="side-by-side-tab">
            <div className="comparison-col">
              <div className="col-header red-header">
                <span>🔴 Original Buggy Source ({job.target_filename})</span>
              </div>
              <pre className="comparison-code-block">
                <code>{originalSource || '# Original code not cached'}</code>
              </pre>
            </div>
            <div className="comparison-col">
              <div className="col-header green-header">
                <span>🟢 Candidate Fix (Verified in Sandbox)</span>
              </div>
              <pre className="comparison-code-block">
                <code>{patchCode || '# No candidate patch generated'}</code>
              </pre>
            </div>
          </div>
        )}

        {activeTab === 'evidence' && (
          <div className="evidence-tab">
            {failureArtifact ? (
              <div className="evidence-grid">
                <div className="evidence-card">
                  <span className="evidence-label">Exception Type</span>
                  <div className="evidence-value">{failureArtifact.exception_type || 'None'}</div>
                </div>
                <div className="evidence-card">
                  <span className="evidence-label">Hypothesis Random Seed</span>
                  <div className="evidence-value">
                    {failureArtifact.seed !== null ? failureArtifact.seed : 'None'}
                  </div>
                </div>
                <div className="evidence-card">
                  <span className="evidence-label">Assertion Message</span>
                  <div className="evidence-value">{failureArtifact.assertion_message || 'None'}</div>
                </div>
                <div className="evidence-card">
                  <span className="evidence-label">Engine Reproducible</span>
                  <div className="evidence-value">
                    {failureArtifact.is_reproducible ? 'Yes (Deterministic)' : 'No'}
                  </div>
                </div>
                <div className="evidence-card-full">
                  <span className="evidence-label">Minimized Failing Input (Shrunk by Hypothesis)</span>
                  <pre className="json-box">
                    <code>
                      {typeof failureArtifact.failing_input === 'object'
                        ? JSON.stringify(failureArtifact.failing_input, null, 2)
                        : String(failureArtifact.failing_input)}
                    </code>
                  </pre>
                </div>
                {failureArtifact.traceback_raw && (
                  <div className="evidence-card-full">
                    <span className="evidence-label">Captured Pytest Traceback</span>
                    <pre className="traceback-box">
                      <code>{failureArtifact.traceback_raw}</code>
                    </pre>
                  </div>
                )}
              </div>
            ) : (
              <div className="empty-evidence-notice">
                No failure artifacts recorded (tests executed cleanly).
              </div>
            )}
          </div>
        )}

        {activeTab === 'logs' && (
          <div className="logs-tab">
            {execResult ? (
              <div className="logs-container">
                <div className="log-section">
                  <span className="log-title">Standard Output (stdout):</span>
                  <pre className="log-box">
                    <code>{execResult.stdout || '(Empty stdout)'}</code>
                  </pre>
                </div>
                {execResult.stderr && (
                  <div className="log-section">
                    <span className="log-title">Standard Error (stderr):</span>
                    <pre className="log-box stderr-box">
                      <code>{execResult.stderr}</code>
                    </pre>
                  </div>
                )}
              </div>
            ) : (
              <div className="empty-logs-notice">No execution output captured.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
