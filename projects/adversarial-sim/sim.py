#!/usr/bin/env python3
"""
Adversarial Simulation Orchestrator

Two-phase architecture for stress-testing legal arguments:
  Phase 1: Four parallel agents analyze independently (no cross-talk)
  Phase 2: Destroyer synthesizes + Refiner revises (sequential)

Usage:
    python sim.py scenarios/example.md
    python sim.py scenarios/example.md --phase1-only
    python sim.py scenarios/example.md --model claude-sonnet-4-6

Requires: claude CLI installed and ANTHROPIC_API_KEY set.
"""

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime

PROMPTS_DIR = Path(__file__).parent / "prompts"
OUTPUT_DIR = Path(__file__).parent / "output"

# Phase 1 agents — run in parallel, no cross-talk
PHASE1_AGENTS = [
    "hostile_oc",
    "skeptical_judge",
    "appellate_panel",
    "economic_realist",
]

# Phase 2 agents — run sequentially
PHASE2_AGENTS = ["destroyer", "refiner"]


def load_prompt(role: str) -> str:
    """Load a role's system prompt from prompts/ directory."""
    path = PROMPTS_DIR / f"{role}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text()


def load_scenario(path: str) -> str:
    """Load a scenario file."""
    return Path(path).read_text()


def run_claude(system_prompt: str, user_message: str, model: str = "claude-sonnet-4-6") -> str:
    """
    Run a Claude CLI call with a system prompt and user message.

    Uses `claude --print` for non-interactive single-shot execution.
    The system prompt is prepended to the user message since --print
    doesn't support separate system prompts.
    """
    full_prompt = f"{system_prompt}\n\n---\n\n{user_message}"

    result = subprocess.run(
        ["claude", "--print", "--model", model, full_prompt],
        capture_output=True,
        text=True,
        timeout=300,  # 5 min per agent
    )

    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr}")

    return result.stdout.strip()


def run_phase1_agent(role: str, scenario: str, model: str) -> dict:
    """Run a single Phase 1 agent. Returns dict with role and response."""
    print(f"  [{role}] Starting...")
    prompt = load_prompt(role)
    user_msg = (
        f"## Scenario\n\n{scenario}\n\n"
        f"## Instructions\n\n"
        f"Analyze the argument presented in the scenario above. "
        f"Follow your role instructions exactly and produce your analysis "
        f"in the specified output format."
    )

    try:
        response = run_claude(prompt, user_msg, model)
        print(f"  [{role}] Done ({len(response)} chars)")
        return {"role": role, "response": response, "error": None}
    except Exception as e:
        print(f"  [{role}] FAILED: {e}")
        return {"role": role, "response": None, "error": str(e)}


def run_simulation(scenario_path: str, model: str = "claude-sonnet-4-6",
                   phase1_only: bool = False):
    """Run a full adversarial simulation."""
    scenario = load_scenario(scenario_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scenario_name = Path(scenario_path).stem
    output_dir = OUTPUT_DIR / f"{scenario_name}_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Adversarial Simulation: {scenario_path}")
    print(f"Model: {model}")
    print(f"Output: {output_dir}")
    print()

    # ── Phase 1: Parallel independent analysis ──────────────────────
    print("═══ Phase 1: Parallel Attack Surface ═══")
    phase1_results = {}

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(run_phase1_agent, role, scenario, model): role
            for role in PHASE1_AGENTS
        }
        for future in as_completed(futures):
            result = future.result()
            phase1_results[result["role"]] = result

    # Save Phase 1 results individually
    for role, result in phase1_results.items():
        out_path = output_dir / f"phase1_{role}.md"
        if result["response"]:
            out_path.write_text(result["response"])
        else:
            out_path.write_text(f"# ERROR\n\n{result['error']}")

    # Check for failures
    failures = [r for r in phase1_results.values() if r["error"]]
    if failures:
        print(f"\nWARNING: {len(failures)} agent(s) failed:")
        for f in failures:
            print(f"  - {f['role']}: {f['error']}")

    successful = {k: v for k, v in phase1_results.items() if v["response"]}
    if not successful:
        print("All Phase 1 agents failed. Aborting.")
        return

    print(f"\nPhase 1 complete: {len(successful)}/{len(PHASE1_AGENTS)} agents succeeded")

    if phase1_only:
        print(f"\n--phase1-only flag set. Results in {output_dir}")
        _write_summary(output_dir, phase1_results, None, None, scenario_path)
        return

    # ── Phase 2: Sequential synthesis ───────────────────────────────
    print("\n═══ Phase 2: Synthesis ═══")

    # Compile Phase 1 output for Destroyer
    phase1_compiled = "\n\n---\n\n".join(
        f"## {role.replace('_', ' ').title()} Analysis\n\n{r['response']}"
        for role, r in sorted(successful.items())
    )

    # Destroyer: synthesize and prioritize
    print("  [destroyer] Starting...")
    destroyer_prompt = load_prompt("destroyer")
    destroyer_msg = (
        f"## Original Scenario\n\n{scenario}\n\n"
        f"## Phase 1 Analyses\n\n{phase1_compiled}\n\n"
        f"## Instructions\n\n"
        f"Synthesize all Phase 1 analyses into a unified, prioritized "
        f"vulnerability report. Follow your role instructions exactly."
    )
    destroyer_response = run_claude(destroyer_prompt, destroyer_msg, model)
    print(f"  [destroyer] Done ({len(destroyer_response)} chars)")
    (output_dir / "phase2_destroyer.md").write_text(destroyer_response)

    # Refiner: revise the argument
    print("  [refiner] Starting...")
    refiner_prompt = load_prompt("refiner")
    refiner_msg = (
        f"## Original Scenario and Argument\n\n{scenario}\n\n"
        f"## Vulnerability Report (from Destroyer)\n\n{destroyer_response}\n\n"
        f"## Instructions\n\n"
        f"Revise the argument to address the identified vulnerabilities. "
        f"Produce the revised argument, unfixable issues, and opposition "
        f"playbook. Follow your role instructions exactly."
    )
    refiner_response = run_claude(refiner_prompt, refiner_msg, model)
    print(f"  [refiner] Done ({len(refiner_response)} chars)")
    (output_dir / "phase2_refiner.md").write_text(refiner_response)

    # ── Write summary ───────────────────────────────────────────────
    _write_summary(output_dir, phase1_results, destroyer_response,
                   refiner_response, scenario_path)

    print(f"\nSimulation complete. All output in {output_dir}")
    print(f"  Start with: phase2_refiner.md (revised argument + opposition playbook)")
    print(f"  Deep dive:  phase2_destroyer.md (full vulnerability report)")


def _write_summary(output_dir: Path, phase1_results: dict,
                   destroyer_response: str | None, refiner_response: str | None,
                   scenario_path: str):
    """Write a summary index file."""
    summary_lines = [
        f"# Adversarial Simulation Summary",
        f"",
        f"- **Scenario:** {scenario_path}",
        f"- **Timestamp:** {datetime.now().isoformat()}",
        f"",
        f"## Phase 1: Parallel Attack Surface",
        f"",
    ]
    for role in PHASE1_AGENTS:
        r = phase1_results.get(role, {})
        status = "OK" if r.get("response") else f"FAILED: {r.get('error', 'unknown')}"
        summary_lines.append(f"- **{role}:** {status} → `phase1_{role}.md`")

    if destroyer_response:
        summary_lines.extend([
            f"",
            f"## Phase 2: Synthesis",
            f"",
            f"- **destroyer:** OK → `phase2_destroyer.md`",
            f"- **refiner:** {'OK' if refiner_response else 'FAILED'} → `phase2_refiner.md`",
        ])

    summary_lines.extend([
        f"",
        f"## Reading Order",
        f"",
        f"1. `phase2_refiner.md` — revised argument + opposition playbook",
        f"2. `phase2_destroyer.md` — prioritized vulnerability report",
        f"3. `phase1_*.md` — individual agent analyses (for deep dives)",
    ])

    (output_dir / "summary.md").write_text("\n".join(summary_lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Adversarial argument simulation (two-phase architecture)"
    )
    parser.add_argument("scenario", help="Path to scenario markdown file")
    parser.add_argument("--model", default="claude-sonnet-4-6",
                        help="Claude model to use (default: claude-sonnet-4-6)")
    parser.add_argument("--phase1-only", action="store_true",
                        help="Run only Phase 1 (parallel analysis), skip synthesis")
    args = parser.parse_args()

    run_simulation(args.scenario, model=args.model, phase1_only=args.phase1_only)
