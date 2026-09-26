"""
Age estimation на детских изображениях из KinFaceW-I / KinFaceW-II.

В каждой паре "родитель-ребёнок" файл вида `<rel>_<id>_1.jpg` - это родитель,
а `<rel>_<id>_2.jpg` - ребёнок (см. ReadMe.txt в датасетах). Скрипт прогоняет
age estimation (DeepFace) только по файлам ребёнка и складывает результат в csv.

Модель гарантированно работает на CPU: GPU скрывается от TensorFlow ещё до
импорта DeepFace.
"""

import os

# Прячем GPU/Metal от TensorFlow до его импорта, чтобы инференс шёл на CPU.
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import argparse
import csv
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterator, Optional

import tensorflow as tf
from tqdm import tqdm

tf.config.set_visible_devices([], "GPU")

from deepface import DeepFace

RELATION_TO_CHILD_GENDER = {
    "father-dau": "female",
    "father-son": "male",
    "mother-dau": "female",
    "mother-son": "male",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

CHILD_SUFFIX = "_2"


@dataclass
class AgeEstimationResult:
    dataset: str
    relation: str
    child_gender: str
    pair_id: str
    filename: str
    image_path: str
    predicted_age: Optional[float]
    status: str


def iter_child_images(dataset_root: Path, dataset_name: str) -> Iterator[tuple[str, str, Path]]:
    """Идём по images/<relation>/ и отдаём только файлы ребёнка (`*_2.<ext>`)."""
    images_dir = dataset_root / "images"
    for relation_dir in sorted(images_dir.iterdir()):
        if not relation_dir.is_dir():
            continue
        relation = relation_dir.name
        for image_path in sorted(relation_dir.iterdir()):
            if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            stem = image_path.stem  # напр. fd_001_2
            if not stem.endswith(CHILD_SUFFIX):
                continue
            pair_id = stem[: -len(CHILD_SUFFIX)]
            yield dataset_name, relation, image_path


def estimate_age(image_path: Path) -> tuple[Optional[float], str]:
    """Возвращает (возраст, статус). Лица в KinFaceW уже выровнены и вырезаны 64x64,
    поэтому детектор не нужен - используем сырое изображение как есть."""
    try:
        result = DeepFace.analyze(
            img_path=str(image_path),
            actions=["age"],
            detector_backend="skip",
            enforce_detection=False,
            silent=True,
        )
        analysis = result[0] if isinstance(result, list) else result
        return float(analysis["age"]), "ok"
    except Exception as exc:  # noqa: BLE001 - хотим продолжить прогон на всём датасете
        return None, f"error: {exc}"


def run(dataset_roots: dict[str, Path], output_csv: Path, limit: Optional[int] = None) -> None:
    tasks = []
    for dataset_name, root in dataset_roots.items():
        tasks.extend(list(iter_child_images(root, dataset_name)))

    if limit is not None:
        tasks = tasks[:limit]

    rows: list[AgeEstimationResult] = []
    for dataset_name, relation, image_path in tqdm(tasks, desc="Age estimation (CPU)"):
        pair_id = image_path.stem[: -len(CHILD_SUFFIX)]
        age, status = estimate_age(image_path)
        rows.append(
            AgeEstimationResult(
                dataset=dataset_name,
                relation=relation,
                child_gender=RELATION_TO_CHILD_GENDER.get(relation, "unknown"),
                pair_id=pair_id,
                filename=image_path.name,
                image_path=str(image_path),
                predicted_age=age,
                status=status,
            )
        )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(rows[0]).keys()) if rows else [f.name for f in AgeEstimationResult.__dataclass_fields__.values()]
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    ok = sum(1 for r in rows if r.status == "ok")
    print(f"\nГотово: {ok}/{len(rows)} изображений обработано успешно.")
    print(f"Результат сохранён в: {output_csv}")


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Age estimation по детям из KinFaceW-I/II (CPU-only)")
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=["KinFaceW-I", "KinFaceW-II"],
        default=["KinFaceW-I", "KinFaceW-II"],
        help="Какие датасеты обработать",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=project_root,
        help="Директория, где лежат папки KinFaceW-I / KinFaceW-II",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "results" / "kinfacew_children_age_estimation.csv",
        help="Путь до итогового csv",
    )
    parser.add_argument("--limit", type=int, default=None, help="Ограничить число изображений (для быстрого теста)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset_roots = {name: args.data_root / name for name in args.datasets}
    for name, root in dataset_roots.items():
        if not root.exists():
            raise FileNotFoundError(f"Не найден датасет {name} по пути {root}")

    run(dataset_roots, args.output, args.limit)


if __name__ == "__main__":
    main()
