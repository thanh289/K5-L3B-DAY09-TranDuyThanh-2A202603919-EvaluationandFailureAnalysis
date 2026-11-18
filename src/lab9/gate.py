"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def _ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    problems = []
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return ["ratchet: eval-set version changed while comparing the same eval set"]

    for group, key in (("metrics", lambda x: x["id"]),
                       ("slices", lambda x: (x["name"], x["metric"]))):
        old_list = base_spec.get(group, [])
        new_list = spec.get(group, [])
        if not isinstance(old_list, list) or not isinstance(new_list, list):
            problems.append(f"ratchet: invalid {group} list")
            continue
        try:
            old_entries = {key(entry): entry for entry in old_list}
            new_entries = {key(entry): entry for entry in new_list}
        except (KeyError, TypeError):
            problems.append(f"ratchet: invalid {group} entry")
            continue
        if len(new_entries) != len(new_list):
            problems.append(f"ratchet: duplicate {group} entry")
        for identity, old in old_entries.items():
            label = f"{group} {identity}"
            if identity not in new_entries:
                problems.append(f"ratchet: removed {label}")
                continue
            new = new_entries[identity]
            if old.get("blocking") and not new.get("blocking"):
                problems.append(f"ratchet: {label} is no longer blocking")
            old_limits = old.get("threshold", {}) if group == "metrics" else old
            new_limits = new.get("threshold", {}) if group == "metrics" else new
            if not isinstance(old_limits, dict) or not isinstance(new_limits, dict):
                problems.append(f"ratchet: invalid threshold for {label}")
                continue
            for bound in ("min", "max", "max_increase"):
                if bound not in old_limits:
                    continue
                previous, current = old_limits[bound], new_limits.get(bound)
                if (type(current) not in (int, float) or not math.isfinite(current)
                        or (bound == "min" and current < previous)
                        or (bound != "min" and current > previous)):
                    problems.append(f"ratchet: loosened or removed {bound} for {label}")
            if old_limits.get("no_significant_drop") and not new_limits.get("no_significant_drop"):
                problems.append(f"ratchet: removed no_significant_drop for {label}")
    return problems


def _report_problems(report: dict, spec: dict, role: str) -> tuple[list[str], dict[tuple[str, int], tuple[str, ...]]]:
    problems = []
    manifest, rows, metrics = report.get("manifest"), report.get("rows"), report.get("metrics")
    if not isinstance(manifest, dict) or not isinstance(rows, list) or not isinstance(metrics, dict):
        return [f"{role}: missing manifest, rows or metrics"], {}
    items, seeds = manifest.get("items"), manifest.get("seeds")
    if type(items) is not int or items < 1 or not isinstance(seeds, list) or not seeds:
        problems.append(f"{role}: invalid item or seed manifest")
    elif (any(type(seed) is not int for seed in seeds) or len(set(seeds)) != len(seeds)):
        problems.append(f"{role}: invalid or duplicate manifest seeds")
    elif len(rows) != items * len(seeds):
        problems.append(f"{role}: row count {len(rows)} != {items} items x {len(seeds)} seeds")
    if not isinstance(report.get("evaluator_failures"), list) or report["evaluator_failures"]:
        problems.append(f"{role}: evaluator_failures is invalid or non-empty")

    for name, value in metrics.items():
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            problems.append(f"{role}: metric {name} is not finite numeric")
    for entry in spec.get("metrics", []):
        if entry["id"] not in metrics:
            problems.append(f"{role}: missing metric {entry['id']}")
    if spec.get("seeds") is not None and seeds != spec["seeds"]:
        problems.append(f"{role}: manifest seeds differ from metric spec")
    graded = {m["id"]: m for m in spec.get("metrics", []) if m["id"] in GRADERS}
    pairs: list[tuple[str, int]] = []
    tags: dict[tuple[str, int], tuple[str, ...]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("item_id"), str) or type(row.get("seed")) is not int:
            problems.append(f"{role}: invalid row identity at index {index}")
            continue
        pair = row["item_id"], row["seed"]
        pairs.append(pair)
        slices = row.get("slices", [])
        if (not isinstance(slices, list) or any(not isinstance(tag, str) for tag in slices)
                or len(set(slices)) != len(slices)):
            problems.append(f"{role}: invalid slice tags on {pair}")
        else:
            tags[pair] = tuple(sorted(slices))
        for metric in graded:
            if type(row.get(metric)) is not bool:
                problems.append(f"{role}: {pair} has missing or invalid {metric} grade")
        cost = row.get("cost")
        if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost)):
            problems.append(f"{role}: {pair} has non-finite cost")
    if len(set(pairs)) != len(pairs):
        problems.append(f"{role}: duplicate (item_id, seed) row")
    if type(items) is int and len({item for item, _ in pairs}) != items:
        problems.append(f"{role}: distinct item count differs from manifest")
    if isinstance(seeds, list) and all(type(seed) is int for seed in seeds):
        if set(pairs) != {(item, seed) for item, _ in pairs for seed in seeds}:
            problems.append(f"{role}: incomplete item x seed grid")
    if not rows:
        problems.append(f"{role}: report has no rows")
        return problems, tags

    # Independently recompute the scores used by the gate; editing only the summary
    # must not make failing rows look green. Rows with invalid grades are already rejected.
    for metric, entry in graded.items():
        values = [row[metric] for row in rows if isinstance(row, dict) and type(row.get(metric)) is bool]
        if len(values) != len(rows):
            continue
        expected = sum(values) if entry.get("kind") == "safety" else round(sum(values) / len(values), 4)
        actual = metrics.get(metric)
        if type(actual) not in (int, float) or not math.isfinite(actual) or not math.isclose(actual, expected, abs_tol=1e-4):
            problems.append(f"{role}: metric {metric} disagrees with rows")
    if "pass_hat_5" in {m["id"] for m in spec.get("metrics", [])} and all(
            isinstance(row, dict) and isinstance(row.get("item_id"), str)
            and type(row.get("pass_rate")) is bool for row in rows):
        by_item: dict[str, list[bool]] = {}
        for row in rows:
            by_item.setdefault(row["item_id"], []).append(row["pass_rate"])
        expected = (round(sum(stats.pass_hat_k(len(v), sum(v), 5) for v in by_item.values()) / len(by_item), 4)
                    if by_item and all(len(v) >= 5 for v in by_item.values()) else None)
        actual = metrics.get("pass_hat_5")
        if expected is None or type(actual) not in (int, float) or not math.isclose(actual, expected, abs_tol=1e-4):
            problems.append(f"{role}: pass_hat_5 disagrees with rows")
    return problems, tags


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems, pr_tags = _report_problems(pr, spec, "PR")
    base_problems, base_tags = _report_problems(base, base_spec or spec, "baseline")
    problems.extend(base_problems)
    if set(pr_tags) != set(base_tags):
        problems.append("PR and baseline (item_id, seed) sets differ")
    for pair in sorted(set(pr_tags) & set(base_tags)):
        if pr_tags[pair] != base_tags[pair]:
            problems.append(f"slice tags changed for {pair}")
    pr_manifest = pr.get("manifest") if isinstance(pr.get("manifest"), dict) else {}
    base_manifest = base.get("manifest") if isinstance(base.get("manifest"), dict) else {}
    if spec.get("metric_spec_version") and pr_manifest.get("metric_spec_version") != spec["metric_spec_version"]:
        problems.append("PR metric spec version differs from selected spec")
    if base_spec and base_spec.get("metric_spec_version") and base_manifest.get("metric_spec_version") != base_spec["metric_spec_version"]:
        problems.append("baseline metric spec version differs from base spec")
    if base_spec is not None:
        problems.extend(_ratchet_problems(spec, base_spec))
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for entry in spec.get("slices", []):
        name, metric = entry["name"], entry["metric"]
        key = f"slice:{name}/{metric}"
        current = per_item(pr, metric, slice_name=name)
        reference = per_item(base, metric, slice_name=name)
        value = sum(current.values()) / len(current) if current else None
        verdict, note = "ok", ""
        if value is None:
            verdict = "missing"
        elif "min" in entry and value < entry["min"]:
            verdict = "fail"
        if entry.get("no_significant_drop"):
            keys = sorted(set(current) & set(reference))
            if not keys or set(current) != set(reference):
                verdict = "missing"
                note = "slice items differ or are empty"
            else:
                delta, lo, hi = stats.paired_bootstrap(
                    [current[k] for k in keys], [reference[k] for k in keys],
                    n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                    confidence=bs.get("confidence", 0.95),
                )
                note = f"Δ {delta:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and entry.get("blocking"):
            blocked.append(key)
        label = {"ok": "ok", "missing": "MISSING"}.get(
            verdict, "BLOCK" if entry.get("blocking") else "warn")
        floor = f"min {entry['min']}" if "min" in entry else "no floor"
        lines.append(f"  {key:<39} {value!s:<8} {floor:<10} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    pr_manifest = pr.get("manifest") if isinstance(pr.get("manifest"), dict) else {}
    base_manifest = base.get("manifest") if isinstance(base.get("manifest"), dict) else {}
    if pr_manifest.get("eval_set_sha") != base_manifest.get("eval_set_sha"):
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    manifest = pr.get("manifest") if isinstance(pr.get("manifest"), dict) else {}
    print(f"gate: PR {pr.get('run_id', '?')} vs main {base.get('run_id', '?')} · eval set {manifest.get('eval_set_sha', '?')}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
