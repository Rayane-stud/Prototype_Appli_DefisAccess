"""
Génération automatique d'images d'entraînement pour le modèle YOLO.

Lit les intersections depuis data/raw/intersections-92.csv,
filtre par ville, et télécharge l'orthophoto IGN de chaque intersection.

Utilisation :
    python src/generer_dataset.py Garches
    python src/generer_dataset.py "Fontenay-aux-Roses"
    python src/generer_dataset.py "Fontenay-aux-Roses" --max 50
    python src/generer_dataset.py Levallois-Perret --pm
    python src/generer_dataset.py Levallois-Perret --pm --rayon 0.3

Options :
    --pm           Filtre les intersections par proximité aux Points de Mobilité
                   (écoles, mairies, hôpitaux, supermarchés…) via identification_PM.py
    --rayon FLOAT  Rayon de proximité en km pour le filtre PM (défaut : 0.2 = 200 m)
    --max INT      Limite le nombre d'images téléchargées

Sortie :
    dataset/images/{ville}_{YYYY-MM-DD_HH-MM-SS}/<nom_safe>.jpg
    dataset/images/{ville}_{YYYY-MM-DD_HH-MM-SS}/_index.csv
"""

import os
import sys
import re
import time
import argparse
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from IA_PP import get_image_ign
from PIL import Image

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CSV_INTERSECTIONS = os.path.join(
    os.path.dirname(__file__), "..", "data", "raw", "intersections-92.csv"
)
DOSSIER_DATASET = os.path.join(
    os.path.dirname(__file__), "..", "dataset", "images"
)
EMPRISE_M = 80
TAILLE_PX = 640
DELAI_S   = 0.5


# ---------------------------------------------------------------------------
# Étape 1 — Charger les intersections depuis le CSV
# ---------------------------------------------------------------------------

def charger_intersections_avec_pm(ville: str, rayon_km: float = 0.2) -> pd.DataFrame:
    """
    Charge les intersections de la ville et les filtre par proximité
    aux Points de Mobilité (PM) générés via identification_PM.py.

    Args:
        ville    : Nom de la commune.
        rayon_km : Rayon de sélection autour de chaque PM en km (défaut 200 m).

    Returns:
        DataFrame avec colonnes lat, lon, nom — intersections proches des PM.
    """
    from identification_PM import construire_dataframe_PM
    from proximite import filtre_distance

    # Génération des PM via les APIs gouvernementales + OSM
    print(f"\nGénération des Points de Mobilité pour '{ville}' (APIs gouvernementales + OSM)...")
    df_pm = construire_dataframe_PM(ville)

    if df_pm.empty:
        raise ValueError(
            f"Aucun PM trouvé pour '{ville}'. Vérifiez la connexion internet."
        )

    # Sauvegarder le fichier PM dans data/raw/ pour réutilisation
    chemin_pm = os.path.join(
        os.path.dirname(__file__), "..", "data", "raw", f"PM_{ville}.xlsx"
    )
    df_pm.to_excel(chemin_pm, index=False)
    print(f"PM sauvegardés : {chemin_pm}  ({len(df_pm)} lieux)\n")

    # Charger toutes les intersections de la ville (colonnes lat, lon, nom)
    df_inter = charger_intersections(ville)

    # Renommer pour filtre_distance() qui attend latitude / longitude / intersection
    df_inter_compat = df_inter.rename(columns={
        "lat": "latitude",
        "lon": "longitude",
        "nom": "intersection",
    })

    # filtre_distance() attend aussi latitude/longitude dans df_lieux
    df_lieux_pm = df_pm[["latitude", "longitude"]].copy()

    print(f"Filtrage : intersections à moins de {rayon_km * 1000:.0f} m d'un PM...")
    df_filtre = filtre_distance(df_lieux_pm, df_inter_compat, rayon_km=rayon_km)

    print(
        f"{len(df_filtre)} intersections retenues près des PM "
        f"(sur {len(df_inter)} dans {ville}).\n"
    )

    # Renommer en retour vers le format attendu par generer_images()
    return (
        df_filtre
        .rename(columns={"latitude": "lat", "longitude": "lon", "intersection": "nom"})
        [["lat", "lon", "nom"]]
        .reset_index(drop=True)
    )


def dedupliquer_proches(df: pd.DataFrame, seuil_m: float = None) -> pd.DataFrame:
    """
    Supprime les intersections trop proches les unes des autres.

    Deux intersections séparées de moins de seuil_m produiraient des images
    quasi-identiques (l'image couvre EMPRISE_M mètres de côté).
    Par défaut on utilise EMPRISE_M / 2 comme seuil.

    Args:
        df      : DataFrame avec colonnes lat, lon.
        seuil_m : Distance minimale en mètres entre deux intersections conservées.

    Returns:
        DataFrame sans doublons géographiques.
    """
    if seuil_m is None:
        seuil_m = EMPRISE_M / 2  # 40 m par défaut

    seuil_deg = seuil_m / 111_000.0  # approximation rapide en degrés

    lignes = df.reset_index(drop=True).copy()
    garder = [True] * len(lignes)

    for i in range(len(lignes)):
        if not garder[i]:
            continue
        for j in range(i + 1, len(lignes)):
            if not garder[j]:
                continue
            dlat = abs(lignes.at[i, "lat"] - lignes.at[j, "lat"])
            dlon = abs(lignes.at[i, "lon"] - lignes.at[j, "lon"])
            if dlat < seuil_deg and dlon < seuil_deg:
                garder[j] = False  # on garde i, on supprime j

    avant = len(lignes)
    lignes["_garder"] = garder
    df_filtre = lignes[lignes["_garder"]].drop(columns=["_garder"]).reset_index(drop=True)
    print(f"Déduplication : {avant} → {len(df_filtre)} intersections ({avant - len(df_filtre)} doublons supprimés)")
    return df_filtre


def charger_intersections(ville: str, max_images: int = None) -> pd.DataFrame:
    """
    Lit intersections-92.csv et retourne les intersections de la ville demandée.

    Args:
        ville      : Nom de la commune (ex: "Garches", "Fontenay-aux-Roses").
        max_images : Limite le nombre d'intersections retournées (None = toutes).

    Returns:
        DataFrame avec les colonnes : lat, lon, nom.
    """
    df = pd.read_csv(CSV_INTERSECTIONS)

    masque = df["properties/context"].str.startswith(ville, na=False)
    df_ville = df[masque].copy()

    if df_ville.empty:
        villes_dispo = (
            df["properties/context"]
            .dropna()
            .str.split(",")
            .str[0]
            .unique()
            .tolist()
        )
        raise ValueError(
            f"Aucune intersection trouvée pour '{ville}' dans le CSV.\n"
            f"Villes disponibles (exemples) : {sorted(villes_dispo)[:15]}"
        )

    df_ville = (
        df_ville
        .rename(columns={
            "geometry/coordinates/1": "lat",
            "geometry/coordinates/0": "lon",
            "properties/name":        "nom",
        })[["lat", "lon", "nom"]]
        .drop_duplicates(subset=["lat", "lon"])
        .reset_index(drop=True)
    )

    df_ville = dedupliquer_proches(df_ville)

    if max_images:
        df_ville = df_ville.head(max_images)

    return df_ville


# ---------------------------------------------------------------------------
# Étape 2 — Dossier de sortie horodaté
# ---------------------------------------------------------------------------

def nom_dossier_sortie(ville: str) -> str:
    """
    Génère le chemin du dossier de sortie :
        dataset/images/{ville}_{YYYY-MM-DD_HH-MM-SS}/
    """
    ville_safe = re.sub(r"[^\w]", "_", ville)
    horodatage = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return os.path.join(DOSSIER_DATASET, f"{ville_safe}_{horodatage}")


# ---------------------------------------------------------------------------
# Étape 3 — Nom de fichier sûr
# ---------------------------------------------------------------------------

def nom_fichier_safe(ville: str, index: int) -> str:
    """Génère un nom de fichier au format fichier_analyse_{ville}_{index}.jpg."""
    ville_safe = re.sub(r"[^\w]", "_", ville)
    ville_safe = re.sub(r"_+", "_", ville_safe).strip("_")
    return f"fichier_analyse_{ville_safe}_{index:03d}.jpg"


# ---------------------------------------------------------------------------
# Étape 4 — Télécharger et sauvegarder les images
# ---------------------------------------------------------------------------

def generer_images(df: pd.DataFrame, dossier_out: str, ville: str) -> pd.DataFrame:
    """
    Télécharge une image IGN par intersection et la sauvegarde.
    Retourne le DataFrame enrichi avec le chemin du fichier image.
    """
    os.makedirs(dossier_out, exist_ok=True)
    total = len(df)
    chemins = []

    for i, row in df.iterrows():
        nom_fichier = nom_fichier_safe(ville, i)
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
# Étape 5 — Sauvegarder l'index
# ---------------------------------------------------------------------------

def sauvegarder_index(df: pd.DataFrame, dossier_out: str) -> None:
    chemin_index = os.path.join(dossier_out, "_index.csv")
    df.to_csv(chemin_index, index=False)
    print(f"\nIndex sauvegardé : {chemin_index}")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Génère des images IGN d'intersections pour une ville du 92."
    )
    parser.add_argument(
        "ville",
        nargs="?",
        default="Garches",
        help="Nom de la commune (ex: Garches, Fontenay-aux-Roses)",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=None,
        help="Nombre maximum d'images à télécharger (défaut : toutes)",
    )
    parser.add_argument(
        "--pm",
        action="store_true",
        help=(
            "Filtre les intersections par proximité aux Points de Mobilité "
            "(écoles, mairies, hôpitaux, supermarchés…) via identification_PM.py"
        ),
    )
    parser.add_argument(
        "--rayon",
        type=float,
        default=0.2,
        help="Rayon de proximité en km pour le filtre PM (défaut : 0.2 = 200 m)",
    )
    args = parser.parse_args()

    ville = args.ville
    print(f"=== Génération dataset YOLO — {ville} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")

    try:
        if args.pm:
            print(f"Mode PM activé — rayon {args.rayon * 1000:.0f} m autour des Points de Mobilité")
            df_intersections = charger_intersections_avec_pm(ville, rayon_km=args.rayon)
        else:
            print(f"Chargement des intersections de '{ville}'...")
            df_intersections = charger_intersections(ville, max_images=args.max)
    except ValueError as e:
        print(f"\nERREUR : {e}")
        sys.exit(1)

    if args.pm and args.max:
        df_intersections = df_intersections.head(args.max)

    print(f"{len(df_intersections)} intersections à télécharger.\n")

    dossier_out = nom_dossier_sortie(ville)
    print(f"Téléchargement des images vers :\n  {dossier_out}\n")

    df_final = generer_images(df_intersections, dossier_out, ville)
    sauvegarder_index(df_final, dossier_out)

    ok = df_final["image"].notna().sum()
    print(f"\nTerminé : {ok}/{len(df_final)} images téléchargées.")
    print("Prochaine étape : annoter les images dans makesense.ai")
