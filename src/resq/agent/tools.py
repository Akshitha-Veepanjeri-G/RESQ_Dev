"""Controlled Tool Registry for the RESQ Verification Agent.

All tools adhere to strict security invariants:
1. No arbitrary host execution or unrestricted shell commands.
2. All test executions run inside the isolated Docker sandbox via ExecutionEnvironment.
3. Original source files are IMMUTABLE.
4. Tool outputs are bounded to prevent memory exhaustion.
5. All arguments are strictly schema-validated.
"""

import ast
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Callable, Optional

from resq.agent.models import AgentActionName, AgentObservation
from resq.engine.failure_analyzer import FailureAnalyzer
from resq.engine.patch_applier import PatchApplier
from resq.execution.base import ExecutionEnvironment, InfrastructureError
from resq.llm.base import LLMProvider
from resq.models import CandidatePatch, ExecutionResult, FailureArtifact, Verdict


@dataclass
class ToolDefinition:
    """Metadata and execution handler for a registered verification tool."""

    name: str
    description: str
    parameters_schema: dict[str, Any]
    handler: Callable[..., AgentObservation]


class ToolRegistry:
    """Registry managing bounded verification tools for the RESQ Agent."""

    def __init__(
        self,
        execution_env: ExecutionEnvironment,
        llm_provider: LLMProvider,
        failure_analyzer: Optional[FailureAnalyzer] = None,
        patch_applier: Optional[PatchApplier] = None,
        max_output_chars: int = 65536,
    ):
        self.execution_env = execution_env
        self.llm_provider = llm_provider
        self.failure_analyzer = failure_analyzer or FailureAnalyzer()
        self.patch_applier = patch_applier or PatchApplier()
        self.max_output_chars = max_output_chars
        self._tools: dict[str, ToolDefinition] = {}

        self._register_default_tools()

    def _truncate(self, text: str) -> str:
        """Truncates text output to the configured bounding limit."""
        if len(text) <= self.max_output_chars:
            return text
        return text[: self.max_output_chars] + f"\n[... truncated at {self.max_output_chars} chars ...]"

    def is_registered(self, tool_name: str) -> bool:
        """Checks if a tool is registered."""
        return tool_name in self._tools

    def get_tool_names(self) -> list[str]:
        """Returns list of registered tool names."""
        return list(self._tools.keys())

    def get_definitions_schema(self) -> list[dict[str, Any]]:
        """Returns JSON schema definitions of all registered tools."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters_schema,
            }
            for t in self._tools.values()
        ]

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> AgentObservation:
        """Executes a registered tool with safety validations.

        Args:
            tool_name: Registered tool name.
            arguments: Validated dictionary of arguments.
            context: Context containing source_code, invariants_code, workspace paths, etc.

        Returns:
            AgentObservation with structured evidence and summary.
        """
        if tool_name not in self._tools:
            return AgentObservation(
                tool_name=tool_name,
                success=False,
                output=None,
                summary=f"Security/Validation Error: Tool '{tool_name}' is not a registered verification tool.",
                evidence_payload={"error_type": "UnregisteredToolError", "tool_name": tool_name},
            )

        tool = self._tools[tool_name]
        try:
            return tool.handler(arguments, context)
        except Exception as exc:
            return AgentObservation(
                tool_name=tool_name,
                success=False,
                output=str(exc),
                summary=f"Execution failed in tool '{tool_name}': {str(exc)}",
                evidence_payload={"error_type": type(exc).__name__, "message": str(exc)},
            )

    def _register_default_tools(self) -> None:
        """Registers the 10 canonical verification tools."""

        # 1. inspect_source
        self._tools[AgentActionName.INSPECT_SOURCE.value] = ToolDefinition(
            name=AgentActionName.INSPECT_SOURCE.value,
            description="Inspect target Python source code with optional line numbers and range.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "start_line": {"type": "integer", "description": "Starting line number (1-indexed)."},
                    "end_line": {"type": "integer", "description": "Ending line number (inclusive)."},
                },
            },
            handler=self._handle_inspect_source,
        )

        # 2. inspect_tests
        self._tools[AgentActionName.INSPECT_TESTS.value] = ToolDefinition(
            name=AgentActionName.INSPECT_TESTS.value,
            description="Inspect test suite and discover unit tests, invariants, and Hypothesis properties.",
            parameters_schema={
                "type": "object",
                "properties": {},
            },
            handler=self._handle_inspect_tests,
        )

        # 3. run_baseline_tests
        self._tools[AgentActionName.RUN_BASELINE_TESTS.value] = ToolDefinition(
            name=AgentActionName.RUN_BASELINE_TESTS.value,
            description="Execute tests against original unpatched code inside the isolated Docker sandbox.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "test_filter": {"type": "string", "description": "Optional pytest -k filter expression."},
                },
            },
            handler=self._handle_run_baseline_tests,
        )

        # 4. analyze_failure
        self._tools[AgentActionName.ANALYZE_FAILURE.value] = ToolDefinition(
            name=AgentActionName.ANALYZE_FAILURE.value,
            description="Examine test failure output, stack trace, exception type, and Hypothesis counterexamples.",
            parameters_schema={
                "type": "object",
                "properties": {},
            },
            handler=self._handle_analyze_failure,
        )

        # 5. inspect_ast
        self._tools[AgentActionName.INSPECT_AST.value] = ToolDefinition(
            name=AgentActionName.INSPECT_AST.value,
            description="Inspect the Python syntax tree of source code or candidate patch to check functions, classes, and syntax validity.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": ["source", "patch"],
                        "description": "Whether to inspect 'source' or candidate 'patch'.",
                    },
                },
            },
            handler=self._handle_inspect_ast,
        )

        # 6. run_hypothesis_analysis
        self._tools[AgentActionName.RUN_HYPOTHESIS_ANALYSIS.value] = ToolDefinition(
            name=AgentActionName.RUN_HYPOTHESIS_ANALYSIS.value,
            description="Run property-based tests with targeted Hypothesis settings (e.g. seed or max_examples) to reproduce edge cases.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "seed": {"type": "integer", "description": "Hypothesis seed for deterministic reproduction."},
                    "max_examples": {"type": "integer", "description": "Maximum test case examples to generate."},
                },
            },
            handler=self._handle_run_hypothesis_analysis,
        )

        # 7. generate_candidate_patch
        self._tools[AgentActionName.GENERATE_CANDIDATE_PATCH.value] = ToolDefinition(
            name=AgentActionName.GENERATE_CANDIDATE_PATCH.value,
            description="Request a targeted candidate patch from the configured LLM provider based on failure evidence.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "focus_hint": {"type": "string", "description": "Optional architectural hint or defect location."},
                },
            },
            handler=self._handle_generate_candidate_patch,
        )

        # 8. validate_candidate_patch
        self._tools[AgentActionName.VALIDATE_CANDIDATE_PATCH.value] = ToolDefinition(
            name=AgentActionName.VALIDATE_CANDIDATE_PATCH.value,
            description="Perform static AST syntax validation and unified diff computation on candidate patch.",
            parameters_schema={
                "type": "object",
                "properties": {},
            },
            handler=self._handle_validate_candidate_patch,
        )

        # 9. run_verification_tests
        self._tools[AgentActionName.RUN_VERIFICATION_TESTS.value] = ToolDefinition(
            name=AgentActionName.RUN_VERIFICATION_TESTS.value,
            description="Execute tests against candidate patch inside an isolated sandbox workspace (source is never mutated).",
            parameters_schema={
                "type": "object",
                "properties": {
                    "test_filter": {"type": "string", "description": "Optional pytest -k filter expression."},
                },
            },
            handler=self._handle_run_verification_tests,
        )

        # 10. summarize_evidence
        self._tools[AgentActionName.SUMMARIZE_EVIDENCE.value] = ToolDefinition(
            name=AgentActionName.SUMMARIZE_EVIDENCE.value,
            description="Assemble a structured evidence report from collected baseline, failure, and re-verification observations.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "assessment": {"type": "string", "description": "Agent assessment summary."},
                },
            },
            handler=self._handle_summarize_evidence,
        )

    # ---------------- Tool Handlers ----------------

    def _handle_inspect_source(self, args: dict[str, Any], context: dict[str, Any]) -> AgentObservation:
        code: str = context.get("source_code", "")
        lines = code.splitlines()
        start = max(1, args.get("start_line", 1))
        end = min(len(lines), args.get("end_line", len(lines))) if args.get("end_line") else len(lines)

        selected_lines = [f"{i:4d}: {lines[i-1]}" for i in range(start, end + 1)]
        formatted = "\n".join(selected_lines)

        # Parse basic symbols
        symbols = []
        try:
            tree = ast.parse(code)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef):
                    symbols.append(f"def {node.name}(line {node.lineno})")
                elif isinstance(node, ast.ClassDef):
                    symbols.append(f"class {node.name}(line {node.lineno})")
        except SyntaxError:
            pass

        return AgentObservation(
            tool_name=AgentActionName.INSPECT_SOURCE.value,
            success=True,
            output=self._truncate(formatted),
            summary=f"Inspected lines {start}-{end} of target source ({len(lines)} total lines). Found symbols: {', '.join(symbols) or 'none'}",
            evidence_payload={
                "total_lines": len(lines),
                "inspected_range": [start, end],
                "symbols": symbols,
            },
        )

    def _handle_inspect_tests(self, args: dict[str, Any], context: dict[str, Any]) -> AgentObservation:
        code: str = context.get("invariants_code", "")
        lines = code.splitlines()

        test_functions = []
        hypothesis_properties = []
        try:
            tree = ast.parse(code)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef):
                    if node.name.startswith("test_"):
                        test_functions.append(node.name)
                        # Check decorators for hypothesis @given
                        for dec in node.decorator_list:
                            dec_name = ""
                            if isinstance(dec, ast.Name):
                                dec_name = dec.id
                            elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                                dec_name = dec.func.id
                            if dec_name == "given" or "given" in ast.dump(dec):
                                hypothesis_properties.append(node.name)
        except SyntaxError:
            pass

        return AgentObservation(
            tool_name=AgentActionName.INSPECT_TESTS.value,
            success=True,
            output=self._truncate(code),
            summary=f"Inspected test harness ({len(lines)} lines). Found {len(test_functions)} tests: {test_functions}. Hypothesis properties: {hypothesis_properties}",
            evidence_payload={
                "total_lines": len(lines),
                "tests_found": test_functions,
                "hypothesis_properties": hypothesis_properties,
            },
        )

    def _handle_run_baseline_tests(self, args: dict[str, Any], context: dict[str, Any]) -> AgentObservation:
        source_code: str = context.get("source_code", "")
        test_code: str = context.get("invariants_code", "")
        target_fn: str = context.get("target_filename", "target.py")
        test_fn: str = context.get("test_filename", "test_target.py")
        test_filter: Optional[str] = args.get("test_filter")

        temp_dir = Path(tempfile.mkdtemp(prefix="resq_agent_base_"))
        try:
            (temp_dir / target_fn).write_text(source_code, encoding="utf-8")
            (temp_dir / test_fn).write_text(test_code, encoding="utf-8")

            cmd = ["pytest", test_fn, "--tb=short", "-q", "-o", "cache_dir=/tmp/.pytest_cache"]
            if test_filter:
                # Sanitize filter: allow alphanumeric, underscore, brackets, quotes
                clean_filter = re.sub(r"[^a-zA-Z0-9_\-\[\]\"\s]", "", test_filter)
                if clean_filter:
                    cmd.extend(["-k", clean_filter])

            exec_result = self.execution_env.execute(temp_dir, cmd)

            # Store in context
            context["baseline_execution_result"] = exec_result

            passed = exec_result.exit_code == 0
            summary = (
                f"Baseline execution exited with code {exec_result.exit_code} "
                f"({'PASSED' if passed else 'FAILED'}) in {exec_result.duration_seconds:.2f}s."
            )
            return AgentObservation(
                tool_name=AgentActionName.RUN_BASELINE_TESTS.value,
                success=True,
                output=self._truncate(f"{exec_result.stdout}\n{exec_result.stderr}".strip()),
                summary=summary,
                evidence_payload={
                    "exit_code": exec_result.exit_code,
                    "timed_out": exec_result.timed_out,
                    "duration_seconds": exec_result.duration_seconds,
                    "passed": passed,
                },
            )
        except InfrastructureError as exc:
            return AgentObservation(
                tool_name=AgentActionName.RUN_BASELINE_TESTS.value,
                success=False,
                output=str(exc),
                summary=f"Infrastructure error during baseline execution: {str(exc)}",
                evidence_payload={"exit_code": 125, "error": "INFRASTRUCTURE_ERROR"},
            )
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _handle_analyze_failure(self, args: dict[str, Any], context: dict[str, Any]) -> AgentObservation:
        exec_result: Optional[ExecutionResult] = context.get("baseline_execution_result")
        if not exec_result:
            # Check latest reverify result if any
            exec_result = context.get("reverification_execution_result")

        if not exec_result:
            return AgentObservation(
                tool_name=AgentActionName.ANALYZE_FAILURE.value,
                success=False,
                output=None,
                summary="No test execution output available to analyze. Run baseline tests first.",
                evidence_payload={"error": "NO_PRIOR_EXECUTION"},
            )

        artifact: FailureArtifact = self.failure_analyzer.analyze(exec_result)
        context["current_failure"] = artifact

        summary = (
            f"Failure Analysis: reproducible={artifact.is_reproducible}, "
            f"exception='{artifact.exception_type or 'None'}', "
            f"assertion='{artifact.assertion_message or 'None'}', "
            f"failing_input={artifact.failing_input}, seed={artifact.seed}."
        )

        return AgentObservation(
            tool_name=AgentActionName.ANALYZE_FAILURE.value,
            success=True,
            output=self._truncate(artifact.traceback_raw or "No traceback found"),
            summary=summary,
            evidence_payload={
                "is_reproducible": artifact.is_reproducible,
                "exception_type": artifact.exception_type,
                "assertion_message": artifact.assertion_message,
                "failing_input": str(artifact.failing_input) if artifact.failing_input is not None else None,
                "seed": artifact.seed,
            },
        )

    def _handle_inspect_ast(self, args: dict[str, Any], context: dict[str, Any]) -> AgentObservation:
        target = args.get("target", "source")
        if target == "patch":
            patch: Optional[CandidatePatch] = context.get("current_patch")
            code = patch.patch_code if patch else ""
            if not code:
                return AgentObservation(
                    tool_name=AgentActionName.INSPECT_AST.value,
                    success=False,
                    output=None,
                    summary="No candidate patch available to inspect.",
                    evidence_payload={"error": "NO_PATCH_AVAILABLE"},
                )
        else:
            code = context.get("source_code", "")

        try:
            tree = ast.parse(code)
            funcs = []
            classes = []
            imports = []
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef):
                    funcs.append(node.name)
                elif isinstance(node, ast.ClassDef):
                    classes.append(node.name)
                elif isinstance(node, ast.Import):
                    imports.extend([alias.name for alias in node.names])
                elif isinstance(node, ast.ImportFrom):
                    imports.append(node.module or "")

            return AgentObservation(
                tool_name=AgentActionName.INSPECT_AST.value,
                success=True,
                output=f"Functions: {funcs}\nClasses: {classes}\nImports: {imports}",
                summary=f"AST Inspection on {target}: Valid Python syntax. Functions: {funcs}, Classes: {classes}, Imports: {imports}.",
                evidence_payload={
                    "target": target,
                    "valid_syntax": True,
                    "functions": funcs,
                    "classes": classes,
                    "imports": imports,
                },
            )
        except SyntaxError as exc:
            return AgentObservation(
                tool_name=AgentActionName.INSPECT_AST.value,
                success=True,  # Syntax check completed successfully and detected syntax error
                output=f"SyntaxError at line {exc.lineno}: {exc.msg}",
                summary=f"AST Inspection on {target}: SyntaxError at line {exc.lineno}: {exc.msg}",
                evidence_payload={
                    "target": target,
                    "valid_syntax": False,
                    "lineno": exc.lineno,
                    "error_msg": exc.msg,
                },
            )

    def _handle_run_hypothesis_analysis(self, args: dict[str, Any], context: dict[str, Any]) -> AgentObservation:
        source_code: str = context.get("source_code", "")
        test_code: str = context.get("invariants_code", "")
        target_fn: str = context.get("target_filename", "target.py")
        test_fn: str = context.get("test_filename", "test_target.py")
        seed = args.get("seed")
        max_examples = args.get("max_examples")

        temp_dir = Path(tempfile.mkdtemp(prefix="resq_agent_hyp_"))
        try:
            (temp_dir / target_fn).write_text(source_code, encoding="utf-8")
            (temp_dir / test_fn).write_text(test_code, encoding="utf-8")

            cmd = ["pytest", test_fn, "--tb=short", "-q", "-o", "cache_dir=/tmp/.pytest_cache"]
            if seed is not None:
                cmd.append(f"--hypothesis-seed={int(seed)}")
            if max_examples is not None:
                cmd.append(f"-o")
                cmd.append(f"hypothesis_max_examples={int(max_examples)}")

            exec_result = self.execution_env.execute(temp_dir, cmd)
            artifact = self.failure_analyzer.analyze(exec_result)

            return AgentObservation(
                tool_name=AgentActionName.RUN_HYPOTHESIS_ANALYSIS.value,
                success=True,
                output=self._truncate(f"{exec_result.stdout}\n{exec_result.stderr}".strip()),
                summary=(
                    f"Hypothesis Analysis: exit_code={exec_result.exit_code}, "
                    f"seed={artifact.seed}, failing_input={artifact.failing_input}."
                ),
                evidence_payload={
                    "exit_code": exec_result.exit_code,
                    "failing_input": str(artifact.failing_input) if artifact.failing_input is not None else None,
                    "seed": artifact.seed,
                    "is_reproducible": artifact.is_reproducible,
                },
            )
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _handle_generate_candidate_patch(self, args: dict[str, Any], context: dict[str, Any]) -> AgentObservation:
        source_code: str = context.get("source_code", "")
        failure: Optional[FailureArtifact] = context.get("current_failure")
        if not failure:
            # Fallback to minimal artifact if not yet analyzed
            failure = FailureArtifact(assertion_message="Defect identified in verification checks")

        candidate_patch: CandidatePatch = self.llm_provider.generate_patch(source_code, failure)
        context["current_patch"] = candidate_patch

        # Validate syntax immediately
        is_valid, syntax_err = self.patch_applier.validate_syntax(candidate_patch.patch_code)
        context["patch_syntax_valid"] = is_valid

        diff = self.patch_applier.generate_diff(source_code, candidate_patch.patch_code)
        context["unified_diff"] = diff

        summary = (
            f"Generated candidate patch using '{candidate_patch.provider_name}'. "
            f"Syntax valid: {is_valid}. Explanation: {candidate_patch.explanation[:100]}..."
        )

        return AgentObservation(
            tool_name=AgentActionName.GENERATE_CANDIDATE_PATCH.value,
            success=True,
            output=self._truncate(diff or candidate_patch.patch_code),
            summary=summary,
            evidence_payload={
                "provider_name": candidate_patch.provider_name,
                "syntax_valid": is_valid,
                "syntax_error": syntax_err,
                "has_diff": bool(diff),
            },
        )

    def _handle_validate_candidate_patch(self, args: dict[str, Any], context: dict[str, Any]) -> AgentObservation:
        patch: Optional[CandidatePatch] = context.get("current_patch")
        if not patch:
            return AgentObservation(
                tool_name=AgentActionName.VALIDATE_CANDIDATE_PATCH.value,
                success=False,
                output=None,
                summary="Cannot validate: No candidate patch has been synthesized.",
                evidence_payload={"error": "NO_PATCH_AVAILABLE"},
            )

        source_code: str = context.get("source_code", "")
        is_valid, syntax_err = self.patch_applier.validate_syntax(patch.patch_code)
        context["patch_syntax_valid"] = is_valid

        diff = self.patch_applier.generate_diff(source_code, patch.patch_code)
        context["unified_diff"] = diff

        return AgentObservation(
            tool_name=AgentActionName.VALIDATE_CANDIDATE_PATCH.value,
            success=True,
            output=self._truncate(diff),
            summary=f"Candidate patch static validation: syntax_valid={is_valid}, syntax_error={syntax_err}.",
            evidence_payload={
                "syntax_valid": is_valid,
                "syntax_error": syntax_err,
                "diff_length": len(diff),
            },
        )

    def _handle_run_verification_tests(self, args: dict[str, Any], context: dict[str, Any]) -> AgentObservation:
        patch: Optional[CandidatePatch] = context.get("current_patch")
        if not patch:
            return AgentObservation(
                tool_name=AgentActionName.RUN_VERIFICATION_TESTS.value,
                success=False,
                output=None,
                summary="Cannot re-verify: No candidate patch exists.",
                evidence_payload={"error": "NO_PATCH_AVAILABLE"},
            )

        is_valid = context.get("patch_syntax_valid")
        if is_valid is None:
            is_valid, _ = self.patch_applier.validate_syntax(patch.patch_code)
            context["patch_syntax_valid"] = is_valid

        if is_valid is False:
            context["reverification_verdict"] = Verdict.REJECTED_SYNTAX_ERROR
            return AgentObservation(
                tool_name=AgentActionName.RUN_VERIFICATION_TESTS.value,
                success=False,
                output="Candidate patch failed AST syntax validation; cannot execute in sandbox.",
                summary="Sandbox execution rejected: candidate patch contains invalid Python syntax.",
                evidence_payload={"verdict": Verdict.REJECTED_SYNTAX_ERROR.value, "syntax_valid": False},
            )

        source_code: str = context.get("source_code", "")
        test_code: str = context.get("invariants_code", "")
        target_fn: str = context.get("target_filename", "target.py")
        test_fn: str = context.get("test_filename", "test_target.py")

        baseline_temp_dir = Path(tempfile.mkdtemp(prefix="resq_agent_reverify_base_"))
        patch_temp_dir: Optional[Path] = None

        try:
            (baseline_temp_dir / target_fn).write_text(source_code, encoding="utf-8")
            (baseline_temp_dir / test_fn).write_text(test_code, encoding="utf-8")

            patch_temp_dir, unified_diff = self.patch_applier.prepare_patch_workspace(
                baseline_temp_dir,
                patch.patch_code,
                target_filename=target_fn,
            )
            context["unified_diff"] = unified_diff

            cmd = ["pytest", test_fn, "--tb=short", "-q", "-o", "cache_dir=/tmp/.pytest_cache"]
            test_filter = args.get("test_filter")
            if test_filter:
                clean_filter = re.sub(r"[^a-zA-Z0-9_\-\[\]\"\s]", "", test_filter)
                if clean_filter:
                    cmd.extend(["-k", clean_filter])

            try:
                reverify_result = self.execution_env.execute(patch_temp_dir, cmd)
                context["reverification_execution_result"] = reverify_result

                # Determine empirical verification outcome
                if reverify_result.timed_out:
                    verdict = Verdict.TIMEOUT_EXCEEDED
                elif reverify_result.exit_code == 125:
                    verdict = Verdict.INFRASTRUCTURE_ERROR
                elif reverify_result.exit_code == 0:
                    verdict = Verdict.VERIFIED
                else:
                    combined_out = f"{reverify_result.stdout}\n{reverify_result.stderr}".lower()
                    if "baseline" in combined_out or "regression" in combined_out:
                        verdict = Verdict.REJECTED_REGRESSION
                    else:
                        verdict = Verdict.REJECTED_STILL_FAILS

                context["reverification_verdict"] = verdict

                summary = (
                    f"Sandbox Re-verification: exit_code={reverify_result.exit_code}, "
                    f"verdict={verdict.value} in {reverify_result.duration_seconds:.2f}s."
                )

                payload: dict[str, Any] = {
                    "exit_code": reverify_result.exit_code,
                    "timed_out": reverify_result.timed_out,
                    "verdict": verdict.value,
                    "duration_seconds": reverify_result.duration_seconds,
                }
                if reverify_result.exit_code == 125:
                    payload["error"] = "INFRASTRUCTURE_ERROR"

                return AgentObservation(
                    tool_name=AgentActionName.RUN_VERIFICATION_TESTS.value,
                    success=(verdict != Verdict.INFRASTRUCTURE_ERROR),
                    output=self._truncate(f"{reverify_result.stdout}\n{reverify_result.stderr}".strip()),
                    summary=summary,
                    evidence_payload=payload,
                )
            except InfrastructureError as exc:
                infra_res = ExecutionResult(
                    exit_code=125,
                    stdout="",
                    stderr=str(exc),
                    timed_out=False,
                    duration_seconds=0.0,
                )
                context["reverification_execution_result"] = infra_res
                context["reverification_verdict"] = Verdict.INFRASTRUCTURE_ERROR
                return AgentObservation(
                    tool_name=AgentActionName.RUN_VERIFICATION_TESTS.value,
                    success=False,
                    output=str(exc),
                    summary=f"Infrastructure error during re-verification execution: {str(exc)}",
                    evidence_payload={"exit_code": 125, "error": "INFRASTRUCTURE_ERROR"},
                )
        finally:
            if patch_temp_dir and patch_temp_dir.exists():
                shutil.rmtree(patch_temp_dir, ignore_errors=True)
            if baseline_temp_dir.exists():
                shutil.rmtree(baseline_temp_dir, ignore_errors=True)

    def _handle_summarize_evidence(self, args: dict[str, Any], context: dict[str, Any]) -> AgentObservation:
        baseline_res: Optional[ExecutionResult] = context.get("baseline_execution_result")
        failure: Optional[FailureArtifact] = context.get("current_failure")
        patch: Optional[CandidatePatch] = context.get("current_patch")
        reverify_verdict: Optional[Verdict] = context.get("reverification_verdict")
        syntax_valid: Optional[bool] = context.get("patch_syntax_valid")

        evidence_items = []
        if baseline_res:
            evidence_items.append(f"Baseline: exit_code={baseline_res.exit_code}")
        if failure:
            evidence_items.append(f"Reproducer: reproducible={failure.is_reproducible}, seed={failure.seed}")
        if patch:
            evidence_items.append(f"Candidate Patch: syntax_valid={syntax_valid}")
        if reverify_verdict:
            evidence_items.append(f"Re-verification Verdict: {reverify_verdict.value}")

        assessment = args.get("assessment", "Evidence summarized.")
        summary = f"Evidence Report: {assessment} [{' | '.join(evidence_items)}]"

        return AgentObservation(
            tool_name=AgentActionName.SUMMARIZE_EVIDENCE.value,
            success=True,
            output="\n".join(evidence_items),
            summary=summary,
            evidence_payload={
                "has_baseline": baseline_res is not None,
                "has_reproducer": failure is not None and failure.is_reproducible,
                "has_patch": patch is not None,
                "verdict": reverify_verdict.value if reverify_verdict else None,
            },
        )
