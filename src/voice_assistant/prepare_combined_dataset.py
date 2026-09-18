from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read_tsv(path: Path) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        item_id, text, wav = line.split("\t", 2)
        rows.append((item_id, text, wav))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="合并真人锚点与火山教师语音，保留真人 holdout")
    parser.add_argument("--real-manifest", type=Path, required=True)
    parser.add_argument("--cloud-dataset", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.real_manifest.read_text(encoding="utf-8-sig"))
    real_train: list[tuple[str, str, str]] = []
    real_holdout: list[dict] = []
    for row in manifest["rows"]:
        split = row.get("split")
        if split == "train" and row.get("file"):
            real_train.append((f"real_{row['id']}", row["text"], str(Path(row["file"]).resolve())))
        elif split == "holdout" and row.get("file"):
            real_holdout.append({
                "id": row["id"], "text": row["text"], "wav": str(Path(row["file"]).resolve()),
                "seconds": row["seconds"], "sha256": row.get("sha256"),
            })

    cloud_train: list[tuple[str, str, str]] = []
    cloud_dev: list[tuple[str, str, str]] = []
    for dataset in args.cloud_dataset:
        cloud_train.extend(_read_tsv(dataset / "custom_train.tsv"))
        cloud_dev.extend(_read_tsv(dataset / "custom_dev.tsv"))

    train = [*real_train, *cloud_train]
    dev = cloud_dev
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "custom_train.tsv").write_text(
        "".join(f"{item_id}\t{text}\t{wav}\n" for item_id, text, wav in train), encoding="utf-8"
    )
    (args.output_dir / "custom_dev.tsv").write_text(
        "".join(f"{item_id}\t{text}\t{wav}\n" for item_id, text, wav in dev), encoding="utf-8"
    )
    summary = {
        "real_train_utterances": len(real_train),
        "cloud_train_utterances": len(cloud_train),
        "cloud_dev_utterances": len(cloud_dev),
        "real_holdout_utterances": len(real_holdout),
        "real_holdout": real_holdout,
        "policy": "真人干净片段与云端教师语音共同训练；真人 holdout 不参与训练或调参。",
    }
    (args.output_dir / "combined-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary | {"real_holdout": f"{len(real_holdout)} clips"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
