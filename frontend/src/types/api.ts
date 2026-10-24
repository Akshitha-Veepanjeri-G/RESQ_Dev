/**
 * Authoritative TypeScript types matching FastAPI Pydantic schemas in src/resq/api/schemas.py
 */

export type Verdict =
  | 'VERIFIED'
  | 'NO_FAILURE_FOUND'
  | 'REJECTED_STILL_FAILS'
  | 'REJECTED_REGRESSION'
  | 'REJECTED_SYNTAX_ERROR'
  | 'INSUFFICIENT_EVIDENCE'
  | 'TIMEOUT_EXCEEDED'
  | 'LLM_ERROR'
  | 'INFRASTRUCTURE_ERROR';

export type JobStatus =
  | 'PENDING'
  | 'RUNNING_BASELINE'
  | 'REPAIR_CYCLE_1'
  | 'REPAIR_CYCLE_2'
  | 'COMPLETED'
  | 'FAILED'
  | 'INTERRUPTED';

export interface HealthResponse {
  status: 'ok' | 'degraded' | 'unhealthy';
  database_connected: boolean;
  docker_available: boolean;
  version: string;
}

export interface JobCreateRequest {
  source_code: string;
  invariants_code: string;
  target_filename?: string;
  test_filename?: string;
}

export interface JobSummaryResponse {
  job_id: string;
  target_filename: string;
  test_filename: string;
  current_status: JobStatus;
  final_verdict: Verdict | null;
  created_at: string;
}

export interface ExecutionResultResponse {
  exit_code: number;
  stdout: string;
  stderr: string;
  timed_out: boolean;
  duration_seconds: number;
}

export interface FailureArtifactResponse {
  failing_input: unknown;
  exception_type: string | null;
  assertion_message: string | null;
  traceback_raw: string;
  seed: number | null;
  is_reproducible: boolean;
}

export interface CandidatePatchResponse {
  patch_code: string;
  explanation: string;
  provider_name: string;
}

export interface VerificationRunResponse {
  id: string;
  job_id: string;
  run_type: string;
  cycle_index: number;
  verdict: Verdict;
  unified_diff: string | null;
  execution_result: ExecutionResultResponse | null;
  failure_artifact: FailureArtifactResponse | null;
  candidate_patch: CandidatePatchResponse | null;
  executed_at: string;
}

export interface AgentDecisionResponse {
  action: string;
  arguments: Record<string, unknown>;
  reason: string;
  expected_observation: string;
  completion_status: string;
}

export interface AgentObservationResponse {
  tool_name: string;
  success: boolean;
  output: unknown;
  summary: string;
  evidence_payload: Record<string, unknown>;
}

export interface AgentStepResponse {
  id: string;
  cycle_index: number;
  decision: AgentDecisionResponse;
  observation: AgentObservationResponse;
  duration_seconds: number;
  timestamp: string;
}

export interface JobDetailResponse {
  id: string;
  target_filename: string;
  test_filename: string;
  current_status: JobStatus;
  final_verdict: Verdict | null;
  objective?: string;
  execution_mode?: 'mock' | 'live_gemini';
  termination_reason?: string | null;
  runs: VerificationRunResponse[];
  agent_steps?: AgentStepResponse[];
  created_at: string;
  updated_at: string;
}


export interface BenchmarkPreset {
  id: string;
  title: string;
  category: string;
  defectSummary: string;
  expectedVerdict: Verdict;
  targetFilename: string;
  testFilename: string;
  sourceCode: string;
  invariantsCode: string;
}
