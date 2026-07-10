"""
Test rapide et isolé de la détection YOLO + filtre géométrique,
sans passer par tout le pipeline (proximité, équipes, routage...).

Lancer avec : python src/test_filtre_pp.py
"""

from pathlib import Path
import IA_PP

BASE_DIR = Path(__file__).parent.parent
DOSSIER_SORTIE = BASE_DIR / "data" / "raw" / "images_pp" / "test_filtre"
DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)

# Quelques intersections de data/raw/intersections_upload.csv (Montrouge)
INTERSECTIONS_TEST = [
    (48.81984863, 2.325496304, "Avenue Aristide Briand D920 - Boulevard Romain Rolland"),
    (48.817540515, 2.325639555, "Avenue Aristide Briand D920 - Rue Barbès D50"),
    (48.812006362, 2.326151496, "Avenue Aristide Briand D920 - Rue de Thalheimer"),
]

for lat, lon, nom in INTERSECTIONS_TEST:
    print(f"\n=== {nom} ({lat:.5f}, {lon:.5f}) ===")
    chemin_img = DOSSIER_SORTIE / f"{lat:.5f}_{lon:.5f}.jpg"

    res = IA_PP.analyser_intersection_filtre(
        lat, lon,
        rayon_filtre_m=25,
        sauvegarder_image_annotee=str(chemin_img),
    )
    print(res)
    if res["image_ok"]:
        print(f"Image annotée : {chemin_img}")
