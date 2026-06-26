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
    # ETAPE 1 : on importe les modules du pipeline ici pour éviter les imports circulaires
    # identification_PM interroge les APIs gouvernementales (BAN, Overpass) pour trouver les lieux
    from identification_PM import construire_dataframe_PM
    from proximite import filtre_distance

    # ETAPE 2 : on génère la liste des Points de Mobilité (écoles, mairies, hôpitaux…) pour la ville
    print(f"\nGénération des Points de Mobilité pour '{ville}' (APIs gouvernementales + OSM)...")
    df_pm = construire_dataframe_PM(ville)

    if df_pm.empty:
        raise ValueError(
            f"Aucun PM trouvé pour '{ville}'. Vérifiez la connexion internet."
        )

    # ETAPE 3 : on sauvegarde les PM dans data/raw/ pour les réutiliser sans rappeler les APIs
    chemin_pm = os.path.join(
        os.path.dirname(__file__), "..", "data", "raw", f"PM_{ville}.xlsx"
    )
    df_pm.to_excel(chemin_pm, index=False)
    print(f"PM sauvegardés : {chemin_pm}  ({len(df_pm)} lieux)\n")

    # ETAPE 4 : on charge toutes les intersections de la ville depuis le CSV du 92
    df_inter = charger_intersections(ville)

    # ETAPE 5 : on renomme les colonnes pour les rendre compatibles avec filtre_distance()
    # filtre_distance() attend les noms "latitude", "longitude", "intersection" et non "lat", "lon", "nom"
    df_inter_compat = df_inter.rename(columns={
        "lat": "latitude",
        "lon": "longitude",
        "nom": "intersection",
    })

    # ETAPE 6 : on prépare aussi le DataFrame des PM avec les mêmes noms de colonnes
    df_lieux_pm = df_pm[["latitude", "longitude"]].copy()

    # ETAPE 7 : on filtre pour ne garder que les intersections proches d'un PM
    print(f"Filtrage : intersections à moins de {rayon_km * 1000:.0f} m d'un PM...")
    df_filtre = filtre_distance(df_lieux_pm, df_inter_compat, rayon_km=rayon_km)

    print(
        f"{len(df_filtre)} intersections retenues près des PM "
        f"(sur {len(df_inter)} dans {ville}).\n"
    )

    # ETAPE 8 : on remet les colonnes dans le format attendu par generer_images() (lat, lon, nom)
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
    # ETAPE 1 : si aucun seuil fourni, on prend la moitié de l'emprise de l'image (40 m par défaut)
    # en dessous de cette distance, deux images seraient quasi-identiques donc inutiles pour l'entraînement
    if seuil_m is None:
        seuil_m = EMPRISE_M / 2

    # ETAPE 2 : on convertit le seuil en degrés pour pouvoir comparer directement avec lat/lon
    # 1 degré de latitude ≈ 111 000 m, approximation suffisante à l'échelle d'une ville
    seuil_deg = seuil_m / 111_000.0

    # ETAPE 3 : on prépare une liste de booléens pour marquer les intersections à conserver
    lignes = df.reset_index(drop=True).copy()
    garder = [True] * len(lignes)

    # ETAPE 4 : pour chaque paire d'intersections, si elles sont trop proches on supprime la seconde
    # on ne supprime jamais la première (i) pour garder un maximum d'intersections bien réparties
    for i in range(len(lignes)):
        if not garder[i]:
            continue
        for j in range(i + 1, len(lignes)):
            if not garder[j]:
                continue
            dlat = abs(lignes.at[i, "lat"] - lignes.at[j, "lat"])
            dlon = abs(lignes.at[i, "lon"] - lignes.at[j, "lon"])
            if dlat < seuil_deg and dlon < seuil_deg:
                garder[j] = False

    # ETAPE 5 : on applique le filtre et on affiche le bilan de la déduplication
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
    # ETAPE 1 : on charge le fichier CSV contenant toutes les intersections des communes du 92
    df = pd.read_csv(CSV_INTERSECTIONS)

    # ETAPE 2 : on filtre les lignes correspondant à la ville demandée
    # startswith() plutôt que contains() pour éviter les faux positifs (ex: "Garches" dans "Garches-sur-...")
    masque = df["properties/context"].str.startswith(ville, na=False)
    df_ville = df[masque].copy()

    # ETAPE 3 : si aucune intersection trouvée, on affiche les villes disponibles pour aider l'utilisateur
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

    # ETAPE 4 : on renomme les colonnes du CSV vers les noms standards du pipeline (lat, lon, nom)
    # et on supprime les doublons géographiques exacts (même coordonnées)
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

    # ETAPE 5 : on supprime les intersections trop proches pour éviter les images quasi-identiques
    df_ville = dedupliquer_proches(df_ville)

    # ETAPE 6 : si une limite est demandée, on tronque le tableau
    if max_images:
        df_ville = df_ville.head(max_images)

    return df_ville


# ---------------------------------------------------------------------------
# Étape 2 — Dossier de sortie horodaté
# ---------------------------------------------------------------------------

def nom_dossier_sortie(ville: str) -> str:
    """
    Génère le chemin du dossier de sortie :
        dataset/images/{ville}_{DD-MM-YYYY_HHhMM-SS}/
    """
    # ETAPE 1 : on remplace les caractères spéciaux (tirets, espaces, accents) par des underscores
    # pour que le nom du dossier soit valide sur tous les systèmes (Windows, Linux, Mac)
    ville_safe = re.sub(r"[^\w]", "_", ville)
    # ETAPE 2 : on ajoute l'horodatage en format français pour distinguer plusieurs analyses de la même ville
    horodatage = datetime.now().strftime("%d-%m-%Y_%Hh%M-%S")
    return os.path.join(DOSSIER_DATASET, f"{ville_safe}_{horodatage}")


# ---------------------------------------------------------------------------
# Étape 3 — Nom de fichier sûr
# ---------------------------------------------------------------------------

def nom_fichier_safe(ville: str, index: int) -> str:
    """Génère un nom de fichier au format fichier_analyse_{ville}_{index}.jpg."""
    # ETAPE 1 : on remplace les caractères spéciaux par des underscores
    ville_safe = re.sub(r"[^\w]", "_", ville)
    # ETAPE 2 : on supprime les underscores en double et en début/fin de chaîne
    ville_safe = re.sub(r"_+", "_", ville_safe).strip("_")
    # ETAPE 3 : on numérote sur 3 chiffres pour que les fichiers se trient correctement (001, 002…)
    return f"fichier_analyse_{ville_safe}_{index:03d}.jpg"


# ---------------------------------------------------------------------------
# Étape 4 — Télécharger et sauvegarder les images
# ---------------------------------------------------------------------------

def generer_images(df: pd.DataFrame, dossier_out: str, ville: str) -> pd.DataFrame:
    """
    Télécharge une image IGN par intersection et la sauvegarde.
    Retourne le DataFrame enrichi avec le chemin du fichier image.
    """
    # ETAPE 1 : on crée le dossier de sortie s'il n'existe pas encore
    os.makedirs(dossier_out, exist_ok=True)
    total = len(df)
    chemins = []

    for i, row in df.iterrows():
        nom_fichier = nom_fichier_safe(ville, i)
        chemin_complet = os.path.join(dossier_out, nom_fichier)

        print(f"[{i+1}/{total}] {row['nom'][:50]} ...", end=" ", flush=True)

        # ETAPE 2 : si l'image existe déjà (reprise après interruption), on ne la retélécharge pas
        if os.path.exists(chemin_complet):
            print("déjà téléchargée, on passe.")
            chemins.append(chemin_complet)
            continue

        try:
            # ETAPE 3 : on télécharge l'orthophoto IGN centrée sur les coordonnées de l'intersection
            image = get_image_ign(
                lat=row["lat"],
                lon=row["lon"],
                emprise_m=EMPRISE_M,
                taille_px=TAILLE_PX,
            )
            # ETAPE 4 : on convertit le tableau numpy en image JPEG et on la sauvegarde
            Image.fromarray(image).save(chemin_complet)
            print("OK")
            chemins.append(chemin_complet)
        except Exception as e:
            # en cas d'erreur réseau ou IGN, on note None pour cette intersection et on continue
            print(f"ERREUR : {e}")
            chemins.append(None)

        # ETAPE 5 : on attend entre chaque requête pour ne pas surcharger le serveur IGN
        if i < total - 1:
            time.sleep(DELAI_S)

    # ETAPE 6 : on ajoute la colonne "image" au DataFrame avec les chemins des fichiers générés
    df = df.copy()
    df["image"] = chemins
    return df


# ---------------------------------------------------------------------------
# Étape 5 — Sauvegarder l'index
# ---------------------------------------------------------------------------

def sauvegarder_index(df: pd.DataFrame, dossier_out: str) -> None:
    # ETAPE 1 : on sauvegarde un fichier _index.csv dans le dossier des images
    # ce fichier fait le lien entre chaque image et ses coordonnées GPS d'origine
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
    print(f"=== Génération dataset YOLO — {ville} — {datetime.now().strftime('%d-%m-%Y %Hh%M')} ===\n")

    # ETAPE 1 : on choisit le mode de chargement selon que --pm est activé ou non
    # mode PM : filtre les intersections proches des écoles, mairies, hôpitaux…
    # mode normal : prend toutes les intersections de la ville
    try:
        if args.pm:
            print(f"Mode PM activé — rayon {args.rayon * 1000:.0f} m autour des Points de Mobilité")
            df_intersections = charger_intersections_avec_pm(ville, rayon_km=args.rayon)
        else:
            print(f"Chargement des intersections de '{ville}'...")
            df_intersections = charger_intersections(ville, max_images=args.max)
    except ValueError as e:
        # si la ville n'est pas trouvée dans le CSV, on affiche l'erreur et on arrête proprement
        print(f"\nERREUR : {e}")
        sys.exit(1)

    # ETAPE 2 : si --pm et --max sont utilisés ensemble, on applique la limite après le filtrage PM
    if args.pm and args.max:
        df_intersections = df_intersections.head(args.max)

    print(f"{len(df_intersections)} intersections à télécharger.\n")

    # ETAPE 3 : on crée le dossier horodaté et on lance le téléchargement des images IGN
    dossier_out = nom_dossier_sortie(ville)
    print(f"Téléchargement des images vers :\n  {dossier_out}\n")

    df_final = generer_images(df_intersections, dossier_out, ville)

    # ETAPE 4 : on sauvegarde l'index CSV pour garder la trace des coordonnées de chaque image
    sauvegarder_index(df_final, dossier_out)

    # ETAPE 5 : on affiche le bilan final avec le nombre d'images réussies
    ok = df_final["image"].notna().sum()
    print(f"\nTerminé : {ok}/{len(df_final)} images téléchargées.")
    print("Prochaine étape : annoter les images dans Roboflow")
