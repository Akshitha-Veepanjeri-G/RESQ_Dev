import React from 'react';
import type { HealthResponse } from '../../types/api';

interface HeaderProps {
  health: HealthResponse | null;
  activeJobId: string | null;
  isPolling: boolean;
  pollCount: number;
  onRefreshHealth: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  health,
  activeJobId,
  isPolling,
  pollCount,
  onRefreshHealth,
}) => {
  const getStatusBadge = () => {
    if (!health) {
      return <span className="status-pill status-unhealthy">API: Checking...</span>;
    }
    if (health.status === 'ok') {
      return <span className="status-pill status-ok">API: Online (v0.1.0)</span>;
    }
    if (health.status === 'degraded') {
      return <span className="status-pill status-degraded">API: Degraded (Docker Offline)</span>;
    }
    return <span className="status-pill status-unhealthy">API: Offline</span>;
  };

  return (
    <header className="resq-topbar">
      <div className="resq-brand">
        <span className="brand-shield">🛡️</span>
        <span className="brand-name">RESQ Dev</span>
        <span className="brand-divider">/</span>
        <span className="brand-sub">Verification & Repair IDE</span>
      </div>

      <div className="resq-topbar-center">
        {activeJobId ? (
          <div className="active-job-indicator">
            <span className="active-job-dot" />
            <span className="active-job-label">Active Job:</span>
            <code className="active-job-id">{activeJobId.slice(0, 8)}</code>
            {isPolling && (
              <span className="polling-badge">
                Testing in Docker ({pollCount}/60)...
              </span>
            )}
          </div>
        ) : (
          <span className="idle-indicator">Workspace Ready</span>
        )}
      </div>

      <div className="resq-topbar-actions">
        <div className="health-indicators">
          {getStatusBadge()}
          <span
            className={`status-pill ${
              health?.database_connected ? 'status-ok' : 'status-unhealthy'
            }`}
          >
            DB: {health?.database_connected ? 'SQLite' : 'Down'}
          </span>
          <span
            className={`status-pill ${
              health?.docker_available ? 'status-ok' : 'status-degraded'
            }`}
          >
            Sandbox: {health?.docker_available ? 'Ready' : 'Docker Down'}
          </span>
          <span className="status-pill status-ok" title="Autonomous Bounded Verification Agent">
            Agent: Active
          </span>
        </div>

        <button
          className="icon-button"
          onClick={onRefreshHealth}
          title="Refresh Backend Health"
        >
          🔄
        </button>
      </div>
    </header>
  );
};
