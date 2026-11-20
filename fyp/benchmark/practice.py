"""Package separate private practice queues, import human work and compare disagreements."""

import argparse
import base64
from html import escape
from collections import Counter
from itertools import product
import json
from pathlib import Path

from dataset import digest, key, practice_ids, private_path, read_json, records, validate_annotation, write_json

ROLES = ("annotator-a", "annotator-b")


def queue_records(root, role):
    queue = root / "practice" / role
    rows = records(queue)
    if not rows or set(rows) != practice_ids(queue) or set(rows) != practice_ids(root):
        raise ValueError(f"Practice roster and files disagree for {role}.")
    return queue, rows


def package(root, role, output):
    queue, rows = queue_records(root, role)
    images = {}
    for ident, row in rows.items():
        path = queue / "images" / f"{ident}.png"
        if digest(path) != row["image_sha256"]:
            raise ValueError(f"Image hash mismatch: {ident}")
        fields = ("id", "annotation", "width", "height", "view", "attribution", "license_terms", "image_sha256")
        images[ident] = {**{f: row[f] for f in fields},
                         "image": "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")}
    content = json.dumps({"queue": role, "images": images}, separators=(",", ":")).replace("<", "\\u003c")
    folder = Path(__file__).parent
    template = (folder / "annotation.html").read_text(encoding="utf-8")
    script = (folder / "offline.js").read_text(encoding="utf-8")
    head = f'<script id="practiceData" type="application/json">{content}</script>\n<script>{script}</script>\n'
    with open(output, "x", encoding="utf-8", opener=private_file) as stream:
        stream.write(template.replace("<script>", head + "<script>", 1))


def private_file(path, flags):
    import os
    return os.open(path, flags, 0o600)


def inspect_submission(root, source, expected_role=None):
    """Check an offline file against its roster without writing workspace records."""
    if source.stat().st_size > 500_000:
        raise ValueError("Expected a small annotation JSON file.")
    payload = read_json(source)
    if not isinstance(payload, dict) or payload.get("queue") not in ROLES or not isinstance(payload.get("rows"), list):
        raise ValueError("Expected an offline JSON object with a known queue and rows list.")
    role = payload["queue"]
    if expected_role and role != expected_role:
        raise ValueError(f"Expected the {expected_role} file, found {role}.")
    _, roster = queue_records(root, role)
    issues, seen, valid = [], set(), {}
    for index, item in enumerate(payload["rows"], 1):
        try:
            if not isinstance(item, dict):
                raise ValueError("Expected an annotation row object.")
            ident = key(item.get("id"))
            if ident in seen:
                valid.pop(ident, None)
                raise ValueError(f"Repeated practice image {ident}.")
            seen.add(ident)
            row = roster.get(ident)
            if not row or item.get("image_sha256") != row["image_sha256"]:
                raise ValueError(f"Unknown or changed practice image {ident}.")
            if not isinstance(item.get("annotation"), dict):
                raise ValueError(f"Missing annotation object for {ident}.")
            valid[ident] = validate_annotation(row, item["annotation"])
        except ValueError as exc:
            issues.append(f"Row {index}: {exc}")
    actors = sorted({row["actor"].casefold() for row in valid.values()})
    if len(actors) > 1:
        issues.append("Use one distinct human annotator ID per practice queue.")
    return {
        "queue": role, "expected": len(roster), "valid": len(valid),
        "missing_ids": sorted(set(roster) - seen),
        "invalid_ids": sorted((set(roster) & seen) - set(valid)),
        "actor_ids": actors, "issues": issues,
    }, valid


def import_submission(root, source):
    check, annotations = inspect_submission(root, source)
    if check["issues"]:
        raise ValueError(" ".join(check["issues"]))
    role = check["queue"]
    queue, rows = queue_records(root, role)
    other_role = next(name for name in ROLES if name != role)
    _, other = queue_records(root, other_role)
    peer_ids = {r["annotation"]["actor"].casefold() for r in other.values() if r["annotation"]}
    participant = {r["annotation"]["actor"].casefold() for r in rows.values() if r["annotation"]}
    participant.update(check["actor_ids"])
    if not annotations or len(participant) != 1 or participant & peer_ids:
        raise ValueError("Use one distinct human annotator ID per practice queue.")
    for ident, annotation in annotations.items():
        if rows[ident]["annotation"] and rows[ident]["annotation"] != annotation:
            raise ValueError(f"Conflicting saved annotation on {ident}; the workspace was not changed.")
    for ident, annotation in annotations.items():
        write_json(queue / "records" / f"{ident}.json", {**rows[ident], "annotation": annotation, "review": None})
    return len(annotations)


def iou(a, b):
    ax, ay, bx, by = a["xyxy"]
    cx, cy, dx, dy = b["xyxy"]
    overlap = max(0, min(bx, dx) - max(ax, cx)) * max(0, min(by, dy) - max(ay, cy))
    return overlap / ((bx - ax) * (by - ay) + (dx - cx) * (dy - cy) - overlap)


def box_differences(a, b):
    possible = [(iou(one, two), i, j) for (i, one), (j, two) in product(enumerate(a), enumerate(b))]
    used_a, used_b, report = set(), set(), []
    # Pair unambiguous matches first, then report residual overlapping differences.
    for phase in ("agreement", "disagreement"):
        for overlap, i, j in sorted(possible, key=lambda item: (-item[0], item[1], item[2])):
            same = a[i]["label"] == b[j]["label"]
            if i in used_a or j in used_b or overlap <= 0:
                continue
            if phase == "agreement" and not (same and overlap >= .5):
                continue
            status = "agreement" if phase == "agreement" else ("extent" if same else "class")
            used_a.add(i)
            used_b.add(j)
            report.append({"status": status, "iou": round(overlap, 4), "a": a[i], "b": b[j]})
    for role, boxes, used in (("a", a, used_a), ("b", b, used_b)):
        report.extend({"status": f"only_{role}", role: box} for i, box in enumerate(boxes) if i not in used)
    return report


def compare(root, submissions=None):
    a, b = [queue_records(root, role)[1] for role in ROLES]
    checks = []
    if submissions is not None:
        for role, source, roster in zip(ROLES, submissions, (a, b), strict=True):
            check, labels = inspect_submission(root, source, expected_role=role)
            checks.append(check)
            for ident, row in roster.items():
                row["annotation"] = labels.get(ident)
    result, counts = [], Counter()
    actors = [{row["annotation"]["actor"].casefold() for row in queue.values() if row["annotation"]} for queue in (a, b)]
    independent_ids = all(len(team) == 1 for team in actors) and not actors[0] & actors[1]
    for ident, left in a.items():
        right = b[ident]
        if left["image_sha256"] != right["image_sha256"]:
            raise ValueError(f"Practice image hashes differ for {ident}.")
        one, two = left["annotation"], right["annotation"]
        if not one or not two:
            status = "pending_both" if not one and not two else "pending_a" if not one else "pending_b"
            counts[status] += 1
            result.append({"id": ident, "status": status})
            continue
        one, two = validate_annotation(left, one), validate_annotation(right, two)
        differences = box_differences(one["boxes"], two["boxes"])
        status = "agree" if one["kind"] == two["kind"] and all(d["status"] == "agreement" for d in differences) else "disagree"
        counts[status] += 1
        result.append({"id": ident, "status": status, "a": one, "b": two, "box_comparison": differences})
    return {"counts": dict(counts), "distinct_annotator_ids": bool(independent_ids),
            "note": "Human practice comparison only. Review disagreements together; nothing was approved.",
            "images": result, "submission_checks": checks}

def comparison_markdown(result):
    lines = ["# Private practice disagreement report", "", result["note"], ""]
    lines.append("Queue status: " + ", ".join(f"{name.replace('_', ' ')}: {count}" for name, count in result["counts"].items()))
    lines.append("Distinct IDs in both queues: " + ("yes" if result["distinct_annotator_ids"] else "not confirmed"))
    for check in result["submission_checks"]:
        lines.append(f"{check['queue']}: {check['valid']} / {check['expected']} valid records.")
        if check["missing_ids"]:
            lines.append("Missing IDs: " + ", ".join(check["missing_ids"]))
        if check["invalid_ids"]:
            lines.append("Invalid IDs: " + ", ".join(check["invalid_ids"]))
        lines.extend(f"- {escape(issue)}" for issue in check["issues"])
    lines.append("")
    for image in result["images"]:
        lines.append(f"## {image['id']} · {image['status'].replace('_', ' ')}")
        if "a" in image:
            for role in ("a", "b"):
                label = image[role]
                lines.append(f"- {role.upper()} selected {label['kind']} and recorded: {escape(label['note'])}")
            for difference in image["box_comparison"]:
                if difference["status"] == "agreement":
                    continue
                left, right = (difference.get(role) for role in ("a", "b"))
                lines.append(f"- {difference['status'].replace('_', ' ')}: A {left or '—'} / B {right or '—'}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import os

    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("package")
    make.add_argument("role", choices=ROLES)
    make.add_argument("output", type=Path)
    commands.add_parser("import").add_argument("source", type=Path)
    commands.add_parser("compare").add_argument("output", type=Path)
    validate = commands.add_parser("validate")
    validate.add_argument("source", type=Path)
    validate.add_argument("output", type=Path)
    files = commands.add_parser("compare-files")
    for field in ("annotator_a", "annotator_b", "output"):
        files.add_argument(field, type=Path)
    args = parser.parse_args()
    try:
        root = private_path(args.root)
        if args.command == "package":
            package(root, args.role, private_path(args.output))
        elif args.command == "import":
            print(f"Imported {import_submission(root, private_path(args.source))} human practice annotations.")
        elif args.command == "validate":
            check, _ = inspect_submission(root, private_path(args.source))
            write_json(private_path(args.output), check)
            print(f"{check['valid']} / {check['expected']} valid; {len(check['issues'])} issue(s).")
            if check["issues"] or check["missing_ids"]:
                raise SystemExit(1)
        else:
            files = (private_path(args.annotator_a), private_path(args.annotator_b)) if args.command == "compare-files" else None
            result = compare(root, files)
            output = private_path(args.output)
            if output.suffix == ".md":
                output.write_text(comparison_markdown(result), encoding="utf-8")
            else:
                write_json(output, result)
            print(json.dumps(result["counts"]))
            if files and (not result["distinct_annotator_ids"] or not result["counts"].keys() <= {"agree", "disagree"}
                          or any(check["issues"] for check in result["submission_checks"])):
                raise SystemExit(1)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))
