import React, { useState } from 'react';

interface CodeViewerProps {
  currentFile: 'target.py' | 'test_target.py';
  sourceCode: string;
  invariantsCode: string;
  onSourceChange: (code: string) => void;
  onInvariantsChange: (code: string) => void;
  onSelectRange: (selection: { startLine: number; endLine: number; text: string }) => void;
  onRunVerification: () => void;
  isSubmitting: boolean;
  submissionError: string | null;
}

export const CodeViewer: React.FC<CodeViewerProps> = ({
  currentFile,
  sourceCode,
  invariantsCode,
  onSourceChange,
  onInvariantsChange,
  onSelectRange,
  onRunVerification,
  isSubmitting,
  submissionError,
}) => {
  const [isEditing, setIsEditing] = useState(true);
  const activeCode = currentFile === 'target.py' ? sourceCode : invariantsCode;
  const lines = activeCode.split('\n');

  const handleTextareaSelect = (e: React.SyntheticEvent<HTMLTextAreaElement>) => {
    const target = e.currentTarget;
    const startPos = target.selectionStart;
    const endPos = target.selectionEnd;

    if (startPos !== endPos) {
      const selectedText = activeCode.substring(startPos, endPos);
      const textBefore = activeCode.substring(0, startPos);
      const startLine = textBefore.split('\n').length;
      const endLine = startLine + selectedText.split('\n').length - 1;

      onSelectRange({
        startLine,
        endLine,
        text: selectedText,
      });
    }
  };

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newText = e.target.value;
    if (currentFile === 'target.py') {
      onSourceChange(newText);
    } else {
      onInvariantsChange(newText);
    }
  };

  return (
    <div className="resq-editor-container">
      <div className="editor-tabbar">
        <div className="tab-group">
          <div className="editor-tab active-tab">
            <span className="tab-icon">
              {currentFile === 'target.py' ? '🐍' : '🧪'}
            </span>
            <span className="tab-filename">{currentFile}</span>
            <span className="tab-mode-tag">
              {currentFile === 'target.py' ? 'Target Code' : 'Invariants Harness'}
            </span>
          </div>
        </div>

        <div className="editor-actions">
          <button
            className={`action-btn-secondary ${isEditing ? 'btn-active' : ''}`}
            onClick={() => setIsEditing(!isEditing)}
            title="Toggle Edit / Read-Only Mode"
          >
            {isEditing ? '✏️ Edit Mode' : '👁️ View Mode'}
          </button>
          <button
            className="action-btn-primary"
            onClick={onRunVerification}
            disabled={isSubmitting}
          >
            {isSubmitting ? (
              <>
                <span className="btn-spinner" /> Running Gate...
              </>
            ) : (
              '🚀 Run Verification Gate'
            )}
          </button>
        </div>
      </div>

      {submissionError && (
        <div className="editor-error-banner">
          <span>⚠️ {submissionError}</span>
        </div>
      )}

      <div className="editor-content-pane">
        <div className="line-numbers">
          {lines.map((_, i) => (
            <div key={i + 1} className="line-number-cell">
              {i + 1}
            </div>
          ))}
        </div>

        <div className="code-surface">
          {isEditing ? (
            <textarea
              className="code-textarea"
              value={activeCode}
              onChange={handleTextChange}
              onSelect={handleTextareaSelect}
              spellCheck={false}
              wrap="off"
              placeholder="# Python code..."
            />
          ) : (
            <pre className="code-read-only">
              {lines.map((line, idx) => (
                <div
                  key={idx}
                  className="code-line"
                  onClick={() =>
                    onSelectRange({
                      startLine: idx + 1,
                      endLine: idx + 1,
                      text: line,
                    })
                  }
                >
                  {line || ' '}
                </div>
              ))}
            </pre>
          )}
        </div>
      </div>

      <div className="editor-statusbar">
        <span className="status-item">Python 3.11+</span>
        <span className="status-item">UTF-8</span>
        <span className="status-item">Lines: {lines.length}</span>
        <span className="status-item">Chars: {activeCode.length}</span>
        <span className="status-item highlight-tip">
          💡 Select any code line to inspect in Point-and-Ask panel
        </span>
      </div>
    </div>
  );
};
