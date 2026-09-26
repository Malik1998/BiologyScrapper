import os
import re
from collections import defaultdict
from typing import Dict, List, Tuple, Iterator, Optional
import PIL


def parse_filename(filename: str):
    # 001A05.jpg -> ("001", 5)
    match = re.match(r"(\d+)A(\d+)", filename)
    if not match:
        raise ValueError(f"Bad filename: {filename}")

    return match.group(1), int(match.group(2))


def load_pts_lazy(points_dir: str, filename: str):
    """
    читаем .pts только когда нужно
    """
    path = os.path.join(points_dir, filename.replace(".jpg", ".pts"))

    if not os.path.exists(path):
        return None

    points = []
    with open(path, "r") as f:
        lines = f.readlines()

    reading = False
    for line in lines:
        line = line.strip()

        if line == "{":
            reading = True
            continue
        if line == "}":
            break

        if reading:
            x, y = map(float, line.split())
            points.append((x, y))

    return points


def build_index(images_dir: str):
    """
    Один раз читаем только список файлов
    """
    index = defaultdict(list)

    for filename in os.listdir(images_dir):
        if not filename.lower().endswith(".jpg"):
            continue

        person_id, age = parse_filename(filename)
        index[person_id].append((age, filename))

    return index


def iter_fgnet_by_id(root_dir: str = "../assets/data/FGNET") -> Iterator[List[dict]]:
    images_dir = os.path.join(root_dir, "images")
    points_dir = os.path.join(root_dir, "points")

    index = build_index(images_dir)
    groups = []
    for person_id in sorted(index.keys()):

        items = index[person_id]

        # сортировка внутри по возрасту
        items.sort(key=lambda x: x[0])

        group = []

        for age, filename in items:
            image_path = os.path.join(images_dir, filename)

            group.append({
                "id": person_id,
                "image": PIL.Image.open(image_path),
                "age": age,
                "points": load_pts_lazy(points_dir=points_dir, filename=filename),  # можно лениво загрузить позже
            })

        yield group
