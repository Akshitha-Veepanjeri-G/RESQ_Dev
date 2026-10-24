"""Google Gemini LLM provider using the official google-genai SDK with structured output."""

import json
from typing import Any, Optional
from pydantic import BaseModel, Field

from resq.config import Settings, get_settings
from resq.llm.base import LLMProvider
from resq.llm.exceptions import LLMProviderError
from resq.models import CandidatePatch, FailureArtifact


class StructuredPatchResponse(BaseModel):
    """Strict schema for candidate patch generation."""

    explanation: str = Field(
        description="Concise root-cause analysis and rationale for the code patch.",
    )
    patch_code: str = Field(
        description="Complete, syntactically valid Python replacement code for the module.",
    )


class StructuredDecisionResponse(BaseModel):
    """Strict schema for agent verification action decisions."""

    action: str = Field(
        description="Selected registered tool name (e.g. inspect_source, run_baseline_tests, analyze_failure, inspect_ast, generate_candidate_patch, validate_candidate_patch, run_verification_tests, summarize_evidence) or 'stop'.",
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments dictionary for the selected tool.",
    )
    reason: str = Field(
        description="Concise evidence-based rationale explaining why this action is selected.",
    )
    expected_observation: str = Field(
        description="What information or outcome the agent expects to observe.",
    )
    completion_status: str = Field(
        default="continue",
        description="One of: continue, completed, needs_human_review, blocked, inconclusive.",
    )



class GeminiLLMProvider(LLMProvider):
    """Real LLM provider using Google Gemini with structured outputs.

    Security & Containment Guarantees:
    - Never passes test harness implementations into the prompt.
    - Treats source code and failure tracebacks as untrusted user inputs.
    - Uses strict structured schema enforcement (StructuredPatchResponse).
    - Configures API timeouts via SDK HttpOptions.
    - Never prints, logs, or transmits credentials into sandboxes.
    - Does not determine the verification verdict (Docker execution alone decides).
    """

    provider_name: str = "gemini"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[Any] = None,
    ):
        """Initializes GeminiLLMProvider.

        Args:
            settings: Optional Settings instance. Defaults to get_settings().
            client: Optional injected GenAI client for testing or custom configuration.
        """
        self.settings = settings or get_settings()
        self._client = client

    def _get_client(self) -> Any:
        """Initializes or returns the GenAI client.

        Raises:
            LLMProviderError: If credentials or required dependencies are missing.
        """
        if self._client is not None:
            return self._client

        if not self.settings.gemini_api_key:
            raise LLMProviderError(
                "Gemini API key is not configured. Set RESQ_GEMINI_API_KEY or configure Settings.",
                provider_name="gemini",
            )

        try:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self.settings.gemini_api_key,
                http_options=types.HttpOptions(
                    timeout=int(self.settings.llm_request_timeout_seconds * 1000)
                ),
            )
            return self._client
        except ImportError:
            raise LLMProviderError(
                "The 'google-genai' package is not installed. "
                "Install it using 'pip install google-genai>=1.0.0'.",
                provider_name="gemini",
            )
        except Exception as exc:
            raise LLMProviderError(
                "Failed to initialize Gemini client due to an unexpected error.",
                provider_name="gemini",
            ) from exc

    def _build_prompt(self, source_code: str, failure: FailureArtifact) -> str:
        """Constructs minimal, isolated repair prompt without leaking test files."""
        evidence_lines = [
            f"Exception Type: {failure.exception_type or 'Unknown'}",
            f"Assertion Message: {failure.assertion_message or 'None'}",
        ]
        if failure.failing_input:
            evidence_lines.append(f"Failing Input: {failure.failing_input}")
        if failure.seed is not None:
            evidence_lines.append(f"Hypothesis Seed: {failure.seed}")

        snippet = failure.traceback_raw.strip()
        if snippet:
            # Include relevant tail of the stack trace
            evidence_lines.append(f"Traceback Snippet:\n{snippet[-1500:]}")

        evidence_str = "\n".join(evidence_lines)

        return (
            "You are an expert Python repair assistant. The following Python module contains a bug "
            "discovered during automated testing.\n\n"
            "=== SOURCE CODE TO REPAIR ===\n"
            f"{source_code}\n\n"
            "=== FAILURE EVIDENCE ===\n"
            f"{evidence_str}\n\n"
            "=== INSTRUCTIONS ===\n"
            "1. Analyze the root cause of the failure using the provided evidence.\n"
            "2. Propose a candidate patch that resolves the issue without introducing regressions.\n"
            "3. Return ONLY a valid JSON object matching the requested schema with 'explanation' and 'patch_code'.\n"
            "4. 'patch_code' must be complete, syntactically valid Python replacement code for the module.\n"
            "5. Do NOT wrap your JSON in markdown code blocks or backticks."
        )

    def generate_patch(self, source_code: str, failure: FailureArtifact) -> CandidatePatch:
        """Synthesizes a candidate patch using Google Gemini with structured JSON output.

        Args:
            source_code: The Python module under repair.
            failure: Structured failure evidence extracted from test execution.

        Returns:
            CandidatePatch containing proposed code and explanation.

        Raises:
            LLMProviderError: On API error, timeout, rate limit, authentication error,
                              or malformed response.
        """
        client = self._get_client()
        prompt = self._build_prompt(source_code, failure)

        try:
            # Dynamically import types if available, otherwise rely on injected client
            try:
                from google.genai import types

                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=StructuredPatchResponse,
                    temperature=self.settings.llm_temperature,
                    http_options=types.HttpOptions(
                        timeout=int(self.settings.llm_request_timeout_seconds * 1000)
                    ),
                )
            except ImportError:
                config = {
                    "response_mime_type": "application/json",
                    "temperature": self.settings.llm_temperature,
                }

            response = client.models.generate_content(
                model=self.settings.gemini_model,
                contents=prompt,
                config=config,
            )

        except TimeoutError as exc:
            raise LLMProviderError(
                f"Gemini API request timed out after {self.settings.llm_request_timeout_seconds}s.",
                provider_name="gemini",
            ) from exc
        except Exception as exc:
            exc_str = str(exc)
            # Safe classification without exposing raw API keys or credentials
            if "429" in exc_str or "quota" in exc_str.lower() or "resourceexhausted" in exc_str.lower():
                raise LLMProviderError(
                    "Gemini API quota or rate limit exceeded.",
                    provider_name="gemini",
                    status_code=429,
                ) from exc
            if "401" in exc_str or "403" in exc_str or "unauthenticated" in exc_str.lower() or "permissiondenied" in exc_str.lower():
                raise LLMProviderError(
                    "Gemini API authentication failed. Verify configured API credentials.",
                    provider_name="gemini",
                    status_code=401,
                ) from exc
            if "timeout" in exc_str.lower() or "deadline" in exc_str.lower():
                raise LLMProviderError(
                    f"Gemini API request timed out after {self.settings.llm_request_timeout_seconds}s.",
                    provider_name="gemini",
                ) from exc

            raise LLMProviderError(
                "Gemini API request failed due to an unexpected provider error.",
                provider_name="gemini",
            ) from exc

        # Extract and validate response content
        raw_text = getattr(response, "text", "") or ""
        parsed_response: Optional[StructuredPatchResponse] = None

        if hasattr(response, "parsed") and response.parsed is not None:
            if isinstance(response.parsed, StructuredPatchResponse):
                parsed_response = response.parsed
            elif isinstance(response.parsed, dict):
                try:
                    parsed_response = StructuredPatchResponse.model_validate(response.parsed)
                except Exception as exc:
                    raise LLMProviderError(
                        f"Parsed response failed schema validation: {exc}",
                        provider_name="gemini",
                    ) from exc

        if parsed_response is None:
            if not raw_text.strip():
                raise LLMProviderError(
                    "Gemini API returned an empty response body.",
                    provider_name="gemini",
                )
            try:
                # Strip code fences if model enclosed JSON despite instructions
                cleaned_text = raw_text.strip()
                if cleaned_text.startswith("```"):
                    lines = cleaned_text.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    cleaned_text = "\n".join(lines).strip()

                parsed_json = json.loads(cleaned_text)
                parsed_response = StructuredPatchResponse.model_validate(parsed_json)
            except Exception as exc:
                raise LLMProviderError(
                    f"Failed to parse structured patch from Gemini response: {exc}",
                    provider_name="gemini",
                ) from exc

        # Validate patch code is non-empty
        if not parsed_response.patch_code or not parsed_response.patch_code.strip():
            raise LLMProviderError(
                "Gemini proposed an empty patch code.",
                provider_name="gemini",
            )

        return CandidatePatch(
            patch_code=parsed_response.patch_code,
            explanation=parsed_response.explanation,
            raw_model_response=raw_text,
            provider_name="gemini",
        )

    def _build_agent_prompt(self, state: Any) -> str:
        """Constructs bounded, structured prompt for agent verification action selection."""
        recent_history = []
        for step in state.recent_steps[-5:]:
            recent_history.append(
                f"- Cycle {step.cycle_index}: Selected '{step.decision.action}' with reason '{step.decision.reason}'. "
                f"Observation: {step.observation.summary}"
            )
        history_str = "\n".join(recent_history) if recent_history else "No actions taken yet."

        evidence_items = []
        if state.has_baseline_run:
            evidence_items.append(f"Baseline tests executed: exit_code={state.baseline_exit_code}, passed={state.baseline_passed}")
        if state.current_failure:
            evidence_items.append(
                f"Failure artifact: reproducible={state.current_failure.is_reproducible}, "
                f"exception={state.current_failure.exception_type}, input={state.current_failure.failing_input}"
            )
        if state.current_patch:
            evidence_items.append(f"Candidate patch exists: syntax_valid={state.patch_syntax_valid}")
        if state.reverification_passed is not None:
            evidence_items.append(f"Re-verification sandbox outcome: passed={state.reverification_passed}")

        evidence_str = "\n".join(evidence_items) if evidence_items else "No test evidence collected yet."

        prompt = f"""You are the RESQ Verification Agent, an expert AI software verification assistant.
Your goal is to investigate defects, explore edge cases, evaluate invariants, and verify Python code changes.

Verification Objective: {state.objective}

Target Python Module ({state.target_filename}):
```python
{state.source_code}
```

Current Verification Evidence:
{evidence_str}

Recent Action History:
{history_str}

Budget & Constraints:
- Remaining decision cycles: {state.remaining_cycles}
- Remaining tool calls: {state.remaining_tool_calls}
- Patch attempts: {state.patch_attempts}/{state.max_patch_attempts}

Available Registered Tools:
1. inspect_source: inspect target Python source lines and symbols
2. inspect_tests: discover test functions, invariants, and Hypothesis properties
3. run_baseline_tests: execute tests against unpatched code in isolated Docker sandbox
4. analyze_failure: parse failure output, traceback, exception, and counterexamples
5. inspect_ast: check Python AST syntax, functions, classes, and imports
6. run_hypothesis_analysis: execute property-based test with targeted seed or examples
7. generate_candidate_patch: synthesize targeted candidate patch based on evidence
8. validate_candidate_patch: perform static AST syntax and diff validation
9. run_verification_tests: execute tests against candidate patch in sandbox
10. summarize_evidence: compile evidence report
11. stop: conclude verification when objective is satisfied or conclusively determined

Instructions:
Select the single next bounded verification action that best advances verification.
Do not repeat redundant actions.
Provide concise, evidence-grounded reasoning.
Return your decision strictly in the requested structured JSON schema.
"""
        return prompt

    def decide_action(self, state: Any) -> Any:
        """Invokes Gemini to select the next verification action based on structured state."""
        from resq.agent.models import AgentActionName, AgentCompletionStatus, AgentDecision

        client = self._get_client()
        prompt = self._build_agent_prompt(state)

        try:
            try:
                from google.genai import types

                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=StructuredDecisionResponse,
                    temperature=self.settings.llm_temperature,
                )
            except ImportError:
                config = {
                    "response_mime_type": "application/json",
                    "temperature": self.settings.llm_temperature,
                }

            response = client.models.generate_content(
                model=self.settings.gemini_model,
                contents=prompt,
                config=config,
            )
        except TimeoutError as exc:
            raise LLMProviderError(
                f"Gemini API request timed out after {self.settings.llm_request_timeout_seconds}s.",
                provider_name="gemini",
            ) from exc
        except Exception as exc:
            exc_str = str(exc)
            if "429" in exc_str or "quota" in exc_str.lower() or "resourceexhausted" in exc_str.lower():
                raise LLMProviderError(
                    "Gemini API quota or rate limit exceeded.",
                    provider_name="gemini",
                    status_code=429,
                ) from exc
            if "401" in exc_str or "403" in exc_str or "unauthenticated" in exc_str.lower():
                raise LLMProviderError(
                    "Gemini API authentication failed. Verify configured API credentials.",
                    provider_name="gemini",
                    status_code=401,
                ) from exc
            raise LLMProviderError(
                f"Gemini API error during agent decision cycle: {exc_str}",
                provider_name="gemini",
            ) from exc

        raw_text = getattr(response, "text", "") or ""
        parsed_decision: Optional[StructuredDecisionResponse] = None

        if hasattr(response, "parsed") and response.parsed is not None:
            if isinstance(response.parsed, StructuredDecisionResponse):
                parsed_decision = response.parsed
            elif isinstance(response.parsed, dict):
                try:
                    parsed_decision = StructuredDecisionResponse.model_validate(response.parsed)
                except Exception:
                    pass

        if parsed_decision is None:
            cleaned_text = raw_text.strip()
            if cleaned_text.startswith("```"):
                lines = cleaned_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned_text = "\n".join(lines).strip()
            try:
                parsed_json = json.loads(cleaned_text)
                parsed_decision = StructuredDecisionResponse.model_validate(parsed_json)
            except Exception as exc:
                raise LLMProviderError(
                    f"Failed to parse agent decision from Gemini response: {exc}",
                    provider_name="gemini",
                ) from exc

        # Map completion status string to AgentCompletionStatus
        status_map = {
            "continue": AgentCompletionStatus.CONTINUE,
            "completed": AgentCompletionStatus.COMPLETED,
            "needs_human_review": AgentCompletionStatus.NEEDS_HUMAN_REVIEW,
            "blocked": AgentCompletionStatus.BLOCKED,
            "inconclusive": AgentCompletionStatus.INCONCLUSIVE,
        }
        completion_status = status_map.get(
            parsed_decision.completion_status.lower(), AgentCompletionStatus.CONTINUE
        )

        return AgentDecision(
            action=parsed_decision.action,
            arguments=parsed_decision.arguments,
            reason=parsed_decision.reason,
            expected_observation=parsed_decision.expected_observation,
            completion_status=completion_status,
        )

