"""Compare two judged eval runs (baseline vs feature) and write a Markdown verdict.

Used by the PR eval workflow: the same questions are run and judged on the
main branch (baseline) and on the PR branch (feature). This script turns the two
`*_judged.json` files into one table with the pass rate per check and a merge
recommendation.

Usage:
    uv run python -m evals.ci.compare \
        --base base_judged.json --feature feature_judged.json \
        --base-label "main @ abc123" --feature-label "PR @ def456" \
        --output comparison.md
"""

import argparse
import json
import sys
from pathlib import Path

# result_key in the judged entries -> label shown in the table
CHECKS = {
    "judge_answer_correctness": "Answer correctness",
    "judge_instruction_following": "Instruction following",
    "judge_trajectory": "Trajectory",
}

MARKER = "<!-- eval-comparison -->"


def load(path: str) -> list[dict]:
    return json.loads(Path(path).read_text())


def pass_rates(entries: list[dict]) -> dict[str, tuple[int, int]]:
    """Return {result_key: (good, total)}."""
    rates = {}
    for key in CHECKS:
        scores = [e.get(key, {}).get("score") for e in entries]
        rates[key] = (sum(s == "good" for s in scores), len(scores))
    return rates


def pct(good: int, total: int) -> float:
    return 100.0 * good / total if total else 0.0


def agent_errors(entries: list[dict]) -> int:
    return sum(1 for e in entries if "error" in e)


def flipped(base: list[dict], feature: list[dict], key: str) -> tuple[list[str], list[str]]:
    """Questions whose score changed between runs: (good->bad, bad->good)."""
    base_by_q = {e["input"]["question"]: e.get(key, {}).get("score") for e in base}
    worse, better = [], []
    for e in feature:
        q = e["input"]["question"]
        before, after = base_by_q.get(q), e.get(key, {}).get("score")
        if before == "good" and after == "bad":
            worse.append(q)
        elif before == "bad" and after == "good":
            better.append(q)
    return worse, better


def compare(base: list[dict], feature: list[dict], tolerance: float) -> dict:
    base_rates, feature_rates = pass_rates(base), pass_rates(feature)
    rows = []
    for key, label in CHECKS.items():
        b, f = pct(*base_rates[key]), pct(*feature_rates[key])
        delta = f - b
        if delta < -tolerance:
            status = "regression"
        elif delta > tolerance:
            status = "improvement"
        else:
            status = "no significant change"
        worse, better = flipped(base, feature, key)
        rows.append({
            "key": key, "label": label,
            "base": base_rates[key], "feature": feature_rates[key],
            "base_pct": b, "feature_pct": f, "delta": delta,
            "status": status, "worse": worse, "better": better,
        })

    base_err, feature_err = agent_errors(base), agent_errors(feature)
    regressions = [r for r in rows if r["status"] == "regression"]
    improvements = [r for r in rows if r["status"] == "improvement"]

    if regressions or feature_err > base_err:
        verdict = "dont_merge"
    elif improvements:
        verdict = "merge_improvement"
    else:
        verdict = "merge_neutral"

    return {
        "rows": rows, "verdict": verdict, "tolerance": tolerance,
        "base_errors": base_err, "feature_errors": feature_err,
        "regressions": regressions, "improvements": improvements,
    }


STATUS_ICON = {"regression": "🔴", "improvement": "🟢", "no significant change": "⚪"}

VERDICT_TEXT = {
    "dont_merge": "❌ **Don't merge.** The PR makes the agent worse on at least one check.",
    "merge_improvement": "✅ **Merge.** The PR improves the agent and nothing regressed.",
    "merge_neutral": "✅ **OK to merge.** No significant change in eval quality.",
}


def render(result: dict, base_label: str, feature_label: str, n: int) -> str:
    tol = result["tolerance"]
    lines = [
        MARKER,
        "## Eval comparison",
        "",
        f"Same {n} questions run and judged on both versions.",
        "",
        f"| Check | Baseline ({base_label}) | Feature ({feature_label}) | Change | |",
        "|---|---|---|---|---|",
    ]
    for r in result["rows"]:
        bg, bt = r["base"]
        fg, ft = r["feature"]
        lines.append(
            f"| {r['label']} | {r['base_pct']:.0f}% ({bg}/{bt}) "
            f"| {r['feature_pct']:.0f}% ({fg}/{ft}) "
            f"| {r['delta']:+.0f} pp | {STATUS_ICON[r['status']]} {r['status']} |"
        )
    lines.append(
        f"| Agent errors | {result['base_errors']} | {result['feature_errors']} "
        f"| {result['feature_errors'] - result['base_errors']:+d} | |"
    )

    lines += ["", "### Verdict", "", VERDICT_TEXT[result["verdict"]], ""]
    reasons = []
    for r in result["regressions"]:
        reasons.append(f"- {r['label']} dropped by {-r['delta']:.0f} pp.")
    if result["feature_errors"] > result["base_errors"]:
        reasons.append("- The feature branch has more agent errors than the baseline.")
    for r in result["improvements"]:
        reasons.append(f"- {r['label']} improved by {r['delta']:.0f} pp.")
    lines += reasons
    lines += [
        "",
        f"A change counts as significant when it's larger than ±{tol:.0f} percentage "
        f"points (about {max(1, round(tol * n / 100))} of {n} questions). Smaller changes "
        "are within the noise of a non-deterministic agent and judge.",
    ]

    details = []
    for r in result["rows"]:
        if r["worse"] or r["better"]:
            details.append(f"**{r['label']}**")
            details += [f"- 🔴 good → bad: {q}" for q in r["worse"]]
            details += [f"- 🟢 bad → good: {q}" for q in r["better"]]
            details.append("")
    if details:
        lines += ["", "<details><summary>Questions that changed</summary>", "", *details, "</details>"]

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Judged JSON for the baseline (main).")
    parser.add_argument("--feature", required=True, help="Judged JSON for the feature branch.")
    parser.add_argument("--base-label", default="main")
    parser.add_argument("--feature-label", default="PR")
    parser.add_argument("--tolerance", type=float, default=10.0,
                        help="Change in percentage points that counts as significant (default: 10).")
    parser.add_argument("--output", default="comparison.md")
    parser.add_argument("--fail-on-regression", action="store_true",
                        help="Exit with code 1 when the verdict is 'don't merge'.")
    args = parser.parse_args()

    base, feature = load(args.base), load(args.feature)
    result = compare(base, feature, args.tolerance)
    md = render(result, args.base_label, args.feature_label, len(feature))

    Path(args.output).write_text(md)
    print(md)

    if args.fail_on_regression and result["verdict"] == "dont_merge":
        sys.exit(1)


if __name__ == "__main__":
    main()
