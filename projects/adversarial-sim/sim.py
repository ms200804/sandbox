#!/usr/bin/env python3
"""
Adversarial Simulation Orchestrator

Two-phase architecture for stress-testing legal arguments:
  Phase 1: Six parallel agents analyze independently (no cross-talk)
  Phase 2: Attacker synthesizes + Reviser revises (sequential)
  Optional: Multi-pass (feed revised argument back through Phase 1)

Usage:
    python sim.py scenarios/example.md
    python sim.py scenarios/example.md --phase1-only
    python sim.py scenarios/example.md --passes 2

Requires: claude CLI installed and ANTHROPIC_API_KEY set.
"""

import argparse
import json
import os
import re
import sys
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime

PROMPTS_DIR = Path(__file__).parent / "prompts"
OUTPUT_DIR = Path(__file__).parent / "output"

# Phase 1 agents — run in parallel, no cross-talk
PHASE1_AGENTS = [
    "opposing_counsel",
    "judge",
    "appellate",
    "pragmatic",
    "procedural",
    "evidence",
]

# Phase 2 agents — run sequentially
PHASE2_AGENTS = ["attacker", "reviser"]

# Default model — Opus across the board, no corner-cutting
DEFAULT_MODEL = "claude-opus-4-6"


def load_prompt(role: str) -> str:
    """Load a role's system prompt from prompts/ directory."""
    path = PROMPTS_DIR / f"{role}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text()


def load_scenario(path: str) -> str:
    """
    Load a scenario file and resolve any brief file references.

    Supports a `brief:` field in the scenario that points to an external file:
        ## Brief
        brief: path/to/draft_mtd_opp.md

    The referenced file's contents are inlined into the scenario.
    Paths are resolved relative to the scenario file's directory.
    """
    scenario_path = Path(path)
    content = scenario_path.read_text()

    # Look for brief file references: "brief: path/to/file.md"
    brief_match = re.search(r'^brief:\s*(.+)$', content, re.MULTILINE)
    if brief_match:
        brief_rel_path = brief_match.group(1).strip()
        brief_path = (scenario_path.parent / brief_rel_path).resolve()

        if not brief_path.exists():
            print(f"WARNING: Brief file not found: {brief_path}")
        else:
            brief_text = brief_path.read_text()
            # Replace the brief: line with the actual brief content
            content = content[:brief_match.start()] + (
                f"## Full Brief Text\n\n{brief_text}"
            ) + content[brief_match.end():]
            print(f"  Inlined brief: {brief_path} ({len(brief_text)} chars)")

    return content


def parse_scenario_metadata(scenario_text: str) -> dict:
    """
    Extract metadata fields from a scenario file.

    Looks for:
        ## Adversary Calibration
        aggressive

        ## Forum
        SDNY

        ## Max Rounds (for multi-pass)
        2
    """
    metadata = {}

    # Calibration
    cal_match = re.search(
        r'##\s*Adversary Calibration\s*\n+\s*(\w+)', scenario_text, re.IGNORECASE
    )
    if cal_match:
        metadata["calibration"] = cal_match.group(1).strip().lower()

    # Forum
    forum_match = re.search(
        r'##\s*Forum\s*\n+\s*(.+)', scenario_text, re.IGNORECASE
    )
    if forum_match:
        metadata["forum"] = forum_match.group(1).strip()

    # Max rounds / passes
    rounds_match = re.search(
        r'##\s*Max Rounds\s*\n+\s*(\d+)', scenario_text, re.IGNORECASE
    )
    if rounds_match:
        metadata["max_rounds"] = int(rounds_match.group(1))

    # Input level
    level_match = re.search(
        r'##\s*Input Level\s*\n+\s*(\w+)', scenario_text, re.IGNORECASE
    )
    if level_match:
        metadata["input_level"] = level_match.group(1).strip().lower()

    # Agent instructions (custom per-scenario)
    instr_match = re.search(
        r'##\s*Agent Instructions\s*\n+([\s\S]*?)(?=\n##\s|\Z)',
        scenario_text, re.IGNORECASE
    )
    if instr_match:
        metadata["agent_instructions"] = instr_match.group(1).strip()

    return metadata


def detect_input_level(scenario_text: str) -> str:
    """
    Auto-detect input level based on content characteristics.
    Returns: bare_issue, issue_with_facts, outline, draft_brief
    """
    # Strip metadata sections for length check
    content = re.sub(r'^##\s*(Forum|Position|Adversary Calibration|Input Level|'
                     r'Key Authorities|Max Rounds|Brief|Agent Instructions).*?'
                     r'(?=\n##\s|\Z)', '', scenario_text,
                     flags=re.MULTILINE | re.DOTALL | re.IGNORECASE)

    # Check for inlined brief text
    if '## Full Brief Text' in scenario_text:
        return 'draft_brief'

    word_count = len(content.split())
    has_citations = bool(re.search(r'\d+\s+(U\.S\.|F\.\d|S\.\s*Ct|F\.\s*Supp)', content))
    has_headings = len(re.findall(r'^#{1,4}\s', content, re.MULTILINE)) > 3
    has_numbered_args = bool(re.search(r'^\s*\d+\.\s+\*?\*?[A-Z]', content, re.MULTILINE))

    if word_count > 2000 or (word_count > 800 and has_citations):
        return 'draft_brief'
    if has_headings or has_numbered_args:
        return 'outline'
    if word_count > 150:
        return 'issue_with_facts'
    return 'bare_issue'


# Level-specific instructions appended to each Phase 1 agent's context
INPUT_LEVEL_INSTRUCTIONS = {
    "bare_issue": (
        "This is an early-stage legal question — no draft argument exists yet. "
        "Provide strategic, directional analysis. Map the doctrinal landscape. "
        "Identify the strongest and weakest angles. Flag threshold issues. "
        "Do NOT critique specific language, structure, or citations (there aren't any). "
        "Your output should help decide WHETHER and HOW to make this argument."
    ),
    "issue_with_facts": (
        "This is a developed legal position with facts but no drafted argument. "
        "Evaluate the legal theories against the stated facts. Identify elements "
        "that are satisfied vs. missing. Flag factual gaps that need investigation. "
        "Your output should help shape the argument's structure and emphasis."
    ),
    "outline": (
        "This is a structured argument outline. Evaluate the architecture: "
        "argument order, emphasis, completeness, logical flow. Check whether "
        "the planned authorities support each point. Identify missing arguments "
        "or arguments that should be cut. Your output should refine the blueprint."
    ),
    "draft_brief": (
        "This is a drafted brief. Perform detailed, line-level analysis. "
        "Check specific citations (do they say what's claimed?), factual assertions "
        "(are they supported?), structural choices (right order? right emphasis?), "
        "and language (any concessions or admissions that shouldn't be there?). "
        "Your output should identify specific passages to fix, cut, or strengthen."
    ),
}


def run_claude(system_prompt: str, user_message: str,
               model: str = DEFAULT_MODEL) -> str:
    """
    Run a Claude CLI call with a system prompt and user message.

    Uses `claude --print` for non-interactive single-shot execution.
    The system prompt is prepended to the user message since --print
    doesn't support separate system prompts.
    """
    full_prompt = f"{system_prompt}\n\n---\n\n{user_message}"

    result = subprocess.run(
        ["claude", "--print", "--model", model, "-"],
        input=full_prompt,
        capture_output=True,
        text=True,
        timeout=900,  # 15 min per agent (Opus on large prompts)
    )

    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr}")

    return result.stdout.strip()


def run_phase1_agent(role: str, scenario: str, model: str,
                     calibration: str | None = None,
                     forum: str | None = None,
                     input_level: str | None = None,
                     agent_instructions: str | None = None) -> dict:
    """Run a single Phase 1 agent. Returns dict with role and response."""
    print(f"  [{role}] Starting...")
    prompt = load_prompt(role)

    # Build context-aware instructions
    instructions = [
        "Analyze the argument presented in the scenario above.",
        "Follow your role instructions exactly and produce your analysis "
        "in the specified output format.",
    ]

    # Input-level instructions tell agents how deep to go
    if input_level and input_level in INPUT_LEVEL_INSTRUCTIONS:
        instructions.append(INPUT_LEVEL_INSTRUCTIONS[input_level])

    # Custom agent instructions from the scenario override defaults
    if agent_instructions:
        instructions.append(agent_instructions)

    if calibration and role == "opposing_counsel":
        instructions.append(
            f"Calibration level: {calibration}. Adjust your attack intensity accordingly."
        )

    if forum:
        instructions.append(
            f"Forum: {forum}. Apply the procedural rules and precedent of this jurisdiction."
        )

    user_msg = (
        f"## Scenario\n\n{scenario}\n\n"
        f"## Instructions\n\n" + " ".join(instructions)
    )

    try:
        response = run_claude(prompt, user_msg, model)
        print(f"  [{role}] Done ({len(response)} chars)")
        return {"role": role, "response": response, "error": None}
    except Exception as e:
        print(f"  [{role}] FAILED: {e}")
        return {"role": role, "response": None, "error": str(e)}


def run_phase1(scenario: str, model: str, output_dir: Path,
               calibration: str | None = None,
               forum: str | None = None,
               input_level: str | None = None,
               agent_instructions: str | None = None,
               pass_num: int = 1) -> dict:
    """Run all Phase 1 agents in parallel. Returns results dict."""
    pass_label = f" (pass {pass_num})" if pass_num > 1 else ""
    print(f"═══ Phase 1: Parallel Attack Surface{pass_label} ═══")
    if input_level:
        print(f"  Input level: {input_level}")

    phase1_results = {}

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(
                run_phase1_agent, role, scenario, model,
                calibration, forum, input_level, agent_instructions,
            ): role
            for role in PHASE1_AGENTS
        }
        for future in as_completed(futures):
            result = future.result()
            phase1_results[result["role"]] = result

    # Save Phase 1 results
    suffix = f"_pass{pass_num}" if pass_num > 1 else ""
    for role, result in phase1_results.items():
        out_path = output_dir / f"phase1_{role}{suffix}.md"
        if result["response"]:
            out_path.write_text(result["response"])
        else:
            out_path.write_text(f"# ERROR\n\n{result['error']}")

    # Report
    failures = [r for r in phase1_results.values() if r["error"]]
    if failures:
        print(f"\nWARNING: {len(failures)} agent(s) failed:")
        for f in failures:
            print(f"  - {f['role']}: {f['error']}")

    successful = {k: v for k, v in phase1_results.items() if v["response"]}
    print(f"\nPhase 1{pass_label} complete: "
          f"{len(successful)}/{len(PHASE1_AGENTS)} agents succeeded")

    return phase1_results


def run_phase2(scenario: str, phase1_results: dict, model: str,
               output_dir: Path, pass_num: int = 1) -> tuple[str, str]:
    """Run Phase 2 (Attacker + Reviser). Returns (attacker, reviser) responses."""
    pass_label = f" (pass {pass_num})" if pass_num > 1 else ""
    suffix = f"_pass{pass_num}" if pass_num > 1 else ""

    print(f"\n═══ Phase 2: Synthesis{pass_label} ═══")

    successful = {k: v for k, v in phase1_results.items() if v.get("response")}

    # Compile Phase 1 output for Attacker
    phase1_compiled = "\n\n---\n\n".join(
        f"## {role.replace('_', ' ').title()} Analysis\n\n{r['response']}"
        for role, r in sorted(successful.items())
    )

    # Attacker: synthesize and prioritize
    print("  [attacker] Starting...")
    attacker_prompt = load_prompt("attacker")
    attacker_msg = (
        f"## Original Scenario\n\n{scenario}\n\n"
        f"## Phase 1 Analyses ({len(successful)} agents)\n\n{phase1_compiled}\n\n"
        f"## Instructions\n\n"
        f"Synthesize all Phase 1 analyses into a unified, prioritized "
        f"vulnerability report. Follow your role instructions exactly."
    )
    attacker_response = run_claude(attacker_prompt, attacker_msg, model)
    print(f"  [attacker] Done ({len(attacker_response)} chars)")
    (output_dir / f"phase2_attacker{suffix}.md").write_text(attacker_response)

    # Reviser: revise the argument
    print("  [reviser] Starting...")
    reviser_prompt = load_prompt("reviser")
    reviser_msg = (
        f"## Original Scenario and Argument\n\n{scenario}\n\n"
        f"## Vulnerability Report (from Attacker)\n\n{attacker_response}\n\n"
        f"## Instructions\n\n"
        f"Revise the argument to address the identified vulnerabilities. "
        f"Produce the revised argument, unfixable issues, and opposition "
        f"playbook. Follow your role instructions exactly."
    )
    reviser_response = run_claude(reviser_prompt, reviser_msg, model)
    print(f"  [reviser] Done ({len(reviser_response)} chars)")
    (output_dir / f"phase2_reviser{suffix}.md").write_text(reviser_response)

    return attacker_response, reviser_response


# ── Post-Phase-2 Processing ────────────────────────────────────────

SANDBOX_ROOT = Path(__file__).parent.parent.parent
FOLLOWUP_DIR = SANDBOX_ROOT / "research_followup"
CASE_RESEARCH_DIR = SANDBOX_ROOT / "projects" / "case-research"


def extract_research_gaps(attacker_response: str, scenario_name: str):
    """Parse attacker output for research gaps and write to research_followup/."""
    gap_patterns = [
        r'[Rr]esearch needed[:\s]+(.*)',
        r'[Nn]o (?:Fifth|Second|Ninth|Third|Fourth|Sixth|Seventh|Eighth|Tenth|Eleventh|D\.C\.) Circuit authority[:\s]*(.*)',
        r'[Cc]heck whether\s+(.*)',
        r'[Vv]erify (?:the |that )?(.*?citation.*)',
        r'[Ll]ook for\s+(.*?(?:cases|decisions|authority).*)',
        r'[Nn]o (?:binding |direct )?authority\s+(.*)',
        r'[Gg]ap[:\s]+(.*)',
        r'[Nn]eed(?:s)? (?:to )?(?:confirm|verify|check)\s+(.*)',
    ]

    items = []
    for pattern in gap_patterns:
        for match in re.finditer(pattern, attacker_response):
            item = match.group(1).strip().rstrip('.')
            if item and len(item) > 10:
                items.append(item)

    if not items:
        return

    FOLLOWUP_DIR.mkdir(exist_ok=True)
    filepath = FOLLOWUP_DIR / f"{scenario_name}.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if filepath.exists():
        content = filepath.read_text()
    else:
        content = (
            f"# Research Follow-Up: {scenario_name}\n"
            f"Generated: {now}\n"
            f"Status: pending\n"
            f"Source: adversarial sim\n\n"
        )

    content += f"\n## Research Gaps from Attacker Report\n"
    for item in items:
        content += f"- [ ] {item}\n"

    filepath.write_text(content)
    print(f"  Research gaps written to {filepath.name} ({len(items)} items)")


def verify_citations(output_dir: Path, scenario_name: str):
    """Extract citations from all sim output and verify against CourtListener."""
    sys.path.insert(0, str(CASE_RESEARCH_DIR))
    try:
        from citation_extractor import extract_citations
        from cl_client import CourtListenerClient
        cl = CourtListenerClient()
    except (ImportError, ValueError) as e:
        print(f"  Citation verification skipped: {e}")
        return

    all_citations = []
    for md_file in sorted(output_dir.glob("*.md")):
        if md_file.name == "summary.md":
            continue
        text = md_file.read_text()
        cites = extract_citations(text)
        for c in cites:
            c.context = md_file.stem  # track which agent cited it
            all_citations.append(c)

    if not all_citations:
        print("  No citations found in sim output.")
        return

    # Deduplicate
    seen = set()
    unique = []
    for c in all_citations:
        key = c.standard_cite
        if key not in seen:
            seen.add(key)
            unique.append(c)

    print(f"  Verifying {len(unique)} unique citations against CourtListener...")

    verified = []
    not_found = []
    partial = []

    for cit in unique:
        try:
            results = cl.search_opinions(f'citation:("{cit.standard_cite}")', limit=3)
            if results:
                best = results[0]
                name_match = cit.case_name and cit.case_name.lower()[:20] in best.get("case_name", "").lower()
                if name_match or not cit.case_name:
                    verified.append({
                        "citation": cit.standard_cite,
                        "case_name": best.get("case_name", cit.case_name),
                        "cited_by": cit.context,
                        "status": "verified",
                    })
                else:
                    partial.append({
                        "citation": cit.standard_cite,
                        "case_name_in_brief": cit.case_name,
                        "case_name_in_cl": best.get("case_name", ""),
                        "cited_by": cit.context,
                        "status": "partial",
                    })
            else:
                not_found.append({
                    "citation": cit.standard_cite,
                    "case_name": cit.case_name,
                    "cited_by": cit.context,
                    "status": "not_found",
                })
        except Exception:
            not_found.append({
                "citation": cit.standard_cite,
                "case_name": cit.case_name,
                "cited_by": cit.context,
                "status": "error",
            })

    print(f"  Results: {len(verified)} verified, {len(partial)} partial, {len(not_found)} not found")

    # Write to follow-up file
    if not_found or partial:
        FOLLOWUP_DIR.mkdir(exist_ok=True)
        filepath = FOLLOWUP_DIR / f"{scenario_name}.md"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        if filepath.exists():
            content = filepath.read_text()
        else:
            content = (
                f"# Research Follow-Up: {scenario_name}\n"
                f"Generated: {now}\n"
                f"Status: pending\n"
                f"Source: adversarial sim\n\n"
            )

        content += f"\n## Citation Verification (from sim output)\n"
        for v in verified:
            content += f"- [x] {v['citation']} — {v['case_name']} — verified\n"
        for p in partial:
            content += (f"- [?] {p['citation']} — brief says \"{p['case_name_in_brief']}\", "
                       f"CL says \"{p['case_name_in_cl']}\". Cited by: {p['cited_by']}. "
                       f"Confirm on Lexis.\n")
        for nf in not_found:
            content += (f"- [ ] {nf['citation']} — {nf['case_name'] or 'unknown'} — "
                       f"NOT FOUND IN CL. Cited by: {nf['cited_by']}. "
                       f"May be hallucinated or a CL gap. Verify on Lexis.\n")

        filepath.write_text(content)
        print(f"  Citation verification written to {filepath.name}")


def run_simulation(scenario_path: str, model: str = DEFAULT_MODEL,
                   phase1_only: bool = False, passes: int = 1):
    """Run a full adversarial simulation, optionally with multiple passes."""
    scenario = load_scenario(scenario_path)
    metadata = parse_scenario_metadata(scenario)
    calibration = metadata.get("calibration")
    forum = metadata.get("forum")
    agent_instructions = metadata.get("agent_instructions")

    # Input level: explicit from scenario, or auto-detect
    input_level = metadata.get("input_level") or detect_input_level(scenario)

    # Scenario can override pass count
    if metadata.get("max_rounds") and passes == 1:
        passes = metadata["max_rounds"]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scenario_name = Path(scenario_path).stem
    output_dir = OUTPUT_DIR / f"{scenario_name}_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Adversarial Simulation: {scenario_path}")
    print(f"Model: {model}")
    print(f"Input level: {input_level}")
    print(f"Agents: {len(PHASE1_AGENTS)} (Phase 1) + {len(PHASE2_AGENTS)} (Phase 2)")
    print(f"Passes: {passes}")
    if calibration:
        print(f"Calibration: {calibration}")
    if forum:
        print(f"Forum: {forum}")
    print(f"Output: {output_dir}")
    print()

    # ── Pass 1 (and potentially more) ──────────────────────────────
    current_scenario = scenario
    last_attacker = None
    last_reviser = None

    for pass_num in range(1, passes + 1):
        # Phase 1
        phase1_results = run_phase1(
            current_scenario, model, output_dir,
            calibration=calibration, forum=forum,
            input_level=input_level, agent_instructions=agent_instructions,
            pass_num=pass_num,
        )

        successful = {k: v for k, v in phase1_results.items() if v.get("response")}
        if not successful:
            print(f"All Phase 1 agents failed on pass {pass_num}. Aborting.")
            break

        if phase1_only:
            print(f"\n--phase1-only flag set. Results in {output_dir}")
            _write_summary(output_dir, phase1_results, None, None,
                           scenario_path, passes=pass_num, model=model)
            return

        # Phase 2
        last_attacker, last_reviser = run_phase2(
            current_scenario, phase1_results, model, output_dir,
            pass_num=pass_num,
        )

        # For multi-pass: feed the Reviser's revised argument back as the new scenario
        if pass_num < passes:
            print(f"\n{'─' * 60}")
            print(f"Pass {pass_num} complete. Feeding revised argument into pass {pass_num + 1}...")
            print(f"{'─' * 60}\n")

            # Compose a new scenario with the refined argument
            current_scenario = (
                f"# Revised Argument (after pass {pass_num} adversarial review)\n\n"
                f"## Original Context\n\n{scenario}\n\n"
                f"## Revised Argument\n\n{last_reviser}\n\n"
                f"## Instructions for This Pass\n\n"
                f"This argument has already been through {pass_num} round(s) of "
                f"adversarial review. Focus on NEW weaknesses, especially any "
                f"introduced by the revisions. Don't re-flag issues that were "
                f"already addressed unless the fix was inadequate."
            )

    # ── Write final summary ────────────────────────────────────────
    _write_summary(output_dir, phase1_results, last_attacker, last_reviser,
                   scenario_path, passes=passes, model=model)

    # ── Post-processing ─────────────────────────────────────────────
    print(f"\n═══ Post-Processing ═══")

    # Extract research gaps from attacker report
    if last_attacker:
        extract_research_gaps(last_attacker, scenario_name)

    # Verify citations in all output files
    verify_citations(output_dir, scenario_name)

    print(f"\nSimulation complete ({passes} pass{'es' if passes > 1 else ''}). "
          f"All output in {output_dir}")
    print(f"  Start with: phase2_reviser{'_pass' + str(passes) if passes > 1 else ''}.md")
    print(f"  Deep dive:  phase2_attacker{'_pass' + str(passes) if passes > 1 else ''}.md")


def _write_summary(output_dir: Path, phase1_results: dict,
                   attacker_response: str | None, reviser_response: str | None,
                   scenario_path: str, passes: int = 1,
                   model: str = DEFAULT_MODEL):
    """Write a summary index file."""
    summary_lines = [
        f"# Adversarial Simulation Summary",
        f"",
        f"- **Scenario:** {scenario_path}",
        f"- **Model:** {model}",
        f"- **Agents:** {', '.join(PHASE1_AGENTS)}",
        f"- **Passes:** {passes}",
        f"- **Timestamp:** {datetime.now().isoformat()}",
        f"",
        f"## Phase 1: Parallel Attack Surface",
        f"",
    ]
    for role in PHASE1_AGENTS:
        r = phase1_results.get(role, {})
        status = "OK" if r.get("response") else f"FAILED: {r.get('error', 'unknown')}"
        summary_lines.append(f"- **{role}:** {status} → `phase1_{role}.md`")

    if attacker_response:
        summary_lines.extend([
            f"",
            f"## Phase 2: Synthesis",
            f"",
            f"- **attacker:** OK → `phase2_attacker.md`",
            f"- **reviser:** {'OK' if reviser_response else 'FAILED'} → `phase2_reviser.md`",
        ])

    if passes > 1:
        summary_lines.extend([
            f"",
            f"## Multi-Pass",
            f"",
            f"Ran {passes} passes. Final output uses `_pass{passes}` suffix.",
            f"Compare across passes to see how the argument evolved.",
        ])

    summary_lines.extend([
        f"",
        f"## Reading Order",
        f"",
    ])
    suffix = f"_pass{passes}" if passes > 1 else ""
    summary_lines.extend([
        f"1. `phase2_reviser{suffix}.md` — revised argument + opposition playbook",
        f"2. `phase2_attacker{suffix}.md` — prioritized vulnerability report",
        f"3. `phase1_*.md` — individual agent analyses (for deep dives)",
    ])

    (output_dir / "summary.md").write_text("\n".join(summary_lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Adversarial argument simulation (two-phase architecture)"
    )
    parser.add_argument("scenario", help="Path to scenario markdown file")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Claude model (default: {DEFAULT_MODEL})")
    parser.add_argument("--phase1-only", action="store_true",
                        help="Run only Phase 1 (parallel analysis), skip synthesis")
    parser.add_argument("--passes", type=int, default=1,
                        help="Number of full passes (default: 1; revised argument "
                             "feeds back into Phase 1 for subsequent passes)")
    args = parser.parse_args()

    run_simulation(args.scenario, model=args.model,
                   phase1_only=args.phase1_only, passes=args.passes)
