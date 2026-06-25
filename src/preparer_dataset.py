import json
import math
import shutil
import random
from pathlib import Path

# Chemin vers le fichier JSON exporté depuis Label Studio
JSON_EXPORT = Path(r"C:\Users\martinant de preneuf\Downloads\project-1-at-2026-06-24-16-31-25801ac1.json")

# Dossier où Label Studio stocke les images uploadées (projet 1)
LS_UPLOAD = Path(r"C:\Users\martinant de preneuf\AppData\Local\label-studio\label-studio\media\upload\1")

OUTPUT_DIR = Path("dataset/yolo")
DATA_YAML  = Path("dataset/data.yaml")


def ls_to_yolo(result):
    """Convertit une annotation rectanglelabels Label Studio en ligne YOLO.

    Label Studio donne x,y (coin haut-gauche en %) + width/height (en %) + rotation (degrés).
    YOLO attend : cx cy w h normalisés [0-1] sans rotation (bounding box alignée sur les axes).
    On calcule la bounding box alignée (AABB) du rectangle tourné.
    """
    v = result["value"]
    x, y  = v["x"], v["y"]           # coin haut-gauche en %
    w, h  = v["width"], v["height"]   # dimensions en %
    theta = math.radians(v.get("rotation", 0))

    cx, cy = x + w / 2, y + h / 2    # centre du rectangle en %
    hw, hh = w / 2, h / 2

    # Demi-dimensions de la AABB du rectangle tourné
    aabb_hw = abs(hw * math.cos(theta)) + abs(hh * math.sin(theta))
    aabb_hh = abs(hw * math.sin(theta)) + abs(hh * math.cos(theta))

    # Clamp dans les limites de l'image
    xmin = max(0.0, cx - aabb_hw)
    xmax = min(100.0, cx + aabb_hw)
    ymin = max(0.0, cy - aabb_hh)
    ymax = min(100.0, cy + aabb_hh)

    yolo_cx = (xmin + xmax) / 2 / 100
    yolo_cy = (ymin + ymax) / 2 / 100
    yolo_w  = (xmax - xmin) / 100
    yolo_h  = (ymax - ymin) / 100

    return f"0 {yolo_cx:.6f} {yolo_cy:.6f} {yolo_w:.6f} {yolo_h:.6f}"


def prepare_dataset(train_ratio=0.8):
    if not JSON_EXPORT.exists():
        print(f"ERREUR : fichier JSON introuvable : {JSON_EXPORT}")
        return
    if not LS_UPLOAD.exists():
        print(f"ERREUR : dossier images Label Studio introuvable : {LS_UPLOAD}")
        return

    tasks = json.loads(JSON_EXPORT.read_text(encoding="utf-8"))
    print(f"Tâches dans le JSON : {len(tasks)}")

    pairs = []
    skipped = 0

    for task in tasks:
        filename = task["file_upload"]
        img_path = LS_UPLOAD / filename

        if not img_path.exists():
            print(f"  Image manquante : {filename}")
            skipped += 1
            continue

        lines = []
        annotations = task.get("annotations", [])
        if annotations:
            for result in annotations[0].get("result", []):
                if result.get("type") == "rectanglelabels":
                    lines.append(ls_to_yolo(result))

        pairs.append((img_path, lines))

    print(f"Paires trouvées : {len(pairs)} | Images manquantes : {skipped}")

    # Supprimer l'ancien dataset pour repartir proprement
    if OUTPUT_DIR.exists():
        try:
            shutil.rmtree(OUTPUT_DIR)
        except PermissionError:
            print("Avertissement : impossible de supprimer l'ancien dataset/yolo (fermez l'explorateur de fichiers si ouvert).")
            print("Les fichiers existants seront écrasés.")

    random.seed(42)
    random.shuffle(pairs)
    split = int(len(pairs) * train_ratio)
    train_pairs = pairs[:split]
    val_pairs   = pairs[split:]
    print(f"Train : {len(train_pairs)} | Val : {len(val_pairs)}")

    for split_name, split_pairs in [("train", train_pairs), ("val", val_pairs)]:
        img_out = OUTPUT_DIR / "images" / split_name
        lbl_out = OUTPUT_DIR / "labels" / split_name
        img_out.mkdir(parents=True, exist_ok=True)
        lbl_out.mkdir(parents=True, exist_ok=True)

        for img_path, label_lines in split_pairs:
            shutil.copy2(img_path, img_out / img_path.name)
            lbl_file = lbl_out / (img_path.stem + ".txt")
            lbl_file.write_text("\n".join(label_lines), encoding="utf-8")

    DATA_YAML.write_text(
        "path: ../dataset/yolo\n"
        "train: images/train\n"
        "val: images/val\n\n"
        "nc: 1\n"
        "names: ['passage_pieton']\n"
    )

    print(f"\ndata.yaml créé : {DATA_YAML}")
    print(f"Dataset prêt dans : {OUTPUT_DIR}")
    print("\nProchaine étape : uploader dataset/yolo/ et dataset/data.yaml sur Google Drive")


if __name__ == "__main__":
    prepare_dataset()
