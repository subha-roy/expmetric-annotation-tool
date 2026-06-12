import argparse
import json
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "pilot_decomposed.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "pilot_decomposed.json"
DEFAULT_IMAGE_SOURCE = PROJECT_ROOT.parent / "v2" / "coco2017_val" / "val2017"
DEFAULT_IMAGE_OUTPUT = PROJECT_ROOT / "images"


def normalize_part(part):
    return {
        "part_id": part.get("part_id"),
        "text": part.get("text"),
        "type": part.get("type"),
        "decomp_quality": part.get("decomp_quality"),
        "label": part.get("label"),
        "importance": part.get("importance", part.get("severity")),
        "error_type": part.get("error_type"),
    }


def normalize_sample(sample):
    return {
        "sample_id": sample.get("sample_id"),
        "image_id": sample.get("image_id"),
        "image_file": sample.get("image_file"),
        "caption": sample.get("caption"),
        "parts": [normalize_part(part) for part in sample.get("parts", [])],
    }


def load_samples(path):
    if path.suffix == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"{path} must contain a JSON array")
        return [normalize_sample(sample) for sample in data]

    samples = []
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(normalize_sample(json.loads(line)))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc
    return samples


def copy_images(samples, source_dir, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    missing = []

    for sample in samples:
        image_file = sample.get("image_file")
        if not image_file:
            continue
        source = source_dir / image_file
        target = output_dir / image_file
        if not source.exists():
            missing.append(image_file)
            continue
        if not target.exists() or source.stat().st_mtime_ns > target.stat().st_mtime_ns:
            shutil.copy2(source, target)
            copied += 1

    return copied, missing


def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert pilot decompositions to the static annotation app JSON format."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--image-source", type=Path, default=DEFAULT_IMAGE_SOURCE)
    parser.add_argument("--image-output", type=Path, default=DEFAULT_IMAGE_OUTPUT)
    parser.add_argument("--no-copy-images", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    samples = load_samples(args.input)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(samples, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Wrote {len(samples)} samples to {args.output}")

    if not args.no_copy_images:
        copied, missing = copy_images(samples, args.image_source, args.image_output)
        print(f"Copied/updated {copied} images into {args.image_output}")
        if missing:
            print(f"Missing {len(missing)} images")
            for image_file in missing[:20]:
                print(f"  {image_file}")
            if len(missing) > 20:
                print(f"  ... {len(missing) - 20} more")


if __name__ == "__main__":
    main()
