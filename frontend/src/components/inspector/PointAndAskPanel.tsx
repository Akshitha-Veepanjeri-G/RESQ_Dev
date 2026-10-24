import React, { useState } from 'react';
import type { VerificationRunResponse } from '../../types/api';

interface PointAndAskPanelProps {
  selection: { startLine: number; endLine: number; text: string } | null;
  currentFile: string;
  latestRun: VerificationRunResponse | null;
}

export const PointAndAskPanel: React.FC<PointAndAskPanelProps> = ({
  selection,
  currentFile,
  latestRun,
}) => {
  const [question, setQuestion] = useState('');
  const candidatePatch = latestRun?.candidate_patch;

  const handleAskSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // Do not fake results or call non-existent backend endpoints
    // This is handled by displaying the backend capability boundary notice.
  };

  return (
    <div className="resq-inspector-panel">
      <div className="inspector-header">
        <span className="inspector-title">AI INSPECTOR & POINT-AND-ASK</span>
      </div>

      {/* Selected Code Scope */}
      <div className="inspector-section">
        <div className="section-subtitle">
          <span>📍 Target Code Context</span>
          {selection && (
            <span className="selection-badge">
              {currentFile}:{selection.startLine}-{selection.endLine}
            </span>
          )}
        </div>
        {selection ? (
          <div className="selected-code-preview">
            <pre>
              <code>{selection.text.trim() || '# Empty selection'}</code>
            </pre>
          </div>
        ) : (
          <div className="empty-selection-prompt">
            Highlight or click any line in the code viewer to focus inspection context.
          </div>
        )}
      </div>

      {/* Point-and-Ask Interface */}
      <div className="inspector-section">
        <div className="section-subtitle">
          <span>💬 Point-and-Ask Code Inquiry</span>
        </div>
        <form onSubmit={handleAskSubmit} className="ask-form">
          <textarea
            className="ask-input"
            rows={3}
            placeholder={
              selection
                ? `Ask about lines ${selection.startLine}-${selection.endLine} in ${currentFile}...`
                : 'Ask a question about this Python module...'
            }
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <div className="ask-actions">
            <button
              type="submit"
              className="ask-submit-btn"
              disabled={!question.trim()}
            >
              Analyze Selection
            </button>
          </div>
        </form>

        {/* Backend Endpoint Gap Notice (Requirement 6 & 7) */}
        <div className="backend-gap-notice">
          <div className="gap-notice-header">
            <span className="gap-icon">ℹ️</span>
            <strong>Backend Capability Status: Planned Extension</strong>
          </div>
          <p className="gap-notice-text">
            In the current M0–M5 specification, LLM providers (Gemini / Mock) operate strictly
            inside the automated verification & repair loop. An ad-hoc conversational endpoint
            (e.g., <code>POST /api/v1/explain</code>) is not yet exposed by the FastAPI backend.
          </p>
        </div>
      </div>

      {/* Verified AI Explanation & Source References Area */}
      <div className="inspector-section ai-explanation-section">
        <div className="section-subtitle">
          <span>🧠 Verified Patch Explanation & Analysis</span>
          {candidatePatch && (
            <span className="provider-badge">
              Provider: {candidatePatch.provider_name}
            </span>
          )}
        </div>

        {candidatePatch?.explanation ? (
          <div className="explanation-card">
            <div className="explanation-body">
              <p>{candidatePatch.explanation}</p>
            </div>

            {candidatePatch.patch_code && (
              <div className="source-reference-box">
                <span className="source-reference-title">
                  🔍 Synthesized Replacement:
                </span>
                <pre className="patch-preview">
                  <code>{candidatePatch.patch_code.slice(0, 300)}...</code>
                </pre>
              </div>
            )}
          </div>
        ) : latestRun ? (
          <div className="no-explanation-box">
            <span>
              Run ({latestRun.run_type}) concluded with verdict{' '}
              <code>{latestRun.verdict}</code> without generating a candidate patch explanation.
            </span>
          </div>
        ) : (
          <div className="empty-explanation-prompt">
            Run the Verification Gate to synthesize candidate repairs and generate evidence-backed explanations.
          </div>
        )}
      </div>
    </div>
  );
};
