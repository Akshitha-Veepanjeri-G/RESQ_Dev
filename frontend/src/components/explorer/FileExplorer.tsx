import React, { useState } from 'react';
import type { BenchmarkPreset, JobSummaryResponse } from '../../types/api';
import { BENCHMARK_PRESETS } from '../../data/benchmarks';

interface FileExplorerProps {
  currentFile: 'target.py' | 'test_target.py';
  onSelectFile: (file: 'target.py' | 'test_target.py') => void;
  onLoadPreset: (preset: BenchmarkPreset) => void;
  recentJobs: JobSummaryResponse[];
  activeJobId: string | null;
  onSelectJob: (jobId: string) => void;
  onRefreshJobs: () => void;
}

export const FileExplorer: React.FC<FileExplorerProps> = ({
  currentFile,
  onSelectFile,
  onLoadPreset,
  recentJobs,
  activeJobId,
  onSelectJob,
  onRefreshJobs,
}) => {
  const [benchmarksOpen, setBenchmarksOpen] = useState(true);
  const [workspaceOpen, setWorkspaceOpen] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(true);

  return (
    <aside className="resq-explorer">
      <div className="explorer-header">
        <span className="explorer-title">EXPLORER</span>
        <button
          className="icon-button-sm"
          onClick={onRefreshJobs}
          title="Refresh Verification History"
        >
          🔄
        </button>
      </div>

      <div className="explorer-section">
        <div
          className="section-header"
          onClick={() => setWorkspaceOpen(!workspaceOpen)}
        >
          <span className="section-arrow">{workspaceOpen ? '▼' : '▶'}</span>
          <span className="section-name">WORKSPACE (IN-MEMORY)</span>
        </div>
        {workspaceOpen && (
          <div className="file-tree">
            <div
              className={`file-item ${
                currentFile === 'target.py' ? 'file-active' : ''
              }`}
              onClick={() => onSelectFile('target.py')}
            >
              <span className="file-icon">🐍</span>
              <span className="file-label">target.py</span>
              <span className="file-tag">Source</span>
            </div>
            <div
              className={`file-item ${
                currentFile === 'test_target.py' ? 'file-active' : ''
              }`}
              onClick={() => onSelectFile('test_target.py')}
            >
              <span className="file-icon">🧪</span>
              <span className="file-label">test_target.py</span>
              <span className="file-tag">Invariants</span>
            </div>
          </div>
        )}
      </div>

      <div className="explorer-section">
        <div
          className="section-header"
          onClick={() => setBenchmarksOpen(!benchmarksOpen)}
        >
          <span className="section-arrow">{benchmarksOpen ? '▼' : '▶'}</span>
          <span className="section-name">BENCHMARK PRESETS (M1–M5)</span>
        </div>
        {benchmarksOpen && (
          <div className="presets-list">
            {BENCHMARK_PRESETS.map((preset) => (
              <div
                key={preset.id}
                className="preset-item"
                onClick={() => onLoadPreset(preset)}
                title={preset.defectSummary}
              >
                <div className="preset-item-header">
                  <span className="preset-icon">📁</span>
                  <span className="preset-title">{preset.title}</span>
                </div>
                <div className="preset-meta">
                  <span className="preset-category">{preset.category}</span>
                  <span className="preset-verdict-tag">{preset.expectedVerdict}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="explorer-section explorer-history-section">
        <div
          className="section-header"
          onClick={() => setHistoryOpen(!historyOpen)}
        >
          <span className="section-arrow">{historyOpen ? '▼' : '▶'}</span>
          <span className="section-name">VERIFICATION HISTORY</span>
        </div>
        {historyOpen && (
          <div className="history-list">
            {recentJobs.length === 0 ? (
              <div className="empty-history">No verification jobs yet.</div>
            ) : (
              recentJobs.map((j) => {
                const isVerified = j.final_verdict === 'VERIFIED';
                const isRejected = j.final_verdict?.startsWith('REJECTED');
                return (
                  <div
                    key={j.job_id}
                    className={`history-item ${
                      activeJobId === j.job_id ? 'history-active' : ''
                    }`}
                    onClick={() => onSelectJob(j.job_id)}
                  >
                    <div className="history-item-top">
                      <span className="history-status-indicator">
                        {isVerified ? '🟢' : isRejected ? '🔴' : '⏳'}
                      </span>
                      <span className="history-filename">{j.target_filename}</span>
                    </div>
                    <div className="history-item-bottom">
                      <code className="history-id">{j.job_id.slice(0, 8)}</code>
                      <span className="history-status-text">
                        {j.final_verdict || j.current_status}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>

      <div className="explorer-footer">
        <span className="security-notice">
          🔒 Safe Sandbox: Isolated temporary workspace only
        </span>
      </div>
    </aside>
  );
};
