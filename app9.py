"""
FICHIER : app6.py

BUT : Nouvelle interface DEFIACCESS, organisée en pages (une par étape) au lieu
      d'accordéons empilés comme dans app5.py. Navigation via une barre latérale
      à 5 boutons (Présentation, Étape 1, Étape 2, Étape 3, Étape 4) + des
      boutons "Précédent"/"Suivant" en bas de chaque page.

      Les 4 étapes sont implémentées (Intersections, Lieux d'intérêt, Passages
      piétons, Fiches équipes). La carte finale (Étape 4) utilise Plotly plutôt
      que Folium : cliquer sur une ligne du tableau "📊 Répartition par équipe"
      met cette équipe en valeur sur la carte et grise les autres.

      app5.py n'est pas modifié par ce fichier.
"""
import os

# Contourne un conflit connu (Windows) entre les runtimes OpenMP embarqués par
# torch/ultralytics (IA - YOLO) et scikit-learn/k-means-constrained (chargé dès
# le démarrage via src.proximite) : conflit associé à un plantage "page blanche"
# lors de la génération des PP (Étape 3, méthodes IA/Mixte). Doit rester tout en
# haut du fichier, avant tout autre import, pour être lu par les runtimes OpenMP
# dès leur initialisation. setdefault : une valeur déjà définie côté shell reste
# prioritaire, on ne l'écrase pas.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np
import io
import zipfile
import contextlib
import yaml
import streamlit as st
import plotly.graph_objects as go
from streamlit_searchbox import st_searchbox
from math import cos, radians, sin, pi
import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image, ImageDraw
import sys
sys.path.append(str(Path(__file__).parent / "src"))

from src.nettoyage import charger_intersections
from src.proximite import (
    charger_points,
    filtre_distance,
    fusion_croisement,
    assigner_equipes,
)
from src.routage import route_toutes_equipes2
from src.export import export_final_equipes, generer_kml_global_une_colonne
from src.identification_PM import (
    get_code_insee_api,
    get_equipements_gouv,
    construire_dataframe_PM_sans_input_avec_filtres,
    CATEGORIES_FINESS_SANTE,
    CATEGORIE_FINESS_AUTRES,
    CATEGORIES_ECOLES,
    CATEGORIE_ECOLE_AUTRES,
    CATEGORIES_OSM_DISPONIBLES,
)
from src.telecharger_intersections import (
    generer_combinaisons_voies,
    filtrer_par_combinaisons_voies,
    chercher_communes_api,
    TYPES_VOIES_COMBO,
)

# Labels affichés pour chaque thème de filtre (théme -> liste de libellés)
LABELS_SANTE  = [c["label"] for c in CATEGORIES_FINESS_SANTE] + [CATEGORIE_FINESS_AUTRES]
LABELS_ECOLES = [c["label"] for c in CATEGORIES_ECOLES] + [CATEGORIE_ECOLE_AUTRES]
LABELS_OSM    = [c["label"] for c in CATEGORIES_OSM_DISPONIBLES]

# Image d'exemple pour illustrer le rayon du filtre géométrique IA (Étape 3).
# Orthophoto IGN fixe (80 m d'emprise, 512 px -> 6,4 px/m), sans annotation.
_EXEMPLE_INTERSECTION_IMG = Path(__file__).parent / "assets" / "exemple_intersection.jpg"
_EXEMPLE_INTERSECTION_EMPRISE_M = 80

# Serveurs Overpass de repli pour le téléchargement du réseau piéton (Étape 4,
# route_toutes_equipes2 dans src/routage.py) : contrairement à identification_PP.py,
# osmnx n'interroge qu'un seul serveur (overpass-api.de) sans repli — on bascule
# nous-mêmes sur un miroir via ox.settings.overpass_url si celui-ci ne répond pas.
SERVEURS_OVERPASS_ROUTAGE = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
]


@st.cache_data
def _image_rayon_exemple(rayon_m: float) -> Image.Image:
    """Dessine un cercle rouge de `rayon_m` mètres sur l'image d'exemple.

    Mise en cache par valeur de rayon : redessine seulement quand le nombre
    saisi par l'utilisateur change (pas de recalcul inutile à chaque rerun).
    """
    im = Image.open(_EXEMPLE_INTERSECTION_IMG).convert("RGB")
    largeur_px = im.size[0]
    px_par_m = largeur_px / _EXEMPLE_INTERSECTION_EMPRISE_M
    rayon_px = rayon_m * px_par_m
    cx, cy = largeur_px / 2, largeur_px / 2

    draw = ImageDraw.Draw(im)
    draw.ellipse([cx - rayon_px, cy - rayon_px, cx + rayon_px, cy + rayon_px],
                 outline=(255, 0, 0), width=3)
    draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 0, 0))
    return im

# Dans le thème "Autres lieux", seules ces catégories sont pré-cochées par défaut
LABELS_OSM_PRESELECTIONNES = ["Gares", "Gendarmeries (OSM)", "Bureaux de poste"]

# ─────────────────────────────────────────────
# 0. Configuration de la page
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="DEFIACCESS",
    page_icon="|DF|",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# 1. Chargement des configs YAML disponibles
# ─────────────────────────────────────────────
CONFIG_DIR = Path("config")


def load_yaml_configs() -> dict:
    configs = {}
    if CONFIG_DIR.exists():
        for yaml_file in sorted(CONFIG_DIR.glob("*.yaml")):
            with open(yaml_file, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            nom = cfg.get("commune", yaml_file.stem).split(",")[0].strip()
            configs[nom] = cfg
    return configs


yaml_configs = load_yaml_configs()

# ─────────────────────────────────────────────
# 1b. Constantes & helpers (repris de app5.py)
# ─────────────────────────────────────────────
COMBINAISONS_VOIES = generer_combinaisons_voies(TYPES_VOIES_COMBO)

# Dossier où telecharger_intersections.py sauvegarde les GeoJSON filtrés
# (chemin dynamique basé sur l'emplacement de l'app, portable sur le Cloud)
INTERSECTIONS_DIR = Path(__file__).parent / "data" / "raw" / "intersections"

# Sécurité : Crée le dossier s'il n'existe pas encore sur le serveur
INTERSECTIONS_DIR.mkdir(parents=True, exist_ok=True)


def chemin_geojson_commune(code_insee: str) -> Path:
    """Chemin du fichier GeoJSON local pour un code INSEE donné."""
    return INTERSECTIONS_DIR / f"intersections_{code_insee}.geojson"


def sauvegarder_index(ville: str, chemin: Path):
    import json
    index_path = INTERSECTIONS_DIR / "index.json"
    index = {}
    if index_path.exists():
        try:
            with open(index_path,encoding='utf-8',errors="replace") as f:
                index = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            index = {}
            
    # AVANT : index[ville.lower().strip()] = str(chemin)
    # MODIFICATION : On ne stocke QUE le nom du fichier (ex: "intersections_94002.geojson")
    index[ville.lower().strip()] = chemin.name

    with open(index_path, "w", encoding='utf-8',errors="replace") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def trouver_geojson_existant(ville: str) -> Path | None:
    import json
    ville_norm = ville.lower().strip()
    index_path = INTERSECTIONS_DIR / "index.json"

    # Priorité 1 : index.json (survit au refresh, O(1))
    if index_path.exists():
        # SI LE FICHIER EST VIDE (0 octet), ON ÉVITE LE CRASH
        if index_path.stat().st_size == 0:
            index = {}
        else:
            try:
                # LECTURE SÉCURISÉE AVEC ENCODAGE UTF-8
                with open(index_path, "r", encoding="utf-8", errors="replace") as f:
                    index = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                # SI LE FICHIER EST CORROMPU, ON NE PLANTE PAS
                index = {}
                
        chemin = index.get(ville_norm)


        if chemin:
            # MODIFICATION : On reconstruit le chemin complet sur le Cloud
            p = INTERSECTIONS_DIR / chemin           
            # AVANT  : p = Path(chemin)
            if p.exists():
                return p
            else:
                del index[ville_norm]
                with open(index_path, "w", encoding="utf-8",errors="replace") as f:
                    json.dump(index, f, ensure_ascii=False, indent=2)

    # Priorité 2 : fallback API (première fois uniquement)
    try:
        from src.telecharger_intersections import trouver_departements
        resultats = trouver_departements(ville)
        if not resultats:
            return None
        _, _, code_insee = resultats[0]
        chemin = chemin_geojson_commune(code_insee)
        if chemin.exists():
            sauvegarder_index(ville, chemin)
            return chemin
    except Exception:
        pass
    return None


def recuperer_coords_mairie(commune_str: str):
    """
    Tente de récupérer les coordonnées de la mairie via l'API Annuaire +
    géocodage BAN. Retourne (lat, lon) ou (None, None) si échec.
    """
    try:
        ville = commune_str.split(",")[0].strip()
        code_insee = get_code_insee_api(ville)
        if not code_insee:
            return None, None
        mairies = get_equipements_gouv(code_insee)
        if mairies:
            return mairies[0]["latitude"], mairies[0]["longitude"]
    except Exception:
        pass
    return None, None


def signature_filtres_pm(categories_sante, categories_ecoles, categories_osm_labels) -> tuple:
    """
    Empreinte des filtres PM sélectionnés (santé/écoles/autres lieux), pour
    détecter si les cases ont changé depuis la dernière génération des lieux
    et invalider le cache (df_pm/pm_buffer) le cas échéant.
    """
    return (
        tuple(sorted(categories_sante)),
        tuple(sorted(categories_ecoles)),
        tuple(sorted(categories_osm_labels)),
    )


def bloc_filtre_theme(
    titre: str, cle_prefixe: str, labels: list[str], labels_preselectionnes: list[str] | None = None
) -> list[str]:
    """
    Affiche un thème de filtre : titre, boutons "Tout sélectionner" /
    "Tout désélectionner", puis une case à cocher par catégorie (3 colonnes).

    labels_preselectionnes : labels cochés par défaut au premier affichage.
                              None = tous cochés par défaut.

    REPONSE : liste des labels cochés.
    """
    st.markdown(f"**{titre}**")

    valeurs_par_defaut = set(labels if labels_preselectionnes is None else labels_preselectionnes)

    # Mémoire "sticky" : contrairement à la clé du widget (perdue dès qu'on
    # quitte la page), ces clés normales survivent à la navigation entre
    # étapes et permettent de restaurer l'état coché/décoché au retour.
    def _sticky_key(lbl: str) -> str:
        return f"sticky_chk_{cle_prefixe}_{lbl}"

    col_sel_all, col_desel_all, _col_spacer = st.columns([1, 1, 3])
    with col_sel_all:
        if st.button("Tout sélectionner", key=f"{cle_prefixe}_select_all"):
            for lbl in labels:
                st.session_state[f"chk_{cle_prefixe}_{lbl}"] = True
                st.session_state[_sticky_key(lbl)] = True
            st.rerun()
    with col_desel_all:
        if st.button("Tout désélectionner", key=f"{cle_prefixe}_desel_all"):
            for lbl in labels:
                st.session_state[f"chk_{cle_prefixe}_{lbl}"] = False
                st.session_state[_sticky_key(lbl)] = False
            st.rerun()

    cols = st.columns(3)
    labels_choisis = []
    for i, lbl in enumerate(labels):
        with cols[i % 3]:
            valeur_defaut = st.session_state.get(_sticky_key(lbl), lbl in valeurs_par_defaut)
            coche = st.checkbox(lbl, value=valeur_defaut, key=f"chk_{cle_prefixe}_{lbl}")
            st.session_state[_sticky_key(lbl)] = coche
            if coche:
                labels_choisis.append(lbl)

    return labels_choisis


def _normaliser_ville(texte: str) -> str:
    # Traite tirets et espaces comme identiques pour comparer les noms de villes
    return texte.lower().replace("-", " ").replace("_", " ")


def _intersections_source_est_chemin(source) -> bool:
    """True si `source` est un chemin (str/Path) vers un GeoJSON auto-téléchargé,
    False si c'est un fichier importé via st.file_uploader (objet avec .name)."""
    return getattr(source, "name", None) is None


def charger_intersections_quelconque(source, combos_selectionnes: list | None = None):
    """
    Charge un DataFrame d'intersections depuis n'importe quelle source :
    - un chemin (str/Path) vers un GeoJSON auto-téléchargé (Étape 1 automatique),
    - un fichier importé (.csv, .xlsx ou .geojson) via st.file_uploader (Étape 1
      "fichier personnalisé").

    Applique le filtre par combinaisons de voies si `combos_selectionnes` est fourni
    et que la colonne 'intersection' est présente.
    """
    import pandas as pd
    from src.telecharger_intersections import charger_en_dataframe_sans_input

    if _intersections_source_est_chemin(source):
        df = charger_en_dataframe_sans_input(source, types_voies=[])
    else:
        nom = source.name
        source.seek(0)
        if nom.endswith(".csv"):
            df = pd.read_csv(source)
        elif nom.endswith(".geojson"):
            df = charger_en_dataframe_sans_input(source, types_voies=[])
        else:
            df = pd.read_excel(source)

    if combos_selectionnes and "intersection" in df.columns:
        df = filtrer_par_combinaisons_voies(df, combos_selectionnes)

    return df


def _joindre_nb_traversees_par_proximite(df_cible, df_pp, rayon_m: float = 30):
    """
    Rattache nb_traversees à chaque intersection de df_cible en cherchant la
    ligne de df_pp la plus proche (dans un rayon donné), sans jamais supprimer
    de ligne de df_cible.

    Contrairement à comparer_coordonnees (conçue pour comparer des points
    bruts un par un et qui supprime toute intersection sans correspondance),
    df_pp est ici déjà agrégé par intersection (une ligne = une intersection
    avec son nb_traversees final, ex: résultat de identification_PP.main()).
    Les intersections de df_cible peuvent avoir été re-filtrées/fusionnées
    depuis le calcul de df_pp, donc les coordonnées ne coïncident plus
    exactement — d'où une recherche du plus proche voisin plutôt qu'une
    jointure exacte.
    """
    from scipy.spatial import cKDTree

    df_cible = df_cible.copy()
    if df_pp.empty:
        df_cible["nb_traversees"] = 0
        return df_cible

    lat0 = df_cible["latitude"].mean()
    m_par_deg_lat = 111_320
    m_par_deg_lon = 111_320 * cos(radians(lat0))

    xy_cible = np.column_stack([
        df_cible["longitude"].to_numpy() * m_par_deg_lon,
        df_cible["latitude"].to_numpy() * m_par_deg_lat,
    ])
    xy_pp = np.column_stack([
        df_pp["longitude"].to_numpy() * m_par_deg_lon,
        df_pp["latitude"].to_numpy() * m_par_deg_lat,
    ])

    arbre = cKDTree(xy_pp)
    distances, indices = arbre.query(xy_cible, k=1)

    nb_traversees_pp = df_pp["nb_traversees"].to_numpy()[indices]
    df_cible["nb_traversees"] = np.where(distances <= rayon_m, nb_traversees_pp, 0)
    return df_cible


def _telecharger_passages_zone_filtree(df_inter, rayon_metres: float = 25, marge_m: float = 200):
    """
    Équivalent de identification_PP.telecharger_passages_par_zone, mais scopé à
    une bounding box autour des intersections déjà filtrées (Étape 2/3) plutôt
    qu'à toute la commune (area(id_zone)) — utilisé uniquement par la méthode
    Mixte, pour éviter d'interroger Overpass sur toute la ville (293+
    intersections pour Montrouge par ex.) alors que seule une poignée
    d'intersections filtrées par le rayon POI nous intéresse. Ça réduit
    fortement le risque de timeout Overpass (504/read timeout) constaté sur
    les grandes communes.

    Ne re-télécharge pas les intersections (on a déjà df_inter, issu de
    l'Étape 1/2/3) — seuls les passages piétons sont interrogés, puis
    rattachés par plus-proche-voisin aux intersections de df_inter. Produit
    le même schéma de colonnes que telecharger_passages_par_zone
    (intersection/latitude/longitude/nb_passages_pietons/latitude_ppN/
    longitude_ppN) pour rester compatible avec identification_PP.trie_intersections.
    """
    import math
    import pandas as pd
    from scipy.spatial import cKDTree
    from src.identification_PP import envoyer_requete_overpass, CATEGORIES_PASSAGES_PIETONS

    lat_moy = df_inter["latitude"].mean()
    marge_deg_lat = marge_m / 111_000
    marge_deg_lon = marge_m / (111_000 * math.cos(math.radians(lat_moy)))

    sud   = df_inter["latitude"].min() - marge_deg_lat
    nord  = df_inter["latitude"].max() + marge_deg_lat
    ouest = df_inter["longitude"].min() - marge_deg_lon
    est   = df_inter["longitude"].max() + marge_deg_lon

    filtre_osm = CATEGORIES_PASSAGES_PIETONS[0]["osm_filters"]
    headers = {
        "User-Agent": "ProjetSecuriteRoutiere_AnalyseIntersections/1.0 (contact: ton_email@exemple.com)",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    requete_passages = f"""
    [out:json][timeout:60][bbox:{sud},{ouest},{nord},{est}];
    (node{filtre_osm};way{filtre_osm};)->.passages_pietons;
    .passages_pietons out body center;
    """

    print(f" Récupération des passages piétons (zone filtrée, {len(df_inter)} intersections)...")
    donnees = envoyer_requete_overpass(requete_passages, headers)

    intersections_brutes = df_inter[["intersection", "latitude", "longitude"]].copy()
    intersections_brutes["nb_passages_pietons"] = 0
    intersections_brutes = intersections_brutes.to_dict("records")

    passages_pietons_extraits = []
    if donnees:
        for el in donnees.get("elements", []):
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")
            if lat and lon:
                passages_pietons_extraits.append({"lat": lat, "lon": lon})

    print(f" {len(passages_pietons_extraits)} passages piétons trouvés (zone filtrée).")

    if passages_pietons_extraits:
        coords_intersections = np.array([
            [math.radians(i["latitude"]), math.radians(i["longitude"])]
            for i in intersections_brutes
        ])
        arbre = cKDTree(coords_intersections)
        rayon_radians = rayon_metres / 6371000

        for passage in passages_pietons_extraits:
            point = [math.radians(passage["lat"]), math.radians(passage["lon"])]
            distance, index = arbre.query(point, k=1, distance_upper_bound=rayon_radians)
            if index < len(intersections_brutes):
                intersections_brutes[index]["nb_passages_pietons"] += 1
                valeur = intersections_brutes[index]["nb_passages_pietons"]
                intersections_brutes[index][f"latitude_pp{valeur}"] = passage["lat"]
                intersections_brutes[index][f"longitude_pp{valeur}"] = passage["lon"]

    return pd.DataFrame(intersections_brutes)


def _osm_accidents_scope_locale(ville: str, df_inter, base_dir, rayon_metres: float = 25):
    """
    Équivalent de identification_PP.main, mais où la partie OSM est scopée aux
    intersections filtrées (_telecharger_passages_zone_filtree) plutôt qu'à
    toute la commune. La partie accidents (déjà scopée par intersection via
    comparer_coordonnees) et la logique de fusion (trie_intersections) sont
    réutilisées telles quelles depuis identification_PP.
    """
    from pathlib import Path as _Path
    from src.identification_PP import charger_accidents, comparer_coordonnees, trie_intersections

    base_dir = _Path(base_dir) if base_dir is not None else _Path(".")
    path_accidents = str(
        base_dir / "data" / "raw" / "source_pp"
        / "accidents-corporels-de-la-circulation-routiere fichier entier.csv"
    )

    print(f"--- Démarrage du traitement Mixte (OSM scopé) pour la commune : {ville} ---")

    final_accident = None
    try:
        tableau_accident = charger_accidents(path_accidents, ville)
        final_accident = comparer_coordonnees(tableau_accident, df_inter)
    except FileNotFoundError:
        print(f" Fichier des accidents introuvable ({path_accidents}) — étape ignorée.")
    except Exception as e:
        print(f" Erreur lors du traitement des accidents : {e} — étape ignorée.")

    df_resultat = _telecharger_passages_zone_filtree(df_inter, rayon_metres=rayon_metres)

    if (final_accident is None or final_accident.empty) and df_resultat.empty:
        print(" Aucune des deux méthodes n'a produit de résultat exploitable.")
        return None
    if final_accident is None or final_accident.empty:
        return df_resultat.rename(columns={"nb_passages_pietons": "nb_traversees"})[
            ["latitude", "longitude", "intersection", "nb_traversees"]
        ]
    if df_resultat.empty:
        return final_accident[["latitude", "longitude", "intersection", "nb_traversees"]]
    return trie_intersections(final_accident, df_resultat)


def _rmtree_force(path):
    # Sur Windows/OneDrive, certains fichiers sont en lecture seule → on force les permissions avant suppression
    # Si un fichier est verrouillé (ouvert dans Excel), on l'ignore avec un avertissement
    import shutil
    import os
    def _on_error(func, p, _):
        try:
            os.chmod(p, 0o777)
            func(p)
        except PermissionError:
            st.warning(f"Impossible de supprimer '{Path(p).name}' (fichier ouvert).")
    shutil.rmtree(path, onerror=_on_error)


def nettoyer_anciennes_villes_gui(base_dir: Path, garder: int = 2):
    """
    Supprime les données (images_pp + fiches_equipes) des villes les plus
    anciennes quand le nombre de villes distinctes dépasse `garder`.
    Le suivi des villes se fait via les dossiers fiches_equipes,
    nommés "{ville}_{horodatage}" par export_final_equipes().
    """
    dossier_images = base_dir / "data" / "raw" / "images_pp"
    dossier_fiches = base_dir / "data" / "output" / "fiches_equipes"

    if not dossier_fiches.exists():
        return

    par_ville = {}
    for dossier in dossier_fiches.iterdir():
        if not dossier.is_dir():
            continue
        ville_brute = dossier.name.rsplit("_", 2)[0]
        ville_norm = _normaliser_ville(ville_brute)
        mtime = dossier.stat().st_mtime
        if ville_norm not in par_ville or mtime > par_ville[ville_norm][1]:
            par_ville[ville_norm] = (ville_brute, mtime)

    villes_par_anciennete = sorted(par_ville.items(), key=lambda kv: kv[1][1])

    while len(villes_par_anciennete) > garder:
        ville_norm, (ville_brute, _) = villes_par_anciennete.pop(0)

        prefix_fiches = ville_norm + " "
        for dossier in dossier_fiches.iterdir():
            if dossier.is_dir() and _normaliser_ville(dossier.name).startswith(prefix_fiches):
                _rmtree_force(dossier)

        if dossier_images.exists():
            prefix_images = "images " + ville_norm + " "
            for dossier in dossier_images.iterdir():
                if dossier.is_dir() and _normaliser_ville(dossier.name).startswith(prefix_images):
                    _rmtree_force(dossier)


# ─────────────────────────────────────────────
# 2. Navigation par pages
# ─────────────────────────────────────────────
PAGES = ["presentation", "etape1", "etape2", "etape3", "etape4"]
LABELS_PAGES = {
    "presentation": "🏠 Présentation",
    "etape1":       "Étape 1 — 🗂️ Intersections",
    "etape2":       "Étape 2 — 📍 Lieux d'intérêt",
    "etape3":       "Étape 3 — 🚶 Passages piétons",
    "etape4":       "Étape 4 — 📄 Fiches équipes",
}
ORDRE_SUIVANT = {
    "presentation": "etape1",
    "etape1": "etape2",
    "etape2": "etape3",
    "etape3": "etape4",
    "etape4": None,
}
ORDRE_PRECEDENT = {
    "presentation": None,
    "etape1": "presentation",
    "etape2": "etape1",
    "etape3": "etape2",
    "etape4": "etape3",
}

if "page_actuelle" not in st.session_state:
    st.session_state["page_actuelle"] = "presentation"


def aller_a(page: str):
    st.session_state["page_actuelle"] = page
    st.rerun()


with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3448/3448614.png", width=60)
    st.title("DEFIACCESS")
    st.caption("Générateur de feuilles terrain accessibilité")
    st.divider()

    for cle in PAGES:
        est_actuelle = st.session_state["page_actuelle"] == cle
        if st.button(
            LABELS_PAGES[cle],
            key=f"nav_{cle}",
            use_container_width=True,
            type="primary" if est_actuelle else "secondary",
        ):
            aller_a(cle)

    st.divider()
    st.caption("v0.1 (app6) — DEFIACCESS © 2025")


# ─────────────────────────────────────────────
# 3. Pied de page commun : navigation Précédent / Suivant
# ─────────────────────────────────────────────
def pied_de_page_navigation(page_actuelle: str, suivant_desactive: bool = False):
    st.divider()
    col_prec, col_spacer, col_suiv = st.columns([1, 3, 1])

    page_prec = ORDRE_PRECEDENT[page_actuelle]
    page_suiv = ORDRE_SUIVANT[page_actuelle]

    with col_prec:
        if page_prec is not None:
            if st.button("⬅️ Précédent", use_container_width=True, key=f"btn_prec_{page_actuelle}"):
                aller_a(page_prec)

    with col_suiv:
        if page_suiv is not None:
            if st.button(
                "Suivant ➡️",
                use_container_width=True,
                type="primary",
                disabled=suivant_desactive,
                key=f"btn_suiv_{page_actuelle}",
            ):
                aller_a(page_suiv)


# ─────────────────────────────────────────────
# 4. Page — Présentation
# ─────────────────────────────────────────────
def page_presentation():
    st.title("|DF| DEFIACCESS — Générateur de feuilles terrain accessibilité")
    st.markdown(
        """
Cette application prépare automatiquement les tournées terrain d'évaluation de
l'accessibilité PMR d'une commune. Renseignez la commune dans la barre latérale,
puis suivez les 4 étapes :

1. **Intersections** — téléchargement automatique des croisements de rues de la commune, avec filtre par types de voies.
2. **Lieux d'intérêt (PM)** — recherche des écoles, de la mairie, des établissements de santé, commerces, etc. via les sources officielles et OpenStreetMap.
3. **Passages piétons** — détection des passages piétons proches des intersections (OpenStreetMap, accidents corporels ou IA).
4. **Fiches équipes** — filtrage des intersections autour des lieux d'intérêt, répartition en équipes, calcul des itinéraires et export des feuilles terrain Excel prêtes à imprimer.

Utilisez les boutons de la barre latérale pour naviguer directement à une étape,
ou le bouton **Suivant ➡️** ci-dessous pour commencer.
        """
    )
    pied_de_page_navigation("presentation")


# ─────────────────────────────────────────────
# 5. Page — Étape 1 : Intersections (reprise du bloc de app5.py)
# ─────────────────────────────────────────────
def page_etape1():
    st.header("Étape 1 — 🗂️ Intersections")

    # --- Commune ---
    commune_names = list(yaml_configs.keys())
    commune_choice = st.selectbox(
        "Commune pré-configurée",
        options=["— Saisie manuelle —"] + commune_names,
        help="Sélectionnez une commune pré-configurée ou saisissez les paramètres manuellement.",
    )
    if commune_choice != "— Saisie manuelle —":
        cfg = yaml_configs[commune_choice]
    else:
        cfg = {}
    st.session_state["cfg_commune"] = cfg

    # Remplacement de l'ancien st.text_input pour la commune
    commune_selectionnee = st_searchbox(
        search_function=chercher_communes_api,
        placeholder="Tapez le nom de la commune (ex: Garches)...",
        label="Nom de la commune",
        key="input_commune_searchbox",
        default=st.session_state.get("commune_complete_obj", None) 
    )

    if commune_selectionnee:
        commune_str = commune_selectionnee["nom"]
        
        # Sauvegarde des données dans le session state
        st.session_state["commune_val"] = commune_str
        st.session_state["commune_complete_obj"] = commune_selectionnee
        st.session_state["code_insee_val"] = commune_selectionnee["code_insee"]
        st.session_state["code_dept_val"] = commune_selectionnee["code_dept"]
    else:
        commune_str = ""







    # Mémorisation dans une clé "normale" (non liée au widget) : la valeur d'un
    # widget disparaît de session_state dès qu'il n'est plus affiché (ex: en
    # naviguant vers une autre page) — cette copie, elle, survit au changement de page.
    st.session_state["commune_val"] = commune_str

    st.markdown("**Objectif :** récupérer les intersections de la commune — automatique, rien à faire.")

    if not commune_str.strip():
        st.info("Saisissez d'abord le nom de la commune ci-dessus.")
    else:
        ville_inter = commune_str.split(",")[0].strip()

        # ── Choix explicite du mode de récupération ───────────────────────────────────────
        # demandé à l'utilisateur AVANT toute action, plutôt que de lancer le
        # téléchargement automatique par défaut avec une option avancée
        # cachée dans un expander (ancien comportement)
        _modes_inter = ["Téléchargement automatique", "Importer mon propre fichier (avancé)"]
        _mode_inter_persiste = st.session_state.get("mode_intersections_val", _modes_inter[0])
        mode_intersections = st.radio(
            "Comment récupérer les intersections ?",
            options=_modes_inter,
            index=_modes_inter.index(_mode_inter_persiste),
            horizontal=True,
            key="input_mode_intersections",
        )
        if mode_intersections != st.session_state.get("mode_intersections_val"):
            # changement de mode : on efface l'état de la source précédente
            # (fichier importé ou chemin auto-téléchargé) pour ne pas mélanger
            # les deux — le mode nouvellement choisi repart de zéro
            for _cle in ("inter_geojson_path", "inter_df_preview", "is_fichier_perso", "last_uploaded_name"):
                st.session_state.pop(_cle, None)
        st.session_state["mode_intersections_val"] = mode_intersections

        if mode_intersections == "Importer mon propre fichier (avancé)":
            fichier_perso = st.file_uploader(
                "Votre fichier d'intersections (.xlsx, .csv ou .geojson)",
                type=["xlsx", "csv", "geojson"],
                key="uploader_intersections_manuel",
            )
            if fichier_perso is not None:
                # 1. On mémorise de manière persistante (ne dépend plus du widget)
                st.session_state["is_fichier_perso"] = True
                st.session_state["last_uploaded_name"] = fichier_perso.name

                # 2. Sécurité : Streamlit purge le fichier uploadé dès que son widget
                # n'est plus actif dans le run courant (donc dès qu'on quitte cette page) —
                # on copie le contenu dans un BytesIO indépendant pour que la lecture
                # reste possible depuis l'Étape 3, sinon la génération des PP plante
                # (page blanche) en tentant de relire un flux déjà purgé.
                _buffer_inter_perso = io.BytesIO(fichier_perso.getvalue())
                _buffer_inter_perso.name = fichier_perso.name
                st.session_state["inter_geojson_path"] = _buffer_inter_perso

            # MODIFICATION ICI : On ne nettoie QUE si l'utilisateur a désemparé le fichier
            # ALORS QU'IL EST ENCORE sur la page (le widget est visible à l'écran, donc sa clé existe)
            elif "uploader_intersections_manuel" in st.session_state and st.session_state["uploader_intersections_manuel"] is None:
                if st.session_state.get("is_fichier_perso"):
                    st.session_state.pop("inter_geojson_path", None)
                    st.session_state.pop("inter_df_preview", None)
                    st.session_state.pop("is_fichier_perso", None)
                    st.session_state.pop("last_uploaded_name", None)
                    st.rerun()

        # ── Mode automatique ───────────────────────────────────────────────────────────────
        if mode_intersections == "Téléchargement automatique":
            geojson_existant = trouver_geojson_existant(ville_inter)

            if geojson_existant is not None:
                st.session_state["inter_geojson_path"] = str(geojson_existant)

                col_info, col_reload = st.columns([4, 1])
                with col_info:
                    st.success(f"✅ Intersections de **{ville_inter}** déjà chargées.")
                with col_reload:
                    if st.button("🔄 Recharger", key="btn_recharger_inter", use_container_width=True):
                        try:
                            chemin_supprime = str(geojson_existant)
                            geojson_existant.unlink()
                            import json
                            index_path = INTERSECTIONS_DIR / "index.json"
                            if index_path.exists():
                                with open(index_path) as f:
                                    index = json.load(f)
                                index = {v: c for v, c in index.items() if c != chemin_supprime}
                                with open(index_path, "w") as f:
                                    json.dump(index, f, ensure_ascii=False, indent=2)
                        except Exception:
                            pass
                        for k in ("inter_geojson_path", "inter_df_preview",
                                  "intersections_auto_ville", "intersections_auto_echec"):
                            st.session_state.pop(k, None)
                        st.rerun()

            elif (
                st.session_state.get("intersections_auto_ville") == ville_inter
                and st.session_state.get("intersections_auto_echec")
            ):
                st.error(f"Intersections introuvables pour '{ville_inter}'. Vérifiez l'orthographe de la commune.")
                if st.button("Réessayer", key="btn_retry_inter"):
                    st.session_state.pop("intersections_auto_echec", None)
                    st.session_state.pop("intersections_auto_ville", None)
                    st.rerun()

            elif st.session_state.get("intersections_auto_ville") != ville_inter:
                # attend un clic explicite plutôt que de lancer le
                # téléchargement dès l'affichage de la page
                st.info(f"Aucune intersection en cache pour **{ville_inter}**.")
                _telecharger_inter_btn = st.button(
                    "📥 Télécharger les intersections", key="btn_telecharger_inter",
                    type="primary", use_container_width=True,
                )
                if _telecharger_inter_btn:
                    from src.telecharger_intersections import telecharger_intersections_ville
                    zone_logs_inter = st.empty()

                    class InterLogger(io.StringIO):
                        def write(self, texte):
                            super().write(texte)
                            lignes = self.getvalue().splitlines()
                            zone_logs_inter.code("\n".join(lignes[-20:]) or "…", language="text")
                            return len(texte)

                    logs_inter = InterLogger()
                    with st.spinner(f"Récupération des intersections de **{ville_inter}**…"):
                        with contextlib.redirect_stdout(logs_inter):
                            # 1. On récupère les codes enregistrés par la searchbox
                            code_dept = st.session_state.get("code_dept_val")
                            code_insee = st.session_state.get("code_insee_val")

                            # 2. On prépare la variable de résolution
                            # Si l'utilisateur a bien sélectionné une commune, on crée le tuple attendu
                            if code_dept and code_insee:
                                preresolus = [(code_dept, ville_inter, code_insee)]
                            else:
                                preresolus = None # Sécurité / Fallback au cas où

                            # 3. On passe la liste à la fonction
                            fichiers = telecharger_intersections_ville(
                                ville_inter,
                                departements_preresolus=preresolus
                            )

                    st.session_state["intersections_auto_ville"] = ville_inter
                    if fichiers:
                        sauvegarder_index(ville_inter, Path(fichiers[0]))
                        st.session_state["inter_geojson_path"] = fichiers[0]
                        st.session_state.pop("inter_df_preview", None)
                        st.session_state.pop("intersections_auto_echec", None)
                        st.rerun()
                    else:
                        st.session_state["intersections_auto_echec"] = True
                        st.rerun()
        elif st.session_state.get("is_fichier_perso"):
            _nom_perso = getattr(st.session_state.get("inter_geojson_path"), "name", "")
            st.success(f"✅ Fichier personnalisé utilisé : `{_nom_perso}`")

        # ── Filtre par combinaisons de types de voies (commun aux 3 modes) ───────────────
        if st.session_state.get("inter_geojson_path"):
            st.divider()
            st.markdown("**Filtrer par combinaisons de types de voies**")
            st.caption(
                "Cochez les combinaisons de voies à conserver (ex: Rue / Avenue). "
                "Aucune case cochée = toutes les intersections sont conservées."
            )

            col_sel_all, col_desel_all, _col_spacer = st.columns([1, 1, 3])
            with col_sel_all:
                if st.button("Tout sélectionner", key="combos_select_all"):
                    for _a, _b in COMBINAISONS_VOIES:
                        st.session_state[f"chk_combo_{_a}_{_b}"] = True
                        st.session_state[f"sticky_chk_combo_{_a}_{_b}"] = True
                    st.session_state.pop("inter_df_preview", None)
                    st.rerun()
            with col_desel_all:
                if st.button("Tout désélectionner", key="combos_desel_all"):
                    for _a, _b in COMBINAISONS_VOIES:
                        st.session_state[f"chk_combo_{_a}_{_b}"] = False
                        st.session_state[f"sticky_chk_combo_{_a}_{_b}"] = False
                    st.session_state.pop("inter_df_preview", None)
                    st.rerun()

            import math
            cols_combo = st.columns(3)
            taille_bloc = math.ceil(len(COMBINAISONS_VOIES) / 3)
            combos_selectionnes = []
            for i, (type_a, type_b) in enumerate(COMBINAISONS_VOIES):
                with cols_combo[i // taille_bloc]:
                    # Mémoire "sticky" : survit à la navigation entre étapes,
                    # contrairement à la clé du widget elle-même.
                    _sticky_combo_key = f"sticky_chk_combo_{type_a}_{type_b}"
                    _valeur_defaut_combo = st.session_state.get(_sticky_combo_key, False)
                    _coche_combo = st.checkbox(
                        f"{type_a} / {type_b}",
                        value=_valeur_defaut_combo,
                        key=f"chk_combo_{type_a}_{type_b}",
                    )
                    st.session_state[_sticky_combo_key] = _coche_combo
                    if _coche_combo:
                        combos_selectionnes.append((type_a, type_b))
            st.session_state["combos_selectionnes"] = combos_selectionnes

            _signature_combos = tuple(sorted(combos_selectionnes))
            if st.session_state.get("combos_signature_preview") != _signature_combos:
                st.session_state.pop("inter_df_preview", None)
                st.session_state["combos_signature_preview"] = _signature_combos

            # ── Aperçu ───────────────────────────────────────────────────────────────────
            _source_fichier = st.session_state["inter_geojson_path"]

            if "inter_df_preview" not in st.session_state:
                try:
                    st.session_state["inter_df_preview"] = charger_intersections_quelconque(
                        _source_fichier, combos_selectionnes
                    )
                except Exception as e:
                    st.warning(f"Aperçu impossible : {e}")

            if "inter_df_preview" in st.session_state:
                _df_prev = st.session_state["inter_df_preview"]
                st.caption(
                    "Aperçu des croisements de rues trouvés — ex. \"Rue Victor Hugo / "
                    "Avenue de la République\" — utilisés ensuite pour générer les feuilles terrain."
                )
                with st.expander(f"📋 Voir le tableau ({len(_df_prev):,} intersections)", expanded=False):
                    st.dataframe(_df_prev.head(20), use_container_width=True)
                    st.caption(f"{len(_df_prev):,} intersections chargées")
                st.download_button(
                    label="📥 Télécharger intersections.csv",
                    data=_df_prev.to_csv(index=False).encode("utf-8"),
                    file_name=f"intersections_{ville_inter.lower().replace(' ', '_')}.csv",
                    mime="text/csv",
                    key="dl_intersections_csv",
                    use_container_width=True,
                )

    pied_de_page_navigation("etape1")


# ─────────────────────────────────────────────
# 6. Page — Étape 2 : Lieux d'intérêt / PM (reprise du bloc de app5.py)
# ─────────────────────────────────────────────
def page_etape2():
    st.header("Étape 2 — 📍 Générer le fichier des lieux Importants (PM, sous format xlsx)")

    commune_str = st.session_state.get("commune_val", "")
    cfg = st.session_state.get("cfg_commune", {})

    st.markdown(
        "**Objectif :** récupérer automatiquement les points d'intérêt de la commune "
        "(écoles, mairie, supermarchés, pharmacies…) depuis les sources "
        "officielles et OpenStreetMap."
    )

    radius_km = st.slider(
        "Veuillez choisir le rayon autour des PM (km)",
        min_value=0.05, max_value=1.0,
        value=st.session_state.get("radius_km_val", float(cfg.get("radius_km", 0.2))), step=0.05,
        help="Seules les intersections dans ce rayon autour d'un point d'intérêt sont conservées.",
        key="input_radius_km",
    )
    # Copie dans une clé "normale" pour survivre au changement de page (cf. Étape 1).
    st.session_state["radius_km_val"] = radius_km

    if not commune_str.strip():
        st.info("Saisissez d'abord le nom de la commune dans l'Étape 1.")

    else:
        ville_cible = commune_str.split(",")[0].strip()
        st.write(f"Commune ciblée : **{ville_cible}**")

        # ── Option avancée, repliée : importer son propre fichier de lieux ───────────
        with st.expander("⚙️ Utiliser un fichier personnalisé (avancé)", expanded=False):
            fichier_perso_pm = st.file_uploader(
                "Votre fichier de lieux (.xlsx)",
                type=["xlsx"],
                key="uploader_pm_manuel",
                help="Remplace la génération automatique ci-dessous — utilisé tel quel pour cette commune.",
            )
            if fichier_perso_pm is not None:
                if st.session_state.get("pm_perso_last_uploaded_name") != fichier_perso_pm.name:
                    import pandas as pd
                    _df_pm_perso = pd.read_excel(fichier_perso_pm)
                    st.session_state["df_pm"] = _df_pm_perso
                    st.session_state["pm_commune"] = ville_cible
                    # None = signature non suivie : le nettoyage par changement de
                    # filtres (plus bas) ne doit jamais effacer un fichier importé.
                    st.session_state["pm_filters_signature"] = None
                    st.session_state["is_fichier_perso_pm"] = True
                    st.session_state["pm_perso_last_uploaded_name"] = fichier_perso_pm.name
                    _buf_pm_perso = io.BytesIO()
                    _df_pm_perso.to_excel(_buf_pm_perso, index=False)
                    _buf_pm_perso.seek(0)
                    st.session_state["pm_buffer"] = _buf_pm_perso.getvalue()
                    st.rerun()
           
            # MODIFICATION ICI : On vérifie si le widget est présent à l'écran et vidé
            elif "uploader_pm_manuel" in st.session_state and st.session_state["uploader_pm_manuel"] is None:
                if st.session_state.get("is_fichier_perso_pm"):
                    for cle in ("pm_buffer", "pm_commune", "pm_filters_signature",
                                "is_fichier_perso_pm", "pm_perso_last_uploaded_name", "df_pm"):
                        st.session_state.pop(cle, None)
                    st.rerun()

        if (
            st.session_state.get("is_fichier_perso_pm")
            and st.session_state.get("pm_commune") == ville_cible
        ):
            st.success(f"📁 Fichier personnalisé de lieux utilisé pour **{ville_cible}**.")

        st.write("📋 **Sélectionnez les types de lieux à récupérer :**")
        st.caption(
            "La mairie est toujours incluse. Laissez tout coché pour ne rien filtrer. "
            "Ces choix sont pris en compte au clic sur « 🏗️ Générer les PM » ci-dessous."
        )

        categories_sante_choisies  = bloc_filtre_theme("🏥 Lieux de santé", "sante", LABELS_SANTE)
        st.write("---")
        categories_ecoles_choisies = bloc_filtre_theme("🏫 Établissements scolaires", "ecoles", LABELS_ECOLES)
        st.write("---")
        categories_osm_labels_choisies = bloc_filtre_theme(
            "📍 Autres lieux", "osm", LABELS_OSM, labels_preselectionnes=LABELS_OSM_PRESELECTIONNES
        )
        categories_osm_choisies = [
            {"type": c["type"], "osm_filters": c["osm_filters"]}
            for c in CATEGORIES_OSM_DISPONIBLES
            if c["label"] in categories_osm_labels_choisies
        ]

        _signature_actuelle = signature_filtres_pm(
            categories_sante_choisies, categories_ecoles_choisies, categories_osm_labels_choisies
        )
        if (
            st.session_state.get("pm_commune") == ville_cible
            and st.session_state.get("pm_filters_signature") is not None
            and st.session_state.get("pm_filters_signature") != _signature_actuelle
        ):
            for cle in ("df_pm", "pm_buffer", "pm_commune", "pm_filters_signature"):
                st.session_state.pop(cle, None)
            st.info(
                "⚠️ Filtres modifiés depuis la dernière génération des lieux — ils seront "
                "régénérés au prochain clic sur « 🏗️ Générer les PM » ou "
                "« ⚡ Générer les feuilles terrain »."
            )

        st.session_state["pm_categories_sante_choisies"] = categories_sante_choisies
        st.session_state["pm_categories_ecoles_choisies"] = categories_ecoles_choisies
        st.session_state["pm_categories_osm_labels_choisies"] = categories_osm_labels_choisies
        st.session_state["pm_categories_osm_choisies"] = categories_osm_choisies

        st.write("---")

        generer_pm_local_btn = st.button(
            "🏗️ Générer les PM",
            key="btn_generer_pm_local",
            type="secondary",
            use_container_width=True,
        )
        st.caption(
            "💡 Génération un peu longue ? Vous pouvez l'interrompre à tout moment via le "
            "bouton ⏹️ Stop en haut à droite de la page pendant le chargement."
        )

        if generer_pm_local_btn:
            _categories_sante = None if set(categories_sante_choisies) == set(LABELS_SANTE) else categories_sante_choisies
            _categories_ecoles = None if set(categories_ecoles_choisies) == set(LABELS_ECOLES) else categories_ecoles_choisies
            _categories_osm = None if set(categories_osm_labels_choisies) == set(LABELS_OSM) else categories_osm_choisies

            st.markdown("**Progression :**")
            zone_logs_pm_local = st.empty()

            class StreamlitLoggerPMLocal(io.StringIO):
                def write(self, texte):
                    super().write(texte)
                    lignes = self.getvalue().splitlines()
                    zone_logs_pm_local.code("\n".join(lignes[-25:]) or "…", language="text")
                    return len(texte)

            logs_pm_local = StreamlitLoggerPMLocal()

            with st.spinner(f"Récupération des lieux pour **{ville_cible}**… (1-2 min)"):
                with contextlib.redirect_stdout(logs_pm_local):
                    df_pm_local = construire_dataframe_PM_sans_input_avec_filtres(
                        ville_cible,
                        categories_osm=_categories_osm,
                        categories_sante=_categories_sante,
                        categories_ecoles=_categories_ecoles,
                    )

            if df_pm_local.empty:
                st.error(f"Aucun lieu d'intérêt trouvé pour '{ville_cible}' avec les filtres sélectionnés.")
                st.toast(f"Aucun lieu trouvé pour {ville_cible}.", icon="⚠️", duration="long")
            else:
                st.session_state["df_pm"] = df_pm_local
                st.session_state["pm_commune"] = ville_cible
                st.session_state["pm_filters_signature"] = _signature_actuelle
                st.session_state.pop("is_fichier_perso_pm", None)
                st.session_state.pop("pm_perso_last_uploaded_name", None)
                _buf_pm_local = io.BytesIO()
                df_pm_local.to_excel(_buf_pm_local, index=False)
                _buf_pm_local.seek(0)
                st.session_state["pm_buffer"] = _buf_pm_local.getvalue()
                st.toast(f"{len(df_pm_local)} lieux trouvés pour {ville_cible}.", icon="✅", duration="long")
                st.rerun()

    if "df_pm" in st.session_state and st.session_state.get("pm_commune") == commune_str.split(",")[0].strip():
        df_pm_disp = st.session_state["df_pm"]

        if not df_pm_disp.empty:
            st.success(f"**{len(df_pm_disp)} lieux** trouvés pour {st.session_state.get('pm_commune')}.")
            st.caption(
                "Aperçu des lieux d'intérêt (PM) trouvés — ex. \"École Jean Moulin\" "
                "(type : école, source : data.education.gouv.fr) — utilisés ensuite pour ne "
                "garder que les intersections situées à proximité d'un de ces lieux."
            )
            with st.expander(f"📋 Voir le tableau ({len(df_pm_disp):,} lieux)", expanded=False):
                st.dataframe(df_pm_disp.head(30), use_container_width=True)

            if "pm_buffer" in st.session_state:
                st.download_button(
                    label="📥 Télécharger lieux.xlsx (Copie de sauvegarde)",
                    data=st.session_state["pm_buffer"],
                    file_name=f"lieux_{st.session_state.get('pm_commune').lower().replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

    pied_de_page_navigation("etape2")


# ─────────────────────────────────────────────
# 7. Page — Étape 3 : Passages piétons (reprise du bloc de app5.py)
# ─────────────────────────────────────────────
def page_etape3():
    st.header("Étape 3 — 🚶 Générer les passages piétons")

    commune_str = st.session_state.get("commune_val", "")
    radius_km = st.session_state.get("radius_km_val", 0.2)

    st.markdown(
        "**Objectif :** identifier les passages piétons autour des intersections selon la méthode choisie."
    )

    if not commune_str.strip():
        st.info("Saisissez d'abord le nom de la commune dans l'Étape 1.")

    _options_pp = [
        "OSM + Accidents", "IA (YOLO — best.pt requis)",
        "Mixte (IA + OSM/Accidents)",
    ]
    _methode_pp_persistee = st.session_state.get("methode_pp_val", _options_pp[0])
    if _methode_pp_persistee not in _options_pp:
        _methode_pp_persistee = _options_pp[0]
    methode_pp = st.radio(
        "Méthode de détection",
        options=_options_pp,
        index=_options_pp.index(_methode_pp_persistee),
        horizontal=True,
        key="input_methode_pp",
        help=(
            "OSM + Accidents combine les passages piétons répertoriés sur OpenStreetMap "
            "(Overpass) et les accidents corporels impliquant un passage piéton (fichier "
            "national local, aucun upload requis)."
        ),
    )
    st.session_state["methode_pp_val"] = methode_pp

    conf_min_mixte = 0.27
    rayon_filtre_mixte = 25
    if methode_pp in ("IA (YOLO — best.pt requis)", "Mixte (IA + OSM/Accidents)"):
        import os
        if os.path.exists(os.path.join("models", "best.pt")):
            st.success("✅ Modèle `models/best.pt` détecté.")
        else:
            st.error("❌ `models/best.pt` introuvable — placez votre modèle dans `models/`.")

        if methode_pp == "Mixte (IA + OSM/Accidents)":
            col_conf_mixte, col_rayon_mixte = st.columns(2)
            with col_conf_mixte:
                conf_min_mixte = st.number_input(
                    "Seuil de confiance IA minimal par détection",
                    min_value=0.0, max_value=1.0, value=0.27, step=0.01,
                    key="input_conf_min_mixte",
                    help=(
                        "En dessous de ce seuil, une détection IA est ignorée avant d'être "
                        "comparée à OSM+Accidents. Sert à compenser la tendance de l'IA à "
                        "surestimer le nombre de passages piétons."
                    ),
                )
            with col_rayon_mixte:
                rayon_filtre_mixte = st.number_input(
                    "Filtre géométrique IA (rayon en mètres)",
                    min_value=1, max_value=80, value=25, step=1,
                    key="input_rayon_filtre_mixte",
                    help=(
                        "Distance maximale (en mètres) entre un passage piéton détecté par "
                        "l'IA et l'intersection ciblée pour être retenu. Sert à ignorer les "
                        "passages piétons d'une intersection voisine visible dans le même "
                        "cadrage."
                    ),
                )
                st.image(
                    _image_rayon_exemple(rayon_filtre_mixte),
                    caption=f"Exemple : rayon de {rayon_filtre_mixte} m",
                    width=180,
                )

    col_pp_gen, col_pp_reset = st.columns([3, 1])
    with col_pp_gen:
        generer_pp_btn = st.button(
            "Générer les PP",
            key="btn_generer_pp",
            type="secondary",
            use_container_width=True,
            disabled=not commune_str.strip() or st.session_state.get("pp_generation_en_cours", False),
        )
    with col_pp_reset:
        reset_pp_btn = st.button("Réinitialiser", key="btn_reset_pp", use_container_width=True)

    if reset_pp_btn:
        for cle in ("df_pp", "pp_methode", "pp_commune", "pp_ia_dossier", "pp_generation_en_cours"):
            st.session_state.pop(cle, None)
        st.rerun()

    if generer_pp_btn and commune_str.strip():
        # On ne lance pas l'analyse dans CE run : on marque juste l'intention et on
        # relance immédiatement. Ça force un rerun "propre" avant de commencer les
        # mises à jour de progression imbriquées (barre/log) — sinon, si ce clic
        # arrive pendant que Streamlit finit à peine d'afficher les champs
        # spécifiques à la méthode IA/Mixte (rerun précédent), les deux reruns
        # peuvent se chevaucher et faire planter l'appli (page blanche).
        st.session_state["pp_lancement_pending"] = True
        st.session_state["pp_generation_en_cours"] = True
        st.rerun()

    if st.session_state.pop("pp_lancement_pending", False) and commune_str.strip():
        ville_pp = commune_str.split(",")[0].strip()

        if methode_pp == "OSM + Accidents":
            _inter_source_osm = st.session_state.get("inter_geojson_path")
            _inter_prete_osm = bool(
                _inter_source_osm
                and (
                    not _intersections_source_est_chemin(_inter_source_osm)
                    or Path(_inter_source_osm).exists()
                )
            )
            if not _inter_prete_osm:
                st.error(
                    "Générez d'abord les intersections (Étape 1) avant de lancer "
                    "l'analyse OSM + Accidents."
                )
                st.toast("Intersections manquantes pour lancer l'analyse OSM + Accidents.", icon="⚠️", duration="long")
            else:
                from src.identification_PP import main as analyser_pp_osm_accidents

                _combos_osm = st.session_state.get("combos_selectionnes", [])
                df_inter_osm = charger_intersections_quelconque(_inter_source_osm, _combos_osm)

                st.markdown("**Progression :**")
                zone_logs_osm = st.empty()

                class StreamlitLoggerOSM(io.StringIO):
                    # redirige les print() de identification_PP.main (accidents,
                    # puis OSM, puis fusion) vers l'UI
                    def write(self, texte):
                        super().write(texte)
                        lignes = self.getvalue().splitlines()
                        zone_logs_osm.code("\n".join(lignes[-25:]) or "…", language="text")
                        return len(texte)

                logs_osm = StreamlitLoggerOSM()
                with st.spinner(f"Analyse OSM + Accidents pour **{ville_pp}**…"):
                    with contextlib.redirect_stdout(logs_osm):
                        df_pp = analyser_pp_osm_accidents(
                            ville_pp, df_inter_osm, base_dir=Path(__file__).parent,
                        )

                if df_pp is None or df_pp.empty:
                    st.warning(f"Aucun résultat OSM + Accidents pour '{ville_pp}'.")
                    st.toast(f"Aucun résultat OSM + Accidents pour '{ville_pp}'.", icon="⚠️", duration="long")
                else:
                    st.session_state["df_pp"]      = df_pp
                    st.session_state["pp_methode"] = "OSM"
                    st.session_state["pp_commune"] = ville_pp
                    st.toast(f"{len(df_pp)} intersections analysées via OSM + Accidents.", icon="✅", duration="long")

        elif methode_pp == "IA (YOLO — best.pt requis)":
            import os

            _inter_source_ia = st.session_state.get("inter_geojson_path")
            _inter_prete = bool(
                _inter_source_ia
                and (
                    not _intersections_source_est_chemin(_inter_source_ia)
                    or Path(_inter_source_ia).exists()
                )
            )
            _pm_prete = (
                "df_pm" in st.session_state
                and st.session_state.get("pm_commune") == ville_pp
            )

            if not os.path.exists(os.path.join("models", "best.pt")):
                st.error("Modèle introuvable.")
                st.toast("Modèle models/best.pt introuvable.", icon="❌", duration="long")
            elif not _inter_prete:
                st.error("Générez d'abord les intersections (Étape 1) avant de lancer la détection IA.")
                st.toast("Intersections manquantes pour lancer l'IA.", icon="⚠️", duration="long")
            elif not _pm_prete:
                st.error(
                    "Générez d'abord les lieux d'intérêt (Étape 2) pour cette commune avant de "
                    "lancer la détection IA."
                )
                st.toast("Lieux d'intérêt (PM) manquants pour lancer l'IA.", icon="⚠️", duration="long")
            else:
                from datetime import datetime

                with st.spinner(f"Préparation de l'analyse IA pour **{ville_pp}**…"):
                    _combos_ia = st.session_state.get("combos_selectionnes", [])
                    df_inter_ia = charger_intersections_quelconque(_inter_source_ia, _combos_ia)

                    pois_ia = st.session_state["df_pm"]

                    df_inter_ia = filtre_distance(pois_ia, df_inter_ia, rayon_km=radius_km)
                    df_inter_ia = fusion_croisement(df_inter_ia, threshold_km=0.03)

                if df_inter_ia.empty:
                    st.warning("Aucune intersection après filtrage géographique — IA non lancée.")
                    st.toast("Aucune intersection à analyser après filtrage.", icon="⚠️", duration="long")

                else:
                    from src.IA_PP import analyser_toutes_intersections

                    dossier_images_ia = str(
                        Path("data/raw/images_pp")
                        / f"images_{ville_pp}_{datetime.now().strftime('%d-%m-%Y_%Hh%M')}"
                    )

                    st.markdown("**Progression :**")
                    zone_logs_ia = st.empty()

                    class StreamlitLoggerIA(io.StringIO):
                        def write(self, texte):
                            super().write(texte)
                            lignes = self.getvalue().splitlines()
                            zone_logs_ia.code("\n".join(lignes[-25:]) or "…", language="text")
                            return len(texte)

                    logs_ia = StreamlitLoggerIA()
                    with st.spinner(f"Détection IA pour **{ville_pp}**…"):
                        with contextlib.redirect_stdout(logs_ia):
                            df_pp = analyser_toutes_intersections(
                                df_inter_ia, col_lat="latitude", col_lon="longitude",
                                dossier_images=dossier_images_ia,
                            )

                    st.session_state["df_pp"]         = df_pp
                    st.session_state["pp_methode"]    = "IA"
                    st.session_state["pp_commune"]    = ville_pp
                    st.session_state["pp_ia_dossier"] = dossier_images_ia
                    st.toast(f"Analyse IA terminée pour {len(df_pp)} intersections.", icon="✅", duration="long")

        elif methode_pp == "Mixte (IA + OSM/Accidents)":
            import os

            _inter_source_mixte = st.session_state.get("inter_geojson_path")
            _inter_prete_mixte = bool(
                _inter_source_mixte
                and (
                    not _intersections_source_est_chemin(_inter_source_mixte)
                    or Path(_inter_source_mixte).exists()
                )
            )
            _pm_prete_mixte = (
                "df_pm" in st.session_state
                and st.session_state.get("pm_commune") == ville_pp
            )

            if not os.path.exists(os.path.join("models", "best.pt")):
                st.error("Modèle introuvable.")
                st.toast("Modèle models/best.pt introuvable.", icon="❌", duration="long")
            elif not _inter_prete_mixte:
                st.error("Générez d'abord les intersections (Étape 1) avant de lancer la détection Mixte.")
                st.toast("Intersections manquantes pour lancer le Mixte.", icon="⚠️", duration="long")
            elif not _pm_prete_mixte:
                st.error(
                    "Générez d'abord les lieux d'intérêt (Étape 2) pour cette commune avant de "
                    "lancer la détection Mixte."
                )
                st.toast("Lieux d'intérêt (PM) manquants pour lancer le Mixte.", icon="⚠️", duration="long")
            else:
                from datetime import datetime
                import src.IA_PP as IA_PP

                with st.spinner(f"Préparation de l'analyse Mixte pour **{ville_pp}**…"):
                    _combos_mixte = st.session_state.get("combos_selectionnes", [])
                    df_inter_mixte = charger_intersections_quelconque(_inter_source_mixte, _combos_mixte)

                    pois_mixte = st.session_state["df_pm"]

                    df_inter_mixte = filtre_distance(pois_mixte, df_inter_mixte, rayon_km=radius_km)
                    df_inter_mixte = fusion_croisement(df_inter_mixte, threshold_km=0.03)

                if df_inter_mixte.empty:
                    st.warning("Aucune intersection après filtrage géographique — Mixte non lancé.")
                    st.toast("Aucune intersection à analyser après filtrage.", icon="⚠️", duration="long")
                else:
                    dossier_images_mixte = str(
                        Path("data/raw/images_pp")
                        / f"images_{ville_pp}_{datetime.now().strftime('%d-%m-%Y_%Hh%M')}"
                    )

                    st.markdown("**Progression :**")
                    zone_logs_mixte = st.empty()

                    class StreamlitLoggerMixte(io.StringIO):
                        def write(self, texte):
                            super().write(texte)
                            lignes = self.getvalue().splitlines()
                            zone_logs_mixte.code("\n".join(lignes[-25:]) or "…", language="text")
                            return len(texte)

                    logs_mixte = StreamlitLoggerMixte()
                    # Note : contrairement à src/fusion_mixte.calculer_mixte (qui interroge
                    # Overpass sur toute la commune via identification_PP.main), la partie
                    # OSM ici est scopée aux intersections déjà filtrées par l'Étape 2/3
                    # (_osm_accidents_scope_locale / _telecharger_passages_zone_filtree,
                    # définies plus haut dans ce fichier) — évite les timeouts Overpass sur
                    # les grandes communes en ne demandant que la zone utile.
                    with st.spinner(f"Fusion IA / OSM+Accidents pour **{ville_pp}**…"):
                        with contextlib.redirect_stdout(logs_mixte):
                            df_ia = IA_PP.analyser_toutes_intersections_filtre(
                                df_inter_mixte, col_lat="latitude", col_lon="longitude",
                                rayon_filtre_m=rayon_filtre_mixte, dossier_images=dossier_images_mixte,
                                conf_min=conf_min_mixte,
                            )
                            df_osm_acc = _osm_accidents_scope_locale(
                                ville_pp, df_inter_mixte, Path(__file__).parent,
                            )

                            df_pp = df_inter_mixte.copy()
                            df_pp["nb_traversees_ia"] = df_ia["nb_traversees"].to_numpy()

                            if df_osm_acc is None or df_osm_acc.empty:
                                print(
                                    "\n Méthode OSM+Accidents indisponible pour cette commune — "
                                    "le comptage mixte retombe entièrement sur l'IA."
                                )
                                df_pp["nb_traversees_osm_accident"] = 0
                                df_pp["nb_traversees"] = df_pp["nb_traversees_ia"]
                            else:
                                df_pp = _joindre_nb_traversees_par_proximite(df_pp, df_osm_acc, rayon_m=25)
                                df_pp = df_pp.rename(columns={"nb_traversees": "nb_traversees_osm_accident"})

                                nb_ia = df_pp["nb_traversees_ia"]
                                nb_osm_acc = df_pp["nb_traversees_osm_accident"]
                                deux_positifs = (nb_ia > 0) & (nb_osm_acc > 0)
                                compromis = ((nb_ia + nb_osm_acc) / 2).round().astype(int)
                                df_pp["nb_traversees"] = np.where(deux_positifs, compromis, nb_ia + nb_osm_acc)

                                print(f"\n Fusion mixte IA (conf >= {conf_min_mixte}) / OSM+Accidents :")
                                print(f"   Total passages détectés par l'IA filtrée   : {int(nb_ia.sum())} (moyenne {nb_ia.mean():.2f}/intersection)")
                                print(f"   Total passages détectés par OSM+Accidents  : {int(nb_osm_acc.sum())} (moyenne {nb_osm_acc.mean():.2f}/intersection)")
                                print(f"   Total passages retenus (mixte)             : {int(df_pp['nb_traversees'].sum())} (moyenne {df_pp['nb_traversees'].mean():.2f}/intersection)")
                                print(f"   {int(deux_positifs.sum())} intersection(s) sur {len(df_pp)} où les deux méthodes détectent quelque chose (moyenne appliquée).")

                    st.session_state["df_pp"]         = df_pp
                    st.session_state["pp_methode"]    = "Mixte"
                    st.session_state["pp_commune"]    = ville_pp
                    st.session_state["pp_ia_dossier"] = dossier_images_mixte
                    st.toast(f"Analyse Mixte terminée pour {len(df_pp)} intersections.", icon="✅", duration="long")

        st.session_state["pp_generation_en_cours"] = False

    if "pp_methode" in st.session_state:
        with st.spinner("Préparation du tableau et des images…"):
            _m = st.session_state["pp_methode"]
            _c = st.session_state.get("pp_commune", "")
            _m_affiche = "OSM + Accidents" if _m == "OSM" else _m

            if _m in ("IA", "Mixte") and "df_pp" in st.session_state:
                _df_pp_r = st.session_state["df_pp"]
                st.success(f"✅ **{len(_df_pp_r)} intersections analysées** via {_m} pour {_c}.")
                with st.expander(f"📋 Voir le tableau ({len(_df_pp_r):,} lignes)", expanded=False):
                    st.dataframe(_df_pp_r.head(15), use_container_width=True)
                    st.caption(f"{len(_df_pp_r)} lignes au total")

                col_dl_ia_csv, col_dl_ia_zip = st.columns(2)
                with col_dl_ia_csv:
                    st.download_button(
                        label="📥 Télécharger les résultats (.csv)",
                        data=_df_pp_r.to_csv(index=False).encode("utf-8"),
                        file_name=f"passages_pietons_{_m.lower()}_{_c.lower().replace(' ', '_')}.csv",
                        mime="text/csv",
                        help=(
                            "Résultat exploitable (colonne 'nb_traversees' par intersection) — "
                            "réimportable à l'Étape 4 ou ici même, pour éviter de relancer l'IA."
                        ),
                        key="dl_pp_ia_csv",
                        use_container_width=True,
                    )

                _dossier_ia = st.session_state.get("pp_ia_dossier")
                if _dossier_ia and Path(_dossier_ia).is_dir():
                    with col_dl_ia_zip:
                        _zip_buf_ia = io.BytesIO()
                        with zipfile.ZipFile(_zip_buf_ia, "w", zipfile.ZIP_DEFLATED) as zf:
                            for _f in Path(_dossier_ia).iterdir():
                                if _f.is_file():
                                    zf.write(_f, arcname=_f.name)
                        _zip_buf_ia.seek(0)
                        st.download_button(
                            label="🖼️ Télécharger les images annotées (.zip)",
                            data=_zip_buf_ia,
                            file_name=f"images_pp_{_c.lower().replace(' ', '_')}.zip",
                            mime="application/zip",
                            help="Preuves visuelles uniquement — pas réimportable, juste pour vérification.",
                            key="dl_pp_ia_zip",
                            use_container_width=True,
                        )

            elif "df_pp" in st.session_state:
                _df_pp_r = st.session_state["df_pp"]
                st.success(f"✅ **{len(_df_pp_r)} entrées PP** via {_m_affiche} pour {_c}.")
                with st.expander(f"📋 Voir le tableau ({len(_df_pp_r):,} lignes)", expanded=False):
                    st.dataframe(_df_pp_r.head(15), use_container_width=True)
                    st.caption(f"{len(_df_pp_r)} lignes au total")
                st.download_button(
                    label="📥 Télécharger l'analyse des passages piétons",
                    data=_df_pp_r.to_csv(index=False).encode("utf-8"),
                    file_name=f"passages_pietons_{_c.lower().replace(' ', '_')}.csv",
                    mime="text/csv",
                    key="dl_pp_csv",
                    use_container_width=True,
                )

    pied_de_page_navigation("etape3")


# ─────────────────────────────────────────────
# 8. Page — Étape 4 : Fiches équipes (reprise du bloc de app5.py)
# ─────────────────────────────────────────────
def _polygones_etoiles_mapbox(lats, lons, textes, rayon_deg=0.00018, ratio_interieur=0.42):
    """
    Construit un seul tracé Scattermapbox (mode="lines" + fill="toself") dessinant
    une étoile à 5 branches par point (polygone à 10 sommets alternant rayon
    extérieur/intérieur), séparées par `None` — pour marquer les lieux d'intérêt PMR
    sur la carte. Scattermapbox ne permet pas de personnaliser couleur/taille d'un
    marker.symbol sur un style sans jeton Mapbox (carto-positron), d'où ce
    contournement géométrique.
    """
    lon_poly, lat_poly, text_poly = [], [], []
    n_branches = 5
    for lat, lon, texte in zip(lats, lons, textes):
        compression_lon = 1 / max(cos(radians(lat)), 0.01)  # compense l'étirement des longitudes selon la latitude
        for i in range(n_branches * 2 + 1):
            angle = pi / 2 + i * pi / n_branches
            rayon = rayon_deg if i % 2 == 0 else rayon_deg * ratio_interieur
            lon_poly.append(lon + rayon * cos(angle) * compression_lon)
            lat_poly.append(lat + rayon * sin(angle))
            text_poly.append(texte)
        lon_poly.append(None)
        lat_poly.append(None)
        text_poly.append(None)
    return lon_poly, lat_poly, text_poly


@st.dialog("🎉 Feuilles terrain générées !")
def _popup_resultat_final(nb_feuilles: int, n_equipes: int, ville: str):
    st.success(f"**{nb_feuilles} feuille(s)** générée(s) pour **{n_equipes} équipe(s)** — {ville}.")
    st.caption("La carte, les statistiques par équipe et le téléchargement ZIP sont juste en dessous, sur la page.")
    if st.button("Fermer", use_container_width=True):
        st.rerun()


def page_etape4():
    st.header("Étape 4 — 📄 Générer les fiches équipes")

    commune_str = st.session_state.get("commune_val", "")
    radius_km = st.session_state.get("radius_km_val", 0.2)
    cfg = st.session_state.get("cfg_commune", {})

    if not commune_str.strip():
        st.info("Saisissez d'abord le nom de la commune dans l'Étape 1.")

    st.markdown(
        "**Objectif :** combiner intersections, lieux d'intérêt et passages piétons "
        "pour répartir les équipes et générer les feuilles terrain prêtes à imprimer."
    )

    # ── Point de rendez-vous ────────────────────────────────────────────
    st.subheader("Point de rendez-vous")

    # Commune déjà pré-configurée (YAML) avec un point de RDV fixé à la main :
    # on respecte cette valeur, pas d'appel API automatique dans ce cas.
    _meetup_preconfigure = "meetup_lat" in cfg and "meetup_long" in cfg

    # ── Auto-détection de la mairie (une seule fois par commune manuelle) ──
    if (
        commune_str.strip()
        and not _meetup_preconfigure
        and st.session_state.get("mairie_auto_tentative_commune") != commune_str
    ):
        # Marqué "tenté" avant même l'appel API, succès ou non, pour ne pas
        # ré-interroger l'API à chaque rerun (ex: si la mairie est introuvable).
        st.session_state["mairie_auto_tentative_commune"] = commune_str
        with st.spinner("Détection automatique de la mairie…"):
            _lat_auto, _lon_auto = recuperer_coords_mairie(commune_str)
        if _lat_auto is not None:
            st.session_state["mairie_lat"] = _lat_auto
            st.session_state["mairie_lon"] = _lon_auto
            st.session_state["mairie_commune"] = commune_str
            st.session_state["input_lat"] = _lat_auto
            st.session_state["input_lon"] = _lon_auto

    redetect_mairie_btn = st.button(
        "🔄 Re-détecter la mairie",
        disabled=not commune_str.strip(),
        help=(
            "Relance la recherche des coordonnées de la mairie via l'API officielle "
            "— utile si l'auto-détection a échoué ou après une modification manuelle."
        ),
        use_container_width=True,
    )

    if redetect_mairie_btn and commune_str.strip():
        with st.spinner("Recherche de la mairie…"):
            _lat_m, _lon_m = recuperer_coords_mairie(commune_str)
        if _lat_m is not None:
            st.session_state["mairie_lat"] = _lat_m
            st.session_state["mairie_lon"] = _lon_m
            st.session_state["mairie_commune"] = commune_str
            st.session_state["input_lat"] = _lat_m
            st.session_state["input_lon"] = _lon_m
            st.success(f"Mairie trouvée : {_lat_m:.6f}, {_lon_m:.6f}")
            st.rerun()
        else:
            st.warning("Mairie introuvable — saisissez les coordonnées manuellement.")

    # La mairie en cache n'est valable que pour la commune courante (évite de
    # réutiliser par erreur les coordonnées d'une commune précédente).
    _mairie_valide = st.session_state.get("mairie_commune") == commune_str
    _default_lat = st.session_state["mairie_lat"] if _mairie_valide else float(cfg.get("meetup_lat", 48.8566))
    _default_lon = st.session_state["mairie_lon"] if _mairie_valide else float(cfg.get("meetup_long", 2.3522))

    col_lat, col_lon = st.columns(2)
    meetup_lat = col_lat.number_input("Latitude",  value=_default_lat, format="%.6f", key="input_lat")
    meetup_lon = col_lon.number_input("Longitude", value=_default_lon, format="%.6f", key="input_lon")
    st.caption("Rempli automatiquement avec la mairie de la commune — modifiez les valeurs ci-dessus pour ajuster le point de RDV.")

    n_teams = st.slider(
        "Nombre d'équipes",
        min_value=1, max_value=20,
        value=st.session_state.get("n_teams_val", int(cfg.get("n_teams", 5))), step=1,
        help="Les intersections seront réparties en N groupes géographiques.",
        key="input_n_teams",
    )
    st.session_state["n_teams_val"] = n_teams

    # ── État des sources (auto par défaut) ──────────────────────────────────
    # inter_geojson_path peut être soit un chemin (str) vers un GeoJSON
    # auto-téléchargé, soit un fichier importé (objet uploader) depuis
    # l'Étape 1 "fichier personnalisé" — les deux cas doivent être gérés.
    _inter_geojson_path = st.session_state.get("inter_geojson_path")
    _inter_geojson_pret = bool(
        _inter_geojson_path
        and (
            not _intersections_source_est_chemin(_inter_geojson_path)
            or Path(_inter_geojson_path).exists()
        )
    )

    col_status_inter, col_status_lieux = st.columns(2)

    with col_status_inter:
        if _inter_geojson_pret:
            _nom_inter_pret = (
                _inter_geojson_path.name
                if not _intersections_source_est_chemin(_inter_geojson_path)
                else Path(_inter_geojson_path).name
            )
            st.success(f"✅ Intersections chargées : `{_nom_inter_pret}`")
        else:
            st.info(
                "Aucune intersection auto-chargée — importez un fichier ci-dessous ou utilisez "
                "l'Étape 1."
            )

    with col_status_lieux:
        if st.session_state.get("pm_buffer"):
            st.success(
                f"✅ Lieux d'intérêt (PM) déjà générés pour "
                f"**{st.session_state.get('pm_commune', '')}**."
            )
        else:
            st.info(
                "Les lieux seront générés automatiquement au clic sur « ⚡ Générer les feuilles "
                "terrain », avec les filtres cochés dans l'Étape 2."
            )

    # ── Importer mes propres fichiers (optionnel, remplace l'auto) ─────────
    with st.expander("📂 Importer mes propres fichiers (avancé)", expanded=False):
        st.caption(
            "⚠️ Les filtres (types de voies, catégories de lieux) ne s'appliquent pas "
            "à vos propres fichiers — ils sont utilisés tels quels."
        )
        col_upload_inter, col_upload_lieux, col_upload_pp = st.columns(3)

        with col_upload_inter:
            intersections_file = st.file_uploader(
                "Votre fichier intersections.csv",
                type=["csv"],
                key="uploader_intersections_manuel_e4",
                help="Remplace le téléchargement automatique si un fichier est fourni ici. Utilisé sans filtre.",
            )

        with col_upload_lieux:
            lieux_file = st.file_uploader(
                "Votre fichier lieux.xlsx (points d'intérêt)",
                type=["xlsx"],
                key="uploader_lieux_manuel",
                help="Remplace les lieux déjà générés si un fichier est fourni ici.",
            )

        with col_upload_pp:
            pp_file = st.file_uploader(
                "Votre fichier passages_pietons.csv (optionnel)",
                type=["csv"],
                key="uploader_pp_manuel_e4",
                help=(
                    "Deux formats acceptés : soit 'latitude'/'longitude' (un passage piéton "
                    "repéré par ligne, ex. export OSM/Accidents), soit 'intersection'/"
                    "'nb_traversees' déjà agrégé par intersection (ex. export CSV d'un "
                    "résultat IA depuis l'Étape 3). Sans ce fichier (et sans passage par "
                    "l'Étape 3), les nombres de passages piétons des fiches seront générés "
                    "aléatoirement."
                ),
            )
            if pp_file is None:
                st.caption(
                    "⚠️ Sans ce fichier ni passage par l'Étape 3, les passages piétons "
                    "seront **fictifs (aléatoires)**."
                )

        st.divider()
        generate_btn_avance = st.button(
            "⚡ Générer les fiches équipes avec mes fichiers",
            key="btn_generate_avance",
            type="primary",
            use_container_width=True,
            disabled=intersections_file is None or not commune_str.strip(),
            help="Utilise directement les fichiers importés ci-dessus (intersections obligatoire, lieux optionnel).",
        )

    # ── Résolution source intersections ─────────────────────────────────────
    if intersections_file is not None:
        intersections_source = "csv"
    elif _inter_geojson_pret:
        intersections_source = "geojson"
    else:
        intersections_source = None

    # ── Résolution source lieux ───────────────────────────────────────────
    if lieux_file is not None:
        lieux_source = lieux_file
    elif st.session_state.get("pm_buffer"):
        lieux_source = io.BytesIO(st.session_state["pm_buffer"])
        lieux_source.name = "lieux_genere.xlsx"
    else:
        lieux_source = None

    # ── Résolution source passages piétons ────────────────────────────────
    # Un fichier importé ici prend toujours la priorité sur un éventuel
    # résultat de l'Étape 3 (qui pourrait concerner une autre commune).
    pp_source = pp_file if pp_file is not None else None

    # ── Prévisualisation ────────────────────────────────────────────────
    _has_inter = intersections_source is not None
    _has_lieux = lieux_source is not None
    _has_pp    = pp_source is not None or "df_pp" in st.session_state

    if _has_inter or _has_lieux or _has_pp:
        st.divider()
        st.subheader("Aperçu des données chargées")

        import pandas as pd

        tabs_preview = []
        if _has_inter:
            tabs_preview.append("Intersections")
        if _has_lieux:
            tabs_preview.append("Lieux d'intérêt")
        if _has_pp:
            tabs_preview.append("Passages piétons")

        tabs = st.tabs(tabs_preview)
        idx = 0

        if _has_inter:
            with tabs[idx]:
                if intersections_source == "geojson" and "inter_df_preview" in st.session_state:
                    _df_p = st.session_state["inter_df_preview"]
                    with st.expander(f"📋 Voir le tableau ({len(_df_p):,} lignes)", expanded=False):
                        st.dataframe(_df_p.head(20), use_container_width=True)
                        st.caption(f"{len(_df_p):,} intersections · filtrage voies appliqué")
                elif intersections_source == "csv" and intersections_file:
                    _df_p = pd.read_csv(intersections_file)
                    intersections_file.seek(0)
                    with st.expander(f"📋 Voir le tableau ({len(_df_p):,} lignes)", expanded=False):
                        st.dataframe(_df_p.head(20), use_container_width=True)
                        st.caption(f"{len(_df_p):,} lignes · {len(_df_p.columns)} colonnes")
            idx += 1

        if _has_lieux:
            with tabs[idx]:
                _df_l = pd.read_excel(lieux_source)
                if hasattr(lieux_source, "seek"):
                    lieux_source.seek(0)
                with st.expander(f"📋 Voir le tableau ({len(_df_l):,} lignes)", expanded=False):
                    st.dataframe(_df_l.head(20), use_container_width=True)
                    st.caption(f"{len(_df_l):,} points d'intérêt")
            idx += 1

        if _has_pp:
            with tabs[idx]:
                if pp_source is not None:
                    _df_pp_p = pd.read_csv(pp_source)
                    pp_source.seek(0)
                    with st.expander(f"📋 Voir le tableau ({len(_df_pp_p):,} lignes)", expanded=False):
                        st.dataframe(_df_pp_p.head(20), use_container_width=True)
                        st.caption(f"{len(_df_pp_p):,} passages piétons importés")
                else:
                    _df_pp_p = st.session_state["df_pp"]
                    _pp_methode_p = st.session_state.get("pp_methode", "")
                    _pp_commune_p = st.session_state.get("pp_commune", "")
                    with st.expander(f"📋 Voir le tableau ({len(_df_pp_p):,} lignes)", expanded=False):
                        st.dataframe(_df_pp_p.head(20), use_container_width=True)
                        st.caption(f"{len(_df_pp_p):,} lignes · méthode {_pp_methode_p} · {_pp_commune_p}")

    # ── Bouton Générer ──────────────────────────────────────────────────
    st.divider()

    ready = (
        (intersections_source is not None)
        and commune_str.strip() != ""
    )

    if not ready:
        manquants = []
        if intersections_source is None:
            manquants.append("intersections (téléchargement auto ou CSV manuel)")
        if not commune_str.strip():
            manquants.append("nom de la commune")
        st.info(f"En attente : **{', '.join(manquants)}**")
    elif lieux_source is None:
        st.caption(
            "Les lieux d'intérêt seront générés automatiquement au clic, avec les "
            "filtres cochés dans l'Étape 2."
        )

    generate_btn = st.button(
        "⚡ Générer les feuilles terrain",
        disabled=not ready,
        type="primary",
        use_container_width=True,
    )

    # ── Pipeline principal ──────────────────────────────────────────────
    # Déclenché par le bouton principal ci-dessus OU par le bouton dédié dans
    # "📂 Importer mes propres fichiers (avancé)" — même pipeline dans les deux cas.
    if (generate_btn or generate_btn_avance) and ready:
        import pandas as pd

        output_dir = Path("data/output/fiches_equipes")
        output_dir.mkdir(parents=True, exist_ok=True)

        progress = st.progress(0, text="Initialisation…")
        status   = st.empty()

        try:
            # ── Etape 1 — Chargement des intersections ────────────────────
            status.info("**Étape 1/6** — Chargement et nettoyage des intersections…")
            progress.progress(8)

            if intersections_source == "geojson":
                # _inter_geojson_path peut être le chemin d'un GeoJSON auto-téléchargé
                # OU un fichier importé depuis l'Étape 1 "fichier personnalisé" —
                # charger_intersections_quelconque() gère les deux cas.
                _combos_pipeline = st.session_state.get("combos_selectionnes", [])
                df = charger_intersections_quelconque(_inter_geojson_path, None)
                if _combos_pipeline:
                    avant = len(df)
                    df = filtrer_par_combinaisons_voies(df, _combos_pipeline)
                    status.info(f"**Étape 1/6** — Filtre voies : {avant} → {len(df)} intersections.")
            else:
                # Fichier personnel importé en Étape 4 : utilisé tel quel, sans filtre
                # par combinaisons de voies (celui-ci ne s'applique qu'aux intersections
                # auto-chargées/importées en Étape 1 — un fichier personnel est considéré
                # déjà préparé par l'utilisateur).
                #
                # Deux formats sont acceptés :
                # - "propre" (déjà nettoyé, colonnes latitude/longitude/intersection) —
                #   notamment celui téléchargeable depuis l'Étape 1 — utilisé tel quel.
                # - "brut" (export GeoJSON aplati type data.gouv.fr, colonnes
                #   properties/context, geometry/coordinates/0…) — passe par
                #   charger_intersections() pour être nettoyé.
                intersections_path = Path("data/raw/intersections_upload.csv")
                intersections_path.parent.mkdir(parents=True, exist_ok=True)
                intersections_path.write_bytes(intersections_file.read())

                df = pd.read_csv(intersections_path)
                if not {"latitude", "longitude", "intersection"}.issubset(df.columns):
                    df = charger_intersections(str(intersections_path), commune_str)

            progress.progress(15)

            if df.empty:
                st.error(
                    "Aucune intersection après chargement/filtrage. "
                    "Vérifiez le nom de la commune ou les types de voies sélectionnés."
                )
                st.stop()

            # ── Étape 2 — Chargement des POI ──────────────────────────────
            lieux_path = Path("data/raw/lieux_upload.xlsx")
            lieux_path.parent.mkdir(parents=True, exist_ok=True)

            _ville_actuelle = commune_str.split(",")[0].strip()

            if lieux_file is not None:
                status.info("**Étape 2/6** — Chargement des points d'intérêt (fichier fourni)…")
                progress.progress(30)
                lieux_path.write_bytes(lieux_file.read())
            elif (
                st.session_state.get("pm_buffer")
                and st.session_state.get("pm_commune") == _ville_actuelle
            ):
                status.info("**Étape 2/6** — Réutilisation des lieux déjà générés…")
                progress.progress(30)
                lieux_path.write_bytes(st.session_state["pm_buffer"])
            else:
                _ville_pm = _ville_actuelle
                status.info(f"**Étape 2/6** — Génération des points d'intérêt pour **{_ville_pm}**… (1-2 min)")
                progress.progress(30)

                _cs_choisies  = st.session_state.get("pm_categories_sante_choisies", LABELS_SANTE)
                _ce_choisies  = st.session_state.get("pm_categories_ecoles_choisies", LABELS_ECOLES)
                _co_labels    = st.session_state.get("pm_categories_osm_labels_choisies", LABELS_OSM)
                _co_choisies  = st.session_state.get("pm_categories_osm_choisies")

                _categories_sante  = None if set(_cs_choisies) == set(LABELS_SANTE) else _cs_choisies
                _categories_ecoles = None if set(_ce_choisies) == set(LABELS_ECOLES) else _ce_choisies
                _categories_osm    = None if set(_co_labels) == set(LABELS_OSM) else _co_choisies

                zone_logs_pm = st.empty()

                class StreamlitLoggerPM(io.StringIO):
                    def write(self, texte):
                        super().write(texte)
                        lignes = self.getvalue().splitlines()
                        zone_logs_pm.code("\n".join(lignes[-20:]) or "…", language="text")
                        return len(texte)

                logs_pm = StreamlitLoggerPM()
                with contextlib.redirect_stdout(logs_pm):
                    df_pm_genere = construire_dataframe_PM_sans_input_avec_filtres(
                        _ville_pm,
                        categories_osm=_categories_osm,
                        categories_sante=_categories_sante,
                        categories_ecoles=_categories_ecoles,
                    )

                if df_pm_genere.empty:
                    st.error(
                        f"Aucun lieu d'intérêt trouvé pour '{_ville_pm}' avec les filtres sélectionnés. "
                        "Cochez plus de catégories dans l'Étape 2."
                    )
                    st.toast(f"Aucun lieu trouvé pour {_ville_pm}.", icon="⚠️", duration="long")
                    st.stop()

                df_pm_genere.to_excel(lieux_path, index=False)

                st.session_state["df_pm"]      = df_pm_genere
                st.session_state["pm_commune"] = _ville_pm
                st.session_state["pm_filters_signature"] = signature_filtres_pm(_cs_choisies, _ce_choisies, _co_labels)
                st.session_state.pop("is_fichier_perso_pm", None)
                st.session_state.pop("pm_perso_last_uploaded_name", None)
                _buf_pm = io.BytesIO()
                df_pm_genere.to_excel(_buf_pm, index=False)
                _buf_pm.seek(0)
                st.session_state["pm_buffer"] = _buf_pm.getvalue()
                st.toast(f"{len(df_pm_genere)} lieux générés pour {_ville_pm}.", icon="✅", duration="long")

            pois = charger_points(str(lieux_path))

            # ── Étape 3 — Filtrage géographique ───────────────────────────
            status.info("**Étape 3/6** — Filtrage des intersections proches des POI…")
            progress.progress(45)
            df = filtre_distance(pois, df, rayon_km=radius_km)
            df = fusion_croisement(df, threshold_km=0.03)

            # ── Étape 4 — Passages piétons ────────────────────────────────
            status.info("**Étape 4/6** — Intégration des passages piétons…")
            progress.progress(58)

            _pp_methode = st.session_state.get("pp_methode")
            _pp_methode_effectif = _pp_methode
            _pp_aleatoire = False

            if pp_source is not None:
                _pp_methode_effectif = "Import"
                df_pp_upload = pd.read_csv(pp_source)

                if "nb_traversees" in df_pp_upload.columns and "intersection" in df_pp_upload.columns:
                    # Format déjà agrégé par intersection (ex : résultat IA exporté
                    # en CSV à l'Étape 3) — jointure directe, pas de comparaison
                    # géographique nécessaire.
                    status.info(
                        "**Étape 4/6** — Intégration des passages piétons "
                        "(résultat déjà agrégé importé)…"
                    )
                    df = df.merge(
                        df_pp_upload[["intersection", "nb_traversees"]],
                        on="intersection", how="left",
                    )
                    df["nb_traversees"] = df["nb_traversees"].fillna(0)
                else:
                    # Format brut : un point par passage piéton détecté
                    # (latitude/longitude), comparé aux intersections par proximité.
                    status.info("**Étape 4/6** — Intégration des passages piétons (fichier importé)…")
                    from src.identification_PP import comparer_coordonnees
                    df = comparer_coordonnees(df_pp_upload, df)
                    if "nb_pp" in df.columns:
                        df["nb_traversees"] = df["nb_pp"]
                    elif "nb_passages_pietons" in df.columns:
                        df["nb_traversees"] = df["nb_passages_pietons"]
                    else:
                        df["nb_traversees"] = 0

            elif _pp_methode == "IA":
                _df_pp_cache = st.session_state.get("df_pp")
                _ia_deja_faite = (
                    _df_pp_cache is not None
                    and st.session_state.get("pp_commune") == _ville_actuelle
                    and "intersection" in df.columns
                    and "intersection" in _df_pp_cache.columns
                    and set(df["intersection"]) == set(_df_pp_cache["intersection"])
                )
                if _ia_deja_faite:
                    status.info("**Étape 4/6** — Réutilisation de l'analyse IA déjà effectuée dans l'Étape 3…")
                    df = _df_pp_cache
                else:
                    from src.IA_PP import analyser_toutes_intersections
                    from datetime import datetime
                    import re
                    dossier_images = str(
                        Path("data/raw/images_pp")
                        / f"images_{_ville_actuelle}_{datetime.now().strftime('%d-%m-%Y_%Hh%M')}"
                    )

                    _pattern_ia2 = re.compile(r"\[(\d+)/(\d+)\]")

                    class StreamlitLoggerIA2(io.StringIO):
                        def write(self, texte):
                            super().write(texte)
                            match = _pattern_ia2.search(texte)
                            if match:
                                _i2, _tot2 = int(match.group(1)), int(match.group(2))
                                status.info(f"**Étape 4/6** — Détection IA — {_i2}/{_tot2} passages analysés…")
                            return len(texte)

                    logs_ia2 = StreamlitLoggerIA2()
                    with contextlib.redirect_stdout(logs_ia2):
                        df = analyser_toutes_intersections(
                            df, col_lat="latitude", col_lon="longitude", dossier_images=dossier_images
                        )
                    st.session_state["df_pp"]         = df
                    st.session_state["pp_commune"]    = _ville_actuelle
                    st.session_state["pp_ia_dossier"] = dossier_images

            elif _pp_methode == "OSM" and "df_pp" in st.session_state:
                # df_pp est déjà agrégé par intersection (identification_PP.main()) —
                # jointure par proximité plutôt que comparer_coordonnees, qui
                # traiterait à tort ces lignes comme des points bruts et
                # supprimerait toute intersection sans correspondance à 30 m
                # (les intersections ont pu être fusionnées/filtrées depuis
                # l'Étape 3, ce qui décale légèrement leurs coordonnées)
                df_pp_session = st.session_state["df_pp"]
                df = _joindre_nb_traversees_par_proximite(df, df_pp_session)

            elif _pp_methode == "Mixte" and "df_pp" in st.session_state:
                # df_pp est déjà agrégé par intersection (fusion_mixte.calculer_mixte) —
                # même logique de jointure par proximité que pour OSM + Accidents.
                df_pp_session = st.session_state["df_pp"]
                df = _joindre_nb_traversees_par_proximite(df, df_pp_session)

            else:
                df["nb_traversees"] = np.random.randint(1, 5, size=len(df))
                _pp_aleatoire = True
                st.warning(
                    "⚠️ **Aucune donnée de passages piétons fournie** — les fiches équipes "
                    "générées contiennent des nombres de passages piétons **inventés "
                    "aléatoirement** (1 à 4 par intersection) et ne reflètent PAS la réalité "
                    "du terrain. Pour des données réelles, complétez l'Étape 3 ou importez un "
                    "fichier passages piétons dans le bloc « Importer mes propres fichiers » "
                    "ci-dessus, puis régénérez.",
                    icon="⚠️",
                )
                status.warning("**Étape 4/6** — Aucune méthode PP configurée : valeurs provisoires (aléatoires) utilisées.")
                st.toast("Passages piétons fictifs (aléatoires) utilisés — voir l'avertissement.", icon="⚠️", duration="long")

            st.session_state["final_pp_aleatoire"] = _pp_aleatoire
            progress.progress(65)

            # ── Étape 5 — Clustering & routing ────────────────────────────
            status.info("**Étape 5/6** — Répartition par équipes et calcul des itinéraires…")
            progress.progress(75)
            df = assigner_equipes(df, n_equipes=n_teams, meetup_lat=meetup_lat, meetup_long=meetup_lon)

            class StreamlitLoggerRoutage(io.StringIO):
                def write(self, texte):
                    super().write(texte)
                    if texte.strip():
                        status.info(f"**Étape 5/6** — {texte.strip()}")
                    return len(texte)

            logs_routage = StreamlitLoggerRoutage()
            with contextlib.redirect_stdout(logs_routage):
                import osmnx as ox
                import requests

                for _i_serveur_ov, _url_overpass_ov in enumerate(SERVEURS_OVERPASS_ROUTAGE):
                    ox.settings.overpass_url = _url_overpass_ov
                    try:
                        teams_dict = route_toutes_equipes2(df, meetup_lat, meetup_lon)
                        break
                    except requests.exceptions.RequestException as e:
                        dernier_serveur_ov = _i_serveur_ov == len(SERVEURS_OVERPASS_ROUTAGE) - 1
                        print(f"Serveur Overpass {_url_overpass_ov} indisponible ({e}).")
                        if dernier_serveur_ov:
                            raise
                        print("Tentative sur le serveur Overpass suivant...")

            # ── Étape 6 — Export XLSX ─────────────────────────────────────
            status.info("**Étape 6/6** — Génération des feuilles terrain XLSX…")
            progress.progress(90)
            output_files = export_final_equipes(teams_dict, str(output_dir), _ville_actuelle)

            nettoyer_anciennes_villes_gui(Path(__file__).parent)

            progress.progress(100, text="Terminé ✅")
            status.success(f"**{len(output_files)} feuille(s) générée(s)** pour {n_teams} équipe(s).")

            st.session_state["final_teams_dict"]  = teams_dict
            st.session_state["final_pois"]        = pois
            st.session_state["final_output_files"] = output_files
            st.session_state["final_meetup"]      = (meetup_lat, meetup_lon)
            st.session_state["final_pp_methode"]  = _pp_methode_effectif
            st.session_state["final_ville"]       = _ville_actuelle
            st.session_state["final_n_teams"]     = n_teams

            _popup_resultat_final(len(output_files), n_teams, commune_str.split(",")[0].strip())

        except FileNotFoundError as e:
            progress.empty()
            st.error(f"Fichier introuvable : {e}")
            st.toast(f"Fichier introuvable : {e}", icon="❌", duration="long")
        except KeyError as e:
            progress.empty()
            st.error(f"Colonne manquante : **{e}** — vérifiez que vos données contiennent latitude, longitude et intersection.")
            st.toast(f"Colonne manquante : {e}", icon="❌", duration="long")
        except Exception as e:
            progress.empty()
            st.error(f"Erreur inattendue : {e}")
            st.toast(f"Erreur inattendue : {e}", icon="❌", duration="long")
            with st.expander("Détails (débogage)"):
                import traceback
                st.code(traceback.format_exc())

    # ── Résultat de la dernière génération (persiste après un rerun) ────
    if "final_teams_dict" in st.session_state:
        import pandas as pd

        _teams_dict_f    = st.session_state["final_teams_dict"]
        _pois_f          = st.session_state["final_pois"]
        _output_files_f  = st.session_state["final_output_files"]
        _meetup_lat_f, _meetup_lon_f = st.session_state["final_meetup"]
        _pp_methode_f    = st.session_state.get("final_pp_methode")
        _ville_f         = st.session_state.get("final_ville", "")

        st.divider()

        st.subheader("🗺️ Carte des intersections par équipe")
        st.caption(
            "Cliquez sur une ligne du tableau ci-dessous pour mettre une équipe en "
            "valeur sur la carte et griser les autres. Recliquez sur la même ligne "
            "pour revenir à la vue complète."
        )

        COLORS = [
            "red", "blue", "green", "purple", "orange",
            "darkred", "brown", "goldenrod", "darkblue", "darkgreen",
            "cadetblue", "deeppink", "lightblue", "lightgreen", "gray",
            "black", "silver", "dimgray", "indigo", "salmon",
        ]
        COULEUR_GRISEE = "lightgray"

        # Équipe mise en valeur : fixée par le clic sur le tableau plus bas
        # (persistée en session_state, lue ici avant de dessiner la carte).
        _equipe_en_valeur = st.session_state.get("equipe_en_valeur_carte")

        fig_carte = go.Figure()

        fig_carte.add_trace(go.Scattermapbox(
            lat=[_meetup_lat_f], lon=[_meetup_lon_f],
            mode="markers",
            marker=dict(size=16, color="black"),
            text=["Point de rendez-vous"],
            hoverinfo="text",
            name="Point de rendez-vous",
            showlegend=False,
        ))

        if not _pois_f.empty:
            _textes_pois = _pois_f.get("lieu", pd.Series(["POI"] * len(_pois_f), index=_pois_f.index)).astype(str).tolist()
            _lon_pois_etoiles, _lat_pois_etoiles, _text_pois_etoiles = _polygones_etoiles_mapbox(
                _pois_f["latitude"].tolist(), _pois_f["longitude"].tolist(), _textes_pois,
            )
            fig_carte.add_trace(go.Scattermapbox(
                lat=_lat_pois_etoiles, lon=_lon_pois_etoiles,
                mode="lines",
                fill="toself",
                fillcolor="black",
                line=dict(color="black", width=1),
                text=_text_pois_etoiles,
                hoverinfo="text",
                name="Lieux d'intérêt",
                showlegend=False,
            ))

        for equipe_id, team_df in _teams_dict_f.items():
            couleur_equipe = COLORS[(equipe_id - 1) % len(COLORS)]
            est_en_valeur = _equipe_en_valeur is None or _equipe_en_valeur == equipe_id
            couleur_affichee = couleur_equipe if est_en_valeur else COULEUR_GRISEE
            opacite = 0.85 if est_en_valeur else 0.35

            hover_text = [
                f"Équipe {equipe_id}<br>Ordre : {int(row.get('ordre', 0))}<br>"
                f"{row.get('intersection', '')}<br>"
                f"Passages piétons : {int(row.get('nb_traversees', 0))}"
                for _, row in team_df.iterrows()
            ]

            ordres_text = [str(int(row.get("ordre", 0))) for _, row in team_df.iterrows()]

            fig_carte.add_trace(go.Scattermapbox(
                lat=team_df["latitude"], lon=team_df["longitude"],
                mode="markers+text",
                marker=dict(size=20, color=couleur_affichee, opacity=opacite),
                text=ordres_text,
                textfont=dict(size=10, color="black"),
                textposition="middle center",
                hovertext=hover_text,
                hoverinfo="text",
                name=f"Équipe {equipe_id}",
            ))

        fig_carte.update_layout(
            mapbox=dict(
                style="carto-positron",
                center=dict(lat=_meetup_lat_f, lon=_meetup_lon_f),
                zoom=13,
            ),
            height=500,
            margin=dict(l=0, r=0, t=0, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            # Conserve le zoom/déplacement de l'utilisateur d'un rechargement à
            # l'autre au lieu de recentrer la carte à chaque rerun Streamlit.
            uirevision="carte_equipes",
            # "pan" : le glisser-déposer déplace la carte (comme Folium/Leaflet)
            # plutôt que de dessiner un rectangle de zoom (comportement par défaut de Plotly).
            dragmode="pan",
        )

        st.plotly_chart(
            fig_carte,
            use_container_width=True,
            key="carte_resultat_final",
            # scrollZoom : zoom à la molette de la souris, désactivé par défaut dans
            # Plotly (contrairement à Folium/Leaflet où il est actif nativement).
            config={"scrollZoom": True},
        )

        st.subheader("📊 Répartition par équipe")
        stats_rows = []
        for equipe_id, team_df in _teams_dict_f.items():
            stats_rows.append({
                "_equipe_id": equipe_id,
                "Équipe": f"Équipe {equipe_id}",
                "Intersections": len(team_df),
                "Passages piétons totaux": int(
                    team_df["nb_traversees"].sum() if "nb_traversees" in team_df.columns else 0
                ),
            })
        _df_stats = pd.DataFrame(stats_rows)

        _etat_selection = st.dataframe(
            _df_stats.drop(columns=["_equipe_id"]),
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="table_repartition_equipes",
        )

        _lignes_selectionnees = _etat_selection["selection"]["rows"]
        _equipe_cliquee = (
            int(_df_stats.iloc[_lignes_selectionnees[0]]["_equipe_id"])
            if _lignes_selectionnees else None
        )

        # IMPORTANT : _equipe_cliquee reflète l'état PERSISTANT de la sélection du
        # tableau (pas un évènement ponctuel) — il reste égal tant que l'utilisateur
        # ne change pas sa sélection. On se contente donc de refléter cet état dans
        # la session, sans logique de "toggle" (qui bouclait indéfiniment : dès que
        # la session rattrapait la sélection, le code croyait à un nouveau clic sur
        # la même ligne et redésélectionnait, provoquant un clignotement en boucle).
        # Recliquer sur la même ligne du tableau la désélectionne nativement
        # (comportement intégré de st.dataframe en selection_mode="single-row").
        if _equipe_cliquee != _equipe_en_valeur:
            st.session_state["equipe_en_valeur_carte"] = _equipe_cliquee
            st.rerun()

        _pp_label = {
            "OSM":       "OpenStreetMap (Overpass)",
            "IA":        "Détection IA YOLOv8",
            "Mixte":     "IA + OSM/Accidents (Mixte)",
            "Import":    "Fichier importé",
            None:        "Valeurs provisoires (aléatoires)",
        }.get(_pp_methode_f, "Inconnue")

        if st.session_state.get("final_pp_aleatoire"):
            st.warning(
                "⚠️ **Ces fiches contiennent des passages piétons fictifs (aléatoires)** — "
                "aucune donnée réelle n'a été fournie (ni Étape 3, ni fichier importé). "
                "Ne pas utiliser pour une vraie tournée terrain sans régénérer avec de "
                "vraies données.",
                icon="⚠️",
            )
        else:
            st.caption(f"Méthode passages piétons : {_pp_label}")

        st.subheader("📥 Téléchargement")

        # --- AJOUT KML : Génération du fichier KML juste avant de faire le ZIP ---
        # Note : On récupère teams_dict défini un peu plus haut dans votre code (Ligne 757)
        nom_kml_généré = "carte_globale_intersections.kml"
        if 'teams_dict' in locals() and teams_dict:
            generer_kml_global_une_colonne(teams_dict, nom_fichier_sortie=nom_kml_généré)
        # ------------------------------------------------------------------------

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            #  Inclusion de vos fichiers Excel classiques
            for fpath in _output_files_f:
                zf.write(fpath, arcname=Path(fpath).name)
            
            # --- AJOUT KML : On glisse le fichier KML à l'intérieur du ZIP ---
            # from pathlib import Path ==> erreure  car ne doit pas exister que localement
            if Path(nom_kml_généré).exists():
                zf.write(nom_kml_généré, arcname=nom_kml_généré)
            # -----------------------------------------------------------------

        zip_buffer.seek(0)

        # Bouton principal qui télécharge maintenant le ZIP contenant les Excel ET le KML
        st.download_button(
            label=f"📦 Télécharger les {len(_output_files_f)} feuilles terrain + Carte My Maps (.zip)",
            data=zip_buffer,
            file_name=f"defiaccess_{_ville_f.lower().replace(' ', '_')}.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
            key="dl_zip_final",
        )

        # --- AJOUT KML OPTIONNEL : Un deuxième bouton si l'utilisateur veut SEULEMENT le KML ---
        if Path(nom_kml_généré).exists():
            with open(nom_kml_généré, "rb") as kml_file:
                st.download_button(
                    label="🌐 Télécharger uniquement le fichier KML pour Google My Maps",
                    data=kml_file,
                    file_name="carte_globale_intersections.kml",
                    mime="application/vnd.google-earth.kml+xml",
                    use_container_width=True,
                    key="dl_kml_only"
                )
        # ----------------------------------------------------------------------------------------

        # Uniquement pertinent pour les méthodes IA et Mixte : ce sont les
        # seules qui capturent une image (annotée par YOLO) par intersection
        # analysée — les autres méthodes (OSM, Accidents, Import) n'en génèrent aucune.
        if _pp_methode_f in ("IA", "Mixte"):
            st.subheader("🔍 Vérifier une détection IA")
            st.caption(
                "Collez les coordonnées d'une intersection depuis la colonne "
                "'coordonnees' de la fiche Excel d'une équipe, pour voir l'image "
                "que l'IA a analysée (avec ses détections annotées) et repérer d'éventuelles erreurs."
            )
            col_coords_vi, col_btn_vi = st.columns([3, 1])
            with col_coords_vi:
                _coords_vi = st.text_input(
                    "Coordonnées (latitude,longitude)",
                    key="input_coords_voir_image",
                    placeholder="ex: 48.843520154,2.192857687",
                )
            with col_btn_vi:
                st.write("")
                _voir_image_btn = st.button(
                    "🔍 Voir l'image", key="btn_voir_image", use_container_width=True,
                )

            if _voir_image_btn:
                # importlib.reload : évite de devoir redémarrer tout le
                # serveur Streamlit après une modification de voir_image.py —
                # Streamlit ré-exécute app7.py à chaque interaction, mais le
                # module déjà importé reste en cache (sys.modules) tant que le
                # process ne redémarre pas, sinon (TypeError sur un paramètre
                # ajouté, par exemple, alors que le code semble à jour sur disque)
                import importlib
                from src import voir_image as _mod_voir_image
                importlib.reload(_mod_voir_image)
                parser_coordonnees = _mod_voir_image.parser_coordonnees
                trouver_image = _mod_voir_image.trouver_image
                try:
                    _lat_vi, _lon_vi = parser_coordonnees(_coords_vi.strip())
                except ValueError as e:
                    st.error(f"Coordonnées invalides : {e}")
                else:
                    # limité au dossier de LA génération en cours (pas toutes
                    # les exécutions IA passées) : sinon une intersection déjà
                    # analysée par le passé ressortirait une fois par ancienne
                    # exécution, ce qui n'a aucun rapport avec la fiche affichée ici
                    _dossier_vi = st.session_state.get("pp_ia_dossier")
                    if not _dossier_vi:
                        _images_vi = []
                        st.warning(
                            "Aucune image disponible pour cette génération (résultat IA "
                            "importé depuis un fichier déjà agrégé, sans image capturée)."
                        )
                    else:
                        _images_vi = trouver_image(_lat_vi, _lon_vi, dossier=_dossier_vi)
                    if _dossier_vi and not _images_vi:
                        st.warning(f"Aucune image trouvée pour ({_lat_vi:.5f}, {_lon_vi:.5f}).")
                    else:
                        for _chemin_vi in _images_vi:
                            st.image(
                                _chemin_vi,
                                caption=Path(_chemin_vi).parent.name,
                                use_container_width=True,
                            )

    pied_de_page_navigation("etape4")


# ─────────────────────────────────────────────
# 9. Routeur
# ─────────────────────────────────────────────
_page = st.session_state["page_actuelle"]

if _page == "presentation":
    page_presentation()
elif _page == "etape1":
    page_etape1()
elif _page == "etape2":
    page_etape2()
elif _page == "etape3":
    page_etape3()
elif _page == "etape4":
    page_etape4()
