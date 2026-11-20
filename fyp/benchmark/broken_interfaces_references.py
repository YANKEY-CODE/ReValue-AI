"""Pair registered Broken Interfaces crops with published visual references."""
import argparse
import hashlib
from io import BytesIO
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps, ImageStat

from dataset import BI_URL, digest, practice_ids, private_path, records, write_json


def stage(root, checkout):
    revision = BI_URL.rsplit("/", 1)[-1]
    head = subprocess.check_output(["git", "-C", checkout, "rev-parse", "HEAD"], text=True).strip()
    if head != revision:
        raise ValueError("Check out the pinned Broken Interfaces revision first.")
    rows = [r for r in records(root).values() if r["source"] == BI_URL]
    if len(rows) != 95:
        raise ValueError("Register all 95 official display crops with dataset.py import-broken first.")
    destination = root / "source_overlays"
    if destination.exists():
        raise ValueError("Source overlays already exist. Use the existing references.")
    reserved = practice_ids(root)
    if len(reserved.intersection(row["id"] for row in rows)) != 10:
        raise ValueError("Reserve the ten Broken Interfaces practice crops first.")
    findings = []
    with TemporaryDirectory(dir=root) as temp:
        staged = Path(temp) / "source_overlays"
        staged.mkdir(mode=0o700)
        for row in rows:
            identifier = row["id"]
            crop = root / "images" / (identifier + ".png")
            asset = "phone_damage_overlay/" + Path(row["source_asset"]).with_suffix(".png").name
            if digest(crop) != row["image_sha256"]:
                raise ValueError(f"Registered display pixels changed for {identifier}.")
            with Image.open(crop) as photo:
                photo.load()
                stats = ImageStat.Stat(ImageOps.grayscale(photo))
                mean, contrast = stats.mean[0], stats.stddev[0]
            finding = {
                "id": identifier, "asset": asset, "short_edge": min(row["width"], row["height"]),
                "mean_brightness": round(mean, 2), "grayscale_stddev": round(contrast, 2),
                "practice": identifier in reserved, "reference_staged": False,
            }
            findings.append(finding)
            if identifier in reserved:
                continue
            # Read the pinned object directly so working-tree changes cannot alter a reference.
            raw = subprocess.check_output(["git", "-C", checkout, "show", f"{revision}:{asset}"])
            output = staged / (identifier + ".png")
            with Image.open(BytesIO(raw)) as overlay:
                if (overlay.format != "PNG" or overlay.size != (row["width"], row["height"])
                        or getattr(overlay, "n_frames", 1) != 1):
                    raise ValueError(f"Unexpected source overlay dimensions or format for {identifier}.")
                overlay.convert("RGB").save(output, format="PNG", compress_level=1)
            finding["reference_staged"] = True
            finding["source_sha256"] = hashlib.sha256(raw).hexdigest()
            finding["normalized_sha256"] = digest(output)
        write_json(staged / "audit.json", {"source": BI_URL, "records": findings})
        staged.rename(destination)
    return findings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    args = parser.parse_args()
    try:
        findings = stage(private_path(args.root), private_path(args.checkout))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    print(f"Staged {sum(item['reference_staged'] for item in findings)} unclassified author overlays.")
