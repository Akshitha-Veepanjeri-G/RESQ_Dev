import type {
  HealthResponse,
  JobCreateRequest,
  JobDetailResponse,
  JobSummaryResponse,
} from '../types/api';

export class ApiError extends Error {
  statusCode?: number;
  detail: string;

  constructor(detail: string, statusCode?: number) {
    super(detail);
    this.name = 'ApiError';
    this.detail = detail;
    this.statusCode = statusCode;
  }
}

const BASE_URL = '/api/v1';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail = `Request failed with status ${res.status}`;
    try {
      const data = await res.json();
      if (data && typeof data === 'object') {
        if (typeof data.detail === 'string') {
          errorDetail = data.detail;
        } else if (Array.isArray(data.detail)) {
          // Pydantic validation error array
          errorDetail = data.detail
            .map((e: { loc?: string[]; msg?: string }) => `${e.loc?.join('.') || ''}: ${e.msg || ''}`)
            .join('; ');
        }
      }
    } catch {
      // Use fallback errorDetail if JSON parsing fails
    }
    throw new ApiError(errorDetail, res.status);
  }

  return res.json() as Promise<T>;
}

export const resqApi = {
  async checkHealth(): Promise<HealthResponse> {
    try {
      const res = await fetch(`${BASE_URL}/health`);
      if (res.status === 503) {
        // Backend returns 503 if SQLite is unreachable
        const data = await res.json().catch(() => ({}));
        return {
          status: 'unhealthy',
          database_connected: Boolean(data.detail?.database_connected),
          docker_available: Boolean(data.detail?.docker_available),
          version: data.detail?.version || '0.1.0',
        };
      }
      return await handleResponse<HealthResponse>(res);
    } catch (err) {
      if (err instanceof ApiError) {
        throw err;
      }
      // Connection failure / server offline
      return {
        status: 'unhealthy',
        database_connected: false,
        docker_available: false,
        version: 'offline',
      };
    }
  },

  async submitJob(payload: JobCreateRequest): Promise<JobSummaryResponse> {
    const res = await fetch(`${BASE_URL}/jobs`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        source_code: payload.source_code,
        invariants_code: payload.invariants_code,
        target_filename: payload.target_filename?.trim() || 'target.py',
        test_filename: payload.test_filename?.trim() || 'test_target.py',
      }),
    });
    return handleResponse<JobSummaryResponse>(res);
  },

  async getJobDetail(jobId: string): Promise<JobDetailResponse> {
    const res = await fetch(`${BASE_URL}/jobs/${encodeURIComponent(jobId)}`);
    return handleResponse<JobDetailResponse>(res);
  },

  async getJobTrace(jobId: string): Promise<import('../types/api').AgentStepResponse[]> {
    const res = await fetch(`${BASE_URL}/jobs/${encodeURIComponent(jobId)}/trace`);
    return handleResponse<import('../types/api').AgentStepResponse[]>(res);
  },

  async listJobs(limit = 25, offset = 0): Promise<JobSummaryResponse[]> {
    const res = await fetch(`${BASE_URL}/jobs?limit=${limit}&offset=${offset}`);
    return handleResponse<JobSummaryResponse[]>(res);
  },
};

