"""
Génération automatique d'images d'entraînement pour le modèle YOLO.

Utilise les intersections produites par le pipeline existant
(fichiers Garches_Equipe_*.xlsx) et télécharge l'orthophoto IGN
de chaque intersection via get_image_ign().

Utilisation :
    python src/generer_dataset.py

Sortie :
    dataset/images/garches/<nom_safe>.jpg   — images brutes
    dataset/images/garches/_index.csv       — index lat/lon/nom
"""

import os
import sys
import re
import time
import pandas as pd
from glob import glob

sys.path.insert(0, os.path.dirname(__file__))
from IA_PP import get_image_ign
from PIL import Image

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DOSSIER_OUTPUT   = os.path.join(
    os.path.dirname(__file__), "..", "data", "output"
)
DOSSIER_DATASET  = os.path.join(
    os.path.dirname(__file__), "..", "dataset", "images", "garches"
)
EMPRISE_M  = 80    # mètres couverts par chaque image
TAILLE_PX  = 640   # résolution (640 px = format standard YOLO)
DELAI_S    = 0.5   # pause entre requêtes IGN

# ---------------------------------------------------------------------------
# Étape 1 — Charger toutes les intersections des fichiers de sortie Garches
# ---------------------------------------------------------------------------

def charger_intersections_garches(dossier_output: str) -> pd.DataFrame:
    """
    Lit tous les fichiers Garches_Equipe_*.xlsx et renvoie un DataFrame
    dédupliqué avec les colonnes : lat, lon, nom.
    """
    pattern = os.path.join(dossier_output, "Garches_Equipe_*.xlsx")
    fichiers = sorted(glob(pattern))

    if not fichiers:
        raise FileNotFoundError(
            f"Aucun fichier Garches_Equipe_*.xlsx trouvé dans : {dossier_output}"
        )

    lignes = []
    for fichier in fichiers:
        df = pd.read_excel(fichier)
        for _, row in df.iterrows():
            coords_str = str(row.get("coordonnees", ""))
            nom = str(row.get("intersection", "sans_nom"))
            parts = coords_str.split(",")
            if len(parts) >= 2:
                try:
                    lat = float(parts[0].strip())
                    lon = float(parts[1].strip())
                    lignes.append({"lat": lat, "lon": lon, "nom": nom})
                except ValueError:
                    continue

    df_all = pd.DataFrame(lignes)
    df_all = df_all.drop_duplicates(subset=["lat", "lon"]).reset_index(drop=True)
    return df_all


# ---------------------------------------------------------------------------
# Étape 2 — Télécharger et sauvegarder les images
# ---------------------------------------------------------------------------

def nom_fichier_safe(nom: str, index: int) -> str:
    """Génère un nom de fichier valide à partir du nom d'intersection."""
    safe = re.sub(r"[^\w\-]", "_", nom)
    safe = re.sub(r"_+", "_", safe).strip("_")[:60]
    return f"{index:03d}_{safe}.jpg"


def generer_images(df: pd.DataFrame, dossier_out: str) -> pd.DataFrame:
    """
    Télécharge une image IGN par intersection et la sauvegarde.
    Retourne le DataFrame enrichi avec le chemin du fichier image.
    """
    os.makedirs(dossier_out, exist_ok=True)
    total = len(df)
    chemins = []

    for i, row in df.iterrows():
        nom_fichier = nom_fichier_safe(row["nom"], i)
        chemin_complet = os.path.join(dossier_out, nom_fichier)

        print(f"[{i+1}/{total}] {row['nom'][:50]} ...", end=" ", flush=True)

        if os.path.exists(chemin_complet):
            print("déjà téléchargée, on passe.")
            chemins.append(chemin_complet)
            continue

        try:
            image = get_image_ign(
                lat=row["lat"],
                lon=row["lon"],
                emprise_m=EMPRISE_M,
                taille_px=TAILLE_PX,
            )
            Image.fromarray(image).save(chemin_complet)
            print("OK")
            chemins.append(chemin_complet)
        except Exception as e:
            print(f"ERREUR : {e}")
            chemins.append(None)

        if i < total - 1:
            time.sleep(DELAI_S)

    df = df.copy()
    df["image"] = chemins
    return df


# ---------------------------------------------------------------------------
# Étape 3 — Sauvegarder l'index
# ---------------------------------------------------------------------------

def sauvegarder_index(df: pd.DataFrame, dossier_out: str) -> None:
    chemin_index = os.path.join(dossier_out, "_index.csv")
    df.to_csv(chemin_index, index=False)
    print(f"\nIndex sauvegardé : {chemin_index}")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Génération du dataset YOLO — Garches ===\n")

    print("Chargement des intersections...")
    df_intersections = charger_intersections_garches(DOSSIER_OUTPUT)
    print(f"{len(df_intersections)} intersections uniques trouvées.\n")

    print(f"Téléchargement des images vers : {DOSSIER_DATASET}\n")
    df_final = generer_images(df_intersections, DOSSIER_DATASET)

    sauvegarder_index(df_final, DOSSIER_DATASET)

    ok = df_final["image"].notna().sum()
    print(f"\nTerminé : {ok}/{len(df_final)} images téléchargées.")
    print("Prochaine étape : annoter les images dans Label Studio.")
