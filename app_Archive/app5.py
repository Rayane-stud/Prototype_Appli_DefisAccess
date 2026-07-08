"""
FICHIER : app5.py

# BUT : Interface Streamlit no-code pour DEFIACCESS — permet aux bénévoles de
      générer les feuilles terrain (répartition par équipe + itinéraires) sans
      écrire de code.

      Copie de app4.py (qui n'est pas modifié, pour ne pas casser le flux de
      travail de l'équipe / éviter les conflits Git) avec des filtres affinés :
        - "Intersections" : filtre par combinaisons exactes de types de voies
          (Rue/Rue, Rue/Avenue, Avenue/Boulevard...) au lieu d'un filtre par
          type "large" appliqué indépendamment à chaque segment
        - "Générer les lieux" : filtres organisés par thème (cases à cocher +
          boutons "Tout sélectionner"/"Tout désélectionner") pour les
          établissements de santé (Hôpitaux, Cliniques, Laboratoires, Centres
          de santé, Autres), les écoles (Maternelles, Élémentaires, Collèges,
          Lycées, Autres) et les autres lieux OSM (gares, gendarmeries,
          pharmacies, etc.)
        - "Intersections" : source automatique par défaut (fichier local ou
          téléchargement, sans choix technique à faire), fichier personnalisé
          disponible en option repliée

LOGIQUE GLOBALE (affichée aussi à l'utilisateur en haut de la page) :
    Barre latérale : commune, point de rendez-vous, rayon, nombre d'équipes
        ↓
    1. Intersections — récupération auto (ou fichier perso) + filtre par
       combinaisons de types de voies (bloc "🗂️ Intersections")
        ↓
    2. Lieux d'intérêt (PM) — récupération des écoles, mairie, établissements
       de santé, etc. avec filtres par thème (bloc "📍 Générer le fichier des lieux Importants (PM, sous format xlsx)")
        ↓
    3. Filtrage géographique — seules les intersections proches d'un lieu
       d'intérêt sont conservées (dans le pipeline principal, bouton "Générer")
        ↓
    4. Passages piétons — OSM, données accidents, ou détection IA
        ↓
    5. Répartition en équipes + calcul d'itinéraires
        ↓
    6. Export — feuilles terrain Excel (une par équipe) + carte Folium + statistiques

LISTE DES FONCTIONS (définies dans ce fichier — le reste vient de src/) :

- load_yaml_configs() :
    # ROLE : Charger les configurations de communes pré-enregistrées (dossier config/*.yaml)
    # ARGUMENTS : aucun
    # REPONSE : dict {nom_commune: config}

- chemin_geojson_commune() :
    # ROLE : Construire le chemin local attendu du GeoJSON d'intersections d'une commune
    # ARGUMENTS : "code_insee" de type str
    # REPONSE : Path

- sauvegarder_index() / trouver_geojson_existant() :
    # ROLE : Tenir à jour un index ville → chemin GeoJSON (intersections/index.json)
              pour retrouver instantanément un fichier déjà téléchargé, sans
              refaire d'appel API à chaque rechargement de page
    # ARGUMENTS : "ville" de type str (+ "chemin" pour sauvegarder_index)
    # REPONSE : None / Path ou None

- recuperer_coords_mairie() :
    # ROLE : Récupérer les coordonnées GPS de la mairie d'une commune,
              pour pré-remplir le point de rendez-vous
    # ARGUMENTS : "commune_str" de type str
    # REPONSE : tuple (latitude, longitude) ou (None, None) si échec

- bloc_filtre_theme() :
    # ROLE : Afficher un thème de filtre réutilisable (titre, boutons "Tout
              sélectionner"/"Tout désélectionner", cases à cocher) — utilisé
              pour les thèmes santé, écoles et autres lieux OSM
    # ARGUMENTS : "titre", "cle_prefixe" (str), "labels" (list[str]),
                  "labels_preselectionnes" (list[str] optionnel)
    # REPONSE : list[str] des labels cochés
"""
import numpy as np
import io
import zipfile
import contextlib
import yaml
import streamlit as st
import folium
from streamlit_folium import st_folium
from pathlib import Path

# Modules internes du projet
from src.nettoyage import (
    charger_intersections,
    correction_intersections,
    normailisation_intersections,
    doublons_intersections,
    filtrer_intersections,
)
from src.proximite import (
    charger_points,
    filtre_distance,
    fusion_croisement,
    assigner_equipes,
)
from src.routage import route_toutes_equipes
from src.export import export_final_equipes
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

# Labels affichés pour chaque thème de filtre (théme -> liste de libellés)
LABELS_SANTE  = [c["label"] for c in CATEGORIES_FINESS_SANTE] + [CATEGORIE_FINESS_AUTRES]
LABELS_ECOLES = [c["label"] for c in CATEGORIES_ECOLES] + [CATEGORIE_ECOLE_AUTRES]
LABELS_OSM    = [c["label"] for c in CATEGORIES_OSM_DISPONIBLES]

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

# Titres des blocs (expanders) en plus grand pour bien les différencier du reste du texte.
st.markdown(
    """
    <style>
    [data-testid="stExpander"] summary p {
        font-size: 1.2rem;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True,
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
# 1b. Constantes & helpers
# ─────────────────────────────────────────────

from src.telecharger_intersections import (
    generer_combinaisons_voies,
    filtrer_par_combinaisons_voies,
    TYPES_VOIES_COMBO,
)

# Toutes les combinaisons proposées dans l'interface (Rue/Rue, Rue/Avenue, ...)
COMBINAISONS_VOIES = generer_combinaisons_voies(TYPES_VOIES_COMBO)

# Dossier où telecharger_intersections.py sauvegarde les GeoJSON filtrés
INTERSECTIONS_DIR = Path("intersections")


def _normaliser_ville(texte: str) -> str:
    # Traite tirets et espaces comme identiques pour comparer les noms de villes
    return texte.lower().replace("-", " ").replace("_", " ")


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

    Contrairement aux scripts CLI (main.py / main_mixte.py), l'interface
    n'écrit pas de PM_{ville}.xlsx persistant par ville (les lieux sont
    regénérés à la volée dans data/raw/lieux_upload.xlsx à chaque run) :
    le suivi des villes se fait donc via les dossiers fiches_equipes,
    nommés "{ville}_{horodatage}" par export_final_equipes().
    """
    import os
    dossier_images = base_dir / "data" / "raw" / "images_pp"
    dossier_fiches = base_dir / "data" / "output" / "fiches_equipes"

    if not dossier_fiches.exists():
        return

    # Regroupe les dossiers par ville normalisée, en retenant la génération
    # la plus récente de chacune comme référence pour le tri par ancienneté.
    par_ville = {}
    for dossier in dossier_fiches.iterdir():
        if not dossier.is_dir():
            continue
        ville_brute = dossier.name.rsplit("_", 2)[0]  # retire "_YYYYMMDD_HHMMSS"
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


def chemin_geojson_commune(code_insee: str) -> Path:
    """Chemin du fichier GeoJSON local pour un code INSEE donné."""
    return INTERSECTIONS_DIR / f"intersections_{code_insee}.geojson"


def sauvegarder_index(ville: str, chemin: Path):
    import json
    index_path = INTERSECTIONS_DIR / "index.json"
    index = {}
    if index_path.exists():
        with open(index_path) as f:
            index = json.load(f)
    index[ville.lower().strip()] = str(chemin)
    with open(index_path, "w") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def trouver_geojson_existant(ville: str) -> Path | None:
    import json
    ville_norm = ville.lower().strip()
    index_path = INTERSECTIONS_DIR / "index.json"

    # Priorité 1 : index.json (survit au refresh, O(1))
    if index_path.exists():
        with open(index_path) as f:
            index = json.load(f)
        chemin = index.get(ville_norm)
        if chemin:
            p = Path(chemin)
            if p.exists():
                return p
            else:
                # Fichier supprimé → nettoyer l'index
                del index[ville_norm]
                with open(index_path, "w") as f:
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
        from src.identification_PM import get_code_insee_api, get_equipements_gouv
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
    Même gabarit que le filtre "combinaisons de types de voies" plus haut,
    pour une expérience cohérente dans toute l'appli.

    labels_preselectionnes : labels cochés par défaut au premier affichage.
                              None = tous cochés par défaut.

    REPONSE : liste des labels cochés.
    """
    st.markdown(f"**{titre}**")

    valeurs_par_defaut = set(labels if labels_preselectionnes is None else labels_preselectionnes)

    col_sel_all, col_desel_all, _col_spacer = st.columns([1, 1, 3])
    with col_sel_all:
        if st.button("Tout sélectionner", key=f"{cle_prefixe}_select_all"):
            for lbl in labels:
                st.session_state[f"chk_{cle_prefixe}_{lbl}"] = True
            st.rerun()
    with col_desel_all:
        if st.button("Tout désélectionner", key=f"{cle_prefixe}_desel_all"):
            for lbl in labels:
                st.session_state[f"chk_{cle_prefixe}_{lbl}"] = False
            st.rerun()

    cols = st.columns(3)
    labels_choisis = []
    for i, lbl in enumerate(labels):
        with cols[i % 3]:
            if st.checkbox(lbl, value=(lbl in valeurs_par_defaut), key=f"chk_{cle_prefixe}_{lbl}"):
                labels_choisis.append(lbl)

    return labels_choisis


# ─────────────────────────────────────────────
# 2. Barre latérale — Paramètres
# ─────────────────────────────────────────────
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3448/3448614.png", width=60)
    st.title("DEFIACCESS")
    st.caption("Générateur de feuilles terrain accessibilité")
    st.divider()

    # --- Sélecteur de commune ---
    commune_names = list(yaml_configs.keys())
    commune_choice = st.selectbox(
        "Commune",
        options=["— Saisie manuelle —"] + commune_names,
        help="Sélectionnez une commune pré-configurée ou saisissez les paramètres manuellement.",
    )

    if commune_choice != "— Saisie manuelle —":
        cfg = yaml_configs[commune_choice]
    else:
        cfg = {}

    commune_str = st.text_input(
        "Nom de la commune",
        value=cfg.get("commune", ""),
        placeholder="ex. Garches, Hauts-de-Seine",
        help="Ce nom sert au filtrage des intersections ET à la génération automatique des lieux.",
    )

    st.divider()

    # --- Point de rendez-vous avec détection automatique de la mairie ---
    st.subheader("Point de rendez-vous")

    detect_mairie_btn = st.button(
        "📍 Utiliser la mairie comme point de RDV",
        disabled=not commune_str.strip(),
        help="Récupère automatiquement les coordonnées de la mairie via l'API officielle.",
        use_container_width=True,
    )

    if detect_mairie_btn and commune_str.strip():
        with st.spinner("Recherche de la mairie…"):
            _lat_m, _lon_m = recuperer_coords_mairie(commune_str)
        if _lat_m is not None:
            st.session_state["mairie_lat"] = _lat_m
            st.session_state["mairie_lon"] = _lon_m

            # AJOUT ICI : Mettre à jour directement l'état des inputs numériques
            st.session_state["input_lat"] = _lat_m
            st.session_state["input_lon"] = _lon_m

            st.success(f"Mairie trouvée : {_lat_m:.6f}, {_lon_m:.6f}")

            # Forcer le re-calcul visuel de la page
            st.rerun()
        else:
            st.warning("Mairie introuvable — saisissez les coordonnées manuellement.")

    _default_lat = st.session_state.get("mairie_lat", float(cfg.get("meetup_lat", 48.8566)))
    _default_lon = st.session_state.get("mairie_lon", float(cfg.get("meetup_long", 2.3522)))

    col_lat, col_lon = st.columns(2)
    meetup_lat = col_lat.number_input("Latitude",  value=_default_lat, format="%.6f", key="input_lat")
    meetup_lon = col_lon.number_input("Longitude", value=_default_lon, format="%.6f", key="input_lon")
    st.caption("Modifiez les valeurs ci-dessus pour ajuster le point de RDV.")

    st.divider()
    st.caption("v1.2 — DEFIACCESS © 2025")


# ─────────────────────────────────────────────
# 1c. Titre et explication du pipeline
# ─────────────────────────────────────────────
st.title("|DF| DEFIACCESS — Générateur de feuilles terrain accessibilité")
st.markdown(
    """
Cette application prépare automatiquement les tournées terrain d'évaluation de
l'accessibilité PMR d'une commune. Réglez les paramètres dans la barre latérale,
puis suivez les 4 étapes ci-dessous :

1. **Intersections** — téléchargement automatique des croisements de rues de la commune, avec filtre par types de voies.
2. **Lieux d'intérêt (PM)** — recherche des écoles, de la mairie, des établissements de santé, commerces, etc. via les sources officielles et OpenStreetMap.
3. **Passages piétons** — détection des passages piétons proches des intersections (OpenStreetMap, accidents corporels ou IA).
4. **Fiches équipes** — filtrage des intersections autour des lieux d'intérêt, répartition en équipes, calcul des itinéraires et export des feuilles terrain Excel prêtes à imprimer.
"""
)
st.divider()


# ─────────────────────────────────────────────────────────────────────────────────────────
# 2a. Intersections — automatique par défaut, fichier personnalisé en option repliée
# ─────────────────────────────────────────────────────────────────────────────────────────
 
with st.expander("**Étape 1 — 🗂️ Intersections**", expanded=True):
 
    st.markdown("**Objectif :** récupérer les intersections de la commune — automatique, rien à faire.")

    if not commune_str.strip():
        st.info("Saisissez d'abord le nom de la commune dans la barre latérale.")
    else:
        ville_inter = commune_str.split(",")[0].strip()

        # ── Option avancée, repliée : importer son propre fichier ────────────────────────
        with st.expander("⚙️ Utiliser un fichier personnalisé (avancé)", expanded=False):
            fichier_perso = st.file_uploader(
                "Votre fichier d'intersections (.xlsx, .csv ou .geojson)",
                type=["xlsx", "csv", "geojson"],
                key="uploader_intersections_manuel",
            )
            if fichier_perso is not None:
                st.session_state["inter_geojson_path"] = fichier_perso
                st.session_state["is_fichier_perso"] = True
                # Vider le cache aperçu si le fichier change
                if st.session_state.get("last_uploaded_name") != fichier_perso.name:
                    st.session_state.pop("inter_df_preview", None)
                    st.session_state["last_uploaded_name"] = fichier_perso.name
            elif st.session_state.get("is_fichier_perso"):
                # L'utilisateur avait un fichier personnalisé et vient de le retirer
                # (bouton "x" du widget) -> on revient au mode automatique.
                st.session_state.pop("inter_geojson_path", None)
                st.session_state.pop("inter_df_preview", None)
                st.session_state.pop("is_fichier_perso", None)
                st.session_state.pop("last_uploaded_name", None)
                st.rerun()

        # ── Mode automatique (par défaut) ─────────────────────────────────────────────────
        if not st.session_state.get("is_fichier_perso"):
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
                # Un téléchargement a déjà été tenté et a échoué pour cette ville : on ne
                # relance pas automatiquement (éviterait de marteler l'API à chaque rerun).
                st.error(f"Intersections introuvables pour '{ville_inter}'. Vérifiez l'orthographe de la commune.")
                if st.button("Réessayer", key="btn_retry_inter"):
                    st.session_state.pop("intersections_auto_echec", None)
                    st.session_state.pop("intersections_auto_ville", None)
                    st.rerun()

            elif st.session_state.get("intersections_auto_ville") != ville_inter:
                # Première fois pour cette ville dans la session -> téléchargement automatique
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
                        fichiers = telecharger_intersections_ville(ville_inter, departements_preresolus=None)

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
        else:
            _nom_perso = getattr(st.session_state.get("inter_geojson_path"), "name", "")
            st.info(f"📁 Fichier personnalisé utilisé : `{_nom_perso}`")

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
                    st.session_state.pop("inter_df_preview", None)
                    st.rerun()
            with col_desel_all:
                if st.button("Tout désélectionner", key="combos_desel_all"):
                    for _a, _b in COMBINAISONS_VOIES:
                        st.session_state[f"chk_combo_{_a}_{_b}"] = False
                    st.session_state.pop("inter_df_preview", None)
                    st.rerun()

            # Répartition en blocs continus (pas en tourniquet) pour que chaque colonne
            # regroupe les combinaisons d'un même type de voie de départ
            # (ex: colonne 1 = toutes les combinaisons "Rue / ..."), simple question d'affichage.
            import math
            cols_combo = st.columns(3)
            taille_bloc = math.ceil(len(COMBINAISONS_VOIES) / 3)
            combos_selectionnes = []
            for i, (type_a, type_b) in enumerate(COMBINAISONS_VOIES):
                with cols_combo[i // taille_bloc]:
                    if st.checkbox(
                        f"{type_a} / {type_b}",
                        value=False,
                        key=f"chk_combo_{type_a}_{type_b}",
                    ):
                        combos_selectionnes.append((type_a, type_b))
            st.session_state["combos_selectionnes"] = combos_selectionnes

            # Invalide l'aperçu mis en cache si la sélection de combinaisons a changé
            # depuis le dernier calcul — sinon l'aperçu ET le téléchargement CSV restent
            # périmés quand on coche/décoche une case individuellement (sans passer par
            # les boutons "Tout sélectionner"/"Tout désélectionner", qui invalidaient déjà).
            _signature_combos = tuple(sorted(combos_selectionnes))
            if st.session_state.get("combos_signature_preview") != _signature_combos:
                st.session_state.pop("inter_df_preview", None)
                st.session_state["combos_signature_preview"] = _signature_combos

            # ── Aperçu ───────────────────────────────────────────────────────────────────
            _source_fichier = st.session_state["inter_geojson_path"]
            _est_perso = st.session_state.get("is_fichier_perso", False)

            if "inter_df_preview" not in st.session_state:
                try:
                    import pandas as pd

                    if _est_perso:
                        _nom = getattr(_source_fichier, "name", "")
                        if _nom.endswith(".csv"):
                            _df_inter_prev = pd.read_csv(_source_fichier)
                        elif _nom.endswith(".geojson"):
                            from src.telecharger_intersections import charger_en_dataframe_sans_input
                            _df_inter_prev = charger_en_dataframe_sans_input(_source_fichier, types_voies=[])
                        else:
                            _df_inter_prev = pd.read_excel(_source_fichier)

                        # Filtrer par combinaisons de voies si la colonne existe
                        if "intersection" in _df_inter_prev.columns and combos_selectionnes:
                            _df_inter_prev = filtrer_par_combinaisons_voies(_df_inter_prev, combos_selectionnes)

                    else:
                        from src.telecharger_intersections import charger_en_dataframe_sans_input
                        _df_inter_prev = charger_en_dataframe_sans_input(_source_fichier, types_voies=[])
                        if combos_selectionnes:
                            _df_inter_prev = filtrer_par_combinaisons_voies(_df_inter_prev, combos_selectionnes)

                    st.session_state["inter_df_preview"] = _df_inter_prev

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

# ─────────────────────────────────────────────────────────────────────────────────────────
# 2b. Génération des lieux via identification_PM (Avec détection et sauvegarde locale)
# ─────────────────────────────────────────────────────────────────────────────────────────

# On crée un bloc repliable (un "accordéon") dans l'interface pour la gestion des lieux (PM).
# "expanded=False" signifie que par défaut, ce bloc est affiché fermé pour ne pas encombrer l'écran.
with st.expander("**Étape 2 — 📍 Générer le fichier des lieux Importants (PM, sous format xlsx)**", expanded=False):
    
    # On affiche un petit texte d'explication pour guider l'utilisateur sur le rôle de cette zone.
    st.markdown(
        "**Objectif :** récupérer automatiquement les points d'intérêt de la commune "
        "(écoles, mairie, supermarchés, pharmacies…) depuis les sources "
        "officielles et OpenStreetMap."
    )

    radius_km = st.slider(
        "Veuillez choisir le rayon autour des PM (km)",
        min_value=0.05, max_value=1.0,
        value=float(cfg.get("radius_km", 0.2)), step=0.05,
        help="Seules les intersections dans ce rayon autour d'un point d'intérêt sont conservées.",
    )

    # VÉRIFICATION : On contrôle si l'utilisateur a bien tapé un nom de commune dans la barre latérale.
    # ".strip()" retire les espaces inutiles au début et à la fin (ex: " Paris " devient "Paris").
    if not commune_str.strip():
        # Si le champ est vide, on affiche un message d'information bleu et on bloque la suite.
        st.info("Saisissez d'abord le nom de la commune dans la barre latérale.")

    else:
        # Si une commune est saisie, on extrait uniquement le nom de la ville avant la première virgule.
        # Exemple : "Garches, Hauts-de-Seine" devient "Garches".
        ville_cible = commune_str.split(",")[0].strip()

        # On affiche à l'écran la commune qui va être analysée.
        st.write(f"Commune ciblée : **{ville_cible}**")

        # ── Filtres organisés par thème : boutons "Tout cocher"/"Tout décocher" +
        # cases fines en dessous (même principe que le menu console de main_filtre.py).
        # Toujours affichés, que des lieux existent déjà ou non — les choix ne sont
        # utilisés qu'au clic sur "⚡ Générer les feuilles terrain" plus bas. ─────────
        st.write("📋 **Sélectionnez les types de lieux à récupérer :**")
        st.caption(
            "La mairie est toujours incluse. Laissez tout coché pour ne rien filtrer. "
            "Ces choix sont pris en compte au clic sur « ⚡ Générer les feuilles terrain » plus bas."
        )

        categories_sante_choisies  = bloc_filtre_theme("🏥 Lieux de santé", "sante", LABELS_SANTE)
        st.write("---")
        categories_ecoles_choisies = bloc_filtre_theme("🏫 Établissements scolaires", "ecoles", LABELS_ECOLES)
        st.write("---")
        categories_osm_labels_choisies = bloc_filtre_theme(
            "📍 Autres lieux", "osm", LABELS_OSM, labels_preselectionnes=LABELS_OSM_PRESELECTIONNES
        )
        # Reconvertit les labels OSM cochés vers le format {type, osm_filters} attendu par le pipeline
        categories_osm_choisies = [
            {"type": c["type"], "osm_filters": c["osm_filters"]}
            for c in CATEGORIES_OSM_DISPONIBLES
            if c["label"] in categories_osm_labels_choisies
        ]

        # ── Invalidation du cache si les filtres ont changé depuis la dernière
        # génération des lieux pour cette commune (bouton local ou pipeline final).
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

        # Mémorisation en session_state : le pipeline principal (section 6, plus bas dans
        # la page) lira ces choix au clic sur "⚡ Générer les feuilles terrain".
        st.session_state["pm_categories_sante_choisies"] = categories_sante_choisies
        st.session_state["pm_categories_ecoles_choisies"] = categories_ecoles_choisies
        st.session_state["pm_categories_osm_labels_choisies"] = categories_osm_labels_choisies
        st.session_state["pm_categories_osm_choisies"] = categories_osm_choisies

        st.write("---")

        # ── Bouton pour générer les PM directement depuis ce bloc (aperçu immédiat,
        # sans attendre le pipeline complet). Si utilisé, le résultat est réutilisé
        # tel quel par "⚡ Générer les feuilles terrain" plus bas (pas de double appel).
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
                _buf_pm_local = io.BytesIO()
                df_pm_local.to_excel(_buf_pm_local, index=False)
                _buf_pm_local.seek(0)
                st.session_state["pm_buffer"] = _buf_pm_local.getvalue()
                st.toast(f"{len(df_pm_local)} lieux trouvés pour {ville_cible}.", icon="✅", duration="long")
                st.rerun()

    # ── AFFICHAGE DE L'APERÇU (rempli par ce bouton ou par le pipeline principal) ──────────
    # Si le tableau de données existe en mémoire et qu'il correspond bien à la commune sélectionnée :
    if "df_pm" in st.session_state and st.session_state.get("pm_commune") == commune_str.split(",")[0].strip():
        df_pm_disp = st.session_state["df_pm"]
        
        if not df_pm_disp.empty:
            # On affiche le nombre de lignes trouvées
            st.success(f"**{len(df_pm_disp)} lieux** trouvés pour {st.session_state.get('pm_commune')}.")
            st.caption(
                "Aperçu des lieux d'intérêt (PM) trouvés — ex. \"École Jean Moulin\" "
                "(type : école, source : data.education.gouv.fr) — utilisés ensuite pour ne "
                "garder que les intersections situées à proximité d'un de ces lieux."
            )
            # On affiche le tableau interactif (les 30 premières lignes) style Excel
            with st.expander(f"📋 Voir le tableau ({len(df_pm_disp):,} lieux)", expanded=False):
                st.dataframe(df_pm_disp.head(30), use_container_width=True)

            # Si le fichier binaire est prêt en mémoire, on affiche le bouton pour exporter l'Excel manuellement (optionnel)
            if "pm_buffer" in st.session_state:
                st.download_button(
                    label="📥 Télécharger lieux.xlsx (Copie de sauvegarde)",
                    data=st.session_state["pm_buffer"],
                    file_name=f"lieux_{st.session_state.get('pm_commune').lower().replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )


# ─────────────────────────────────────────────
# 2c. Génération des passages piétons (PP)
# ─────────────────────────────────────────────
with st.expander("**Étape 3 — 🚶 Générer les passages piétons**", expanded=False):
    st.markdown(
        "**Objectif :** identifier les passages piétons autour des intersections selon la méthode choisie."
    )

    methode_pp = st.radio(
        "Méthode de détection",
        options=["OSM (Overpass)", "Accidents (CSV)", "IA (YOLO — best.pt requis)"],
        horizontal=True,
    )

    accidents_file = None
    if methode_pp == "Accidents (CSV)":
        st.markdown("Uploadez le fichier CSV d'accidents corporels :")
        accidents_file = st.file_uploader(
            "CSV accidents",
            type=["csv"],
            key="upload_accidents_csv",
            help="Téléchargeable sur data.gouv.fr — accidents corporels de la circulation.",
        )
        if accidents_file is None:
            st.warning("⚠️ Aucun fichier CSV chargé.")

    if methode_pp == "IA (YOLO — best.pt requis)":
        import os
        if os.path.exists(os.path.join("models", "best.pt")):
            st.success("✅ Modèle `models/best.pt` détecté.")
        else:
            st.error("❌ `models/best.pt` introuvable — placez votre modèle dans `models/`.")

    col_pp_gen, col_pp_reset = st.columns([3, 1])
    with col_pp_gen:
        generer_pp_btn = st.button(
            "Générer les PP",
            key="btn_generer_pp",
            type="secondary",
            use_container_width=True,
            disabled=not commune_str.strip(),
        )
    with col_pp_reset:
        reset_pp_btn = st.button("Réinitialiser", key="btn_reset_pp", use_container_width=True)

    if reset_pp_btn:
        for cle in ("df_pp", "pp_methode", "pp_commune", "pp_ia_dossier"):
            st.session_state.pop(cle, None)
        st.rerun()

    if generer_pp_btn and commune_str.strip():
        ville_pp = commune_str.split(",")[0].strip()

        if methode_pp == "OSM (Overpass)":
            from src.identification_PP import get_osm_area_id, telecharger_passages_par_zone
            with st.spinner(f"Interrogation d'OpenStreetMap pour **{ville_pp}**…"):
                id_zone = get_osm_area_id(ville_pp)
                if id_zone:
                    df_pp = telecharger_passages_par_zone(id_zone, rayon_metres=25)
                    if not df_pp.empty:
                        st.session_state["df_pp"]      = df_pp
                        st.session_state["pp_methode"] = "OSM"
                        st.session_state["pp_commune"] = ville_pp
                        st.toast(f"{len(df_pp)} intersections analysées via OSM.", icon="✅", duration="long")
                    else:
                        st.warning("Aucun passage piéton trouvé via OSM.")
                        st.toast("Aucun passage piéton trouvé via OSM.", icon="⚠️", duration="long")
                else:
                    st.error(f"Zone OSM introuvable pour '{ville_pp}'.")
                    st.toast(f"Zone OSM introuvable pour '{ville_pp}'.", icon="❌", duration="long")

        elif methode_pp == "Accidents (CSV)":
            if accidents_file is None:
                st.error("Uploadez d'abord le fichier CSV d'accidents.")
                st.toast("Uploadez d'abord le fichier CSV d'accidents.", icon="⚠️", duration="long")
            else:
                from src.identification_PP import charger_accidents
                import tempfile, os
                with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                    tmp.write(accidents_file.read())
                    tmp_path = tmp.name
                with st.spinner(f"Filtrage des accidents pour **{ville_pp}**…"):
                    try:
                        df_pp = charger_accidents(tmp_path, ville_pp)
                        os.unlink(tmp_path)
                        if not df_pp.empty:
                            st.session_state["df_pp"]      = df_pp
                            st.session_state["pp_methode"] = "Accidents"
                            st.session_state["pp_commune"] = ville_pp
                            st.toast(f"{len(df_pp)} accidents sur passages piétons trouvés.", icon="✅", duration="long")
                        else:
                            st.warning(f"Aucun accident sur PP trouvé pour '{ville_pp}'.")
                            st.toast(f"Aucun accident sur PP trouvé pour '{ville_pp}'.", icon="⚠️", duration="long")
                    except Exception as e:
                        os.unlink(tmp_path)
                        st.error(f"Erreur CSV : {e}")
                        st.toast(f"Erreur CSV : {e}", icon="❌", duration="long")

        elif methode_pp == "IA (YOLO — best.pt requis)":
            import os
            _inter_prete = bool(
                st.session_state.get("inter_geojson_path")
                and Path(st.session_state["inter_geojson_path"]).exists()
            )
            _pm_prete = (
                "df_pm" in st.session_state
                and st.session_state.get("pm_commune") == ville_pp
            )

            if not os.path.exists(os.path.join("models", "best.pt")):
                st.error("Modèle introuvable.")
                st.toast("Modèle models/best.pt introuvable.", icon="❌", duration="long")
            elif not _inter_prete:
                st.error(
                    "Générez d'abord les intersections (bloc « 🗂️ Intersections » ci-dessus) "
                    "avant de lancer la détection IA."
                )
                st.toast("Intersections manquantes pour lancer l'IA.", icon="⚠️", duration="long")
            elif not _pm_prete:
                st.error(
                    "Générez d'abord les lieux d'intérêt (bloc « 📍 Générer le fichier des lieux "
                    "Importants ») pour cette commune avant de lancer la détection IA."
                )
                st.toast("Lieux d'intérêt (PM) manquants pour lancer l'IA.", icon="⚠️", duration="long")
            else:
                from src.telecharger_intersections import charger_en_dataframe_sans_input
                from src.IA_PP import analyser_toutes_intersections
                from datetime import datetime
                import re

                with st.spinner(f"Préparation de l'analyse IA pour **{ville_pp}**…"):
                    _combos_ia = st.session_state.get("combos_selectionnes", [])
                    df_inter_ia = charger_en_dataframe_sans_input(
                        st.session_state["inter_geojson_path"], types_voies=[]
                    )
                    if _combos_ia:
                        df_inter_ia = filtrer_par_combinaisons_voies(df_inter_ia, _combos_ia)

                    df_inter_ia = filtre_distance(st.session_state["df_pm"], df_inter_ia, rayon_km=radius_km)
                    df_inter_ia = fusion_croisement(df_inter_ia, threshold_km=0.03)

                if df_inter_ia.empty:
                    st.warning("Aucune intersection après filtrage géographique — IA non lancée.")
                    st.toast("Aucune intersection à analyser après filtrage.", icon="⚠️", duration="long")
                else:
                    dossier_images_ia = str(
                        Path("data/raw/images_pp")
                        / f"images_{ville_pp}_{datetime.now().strftime('%d-%m-%Y_%Hh%M')}"
                    )

                    _total_ia = len(df_inter_ia)
                    _progress_ia = st.progress(0, text=f"Détection IA — 0/{_total_ia} passages analysés…")
                    _pattern_ia = re.compile(r"\[(\d+)/(\d+)\]")

                    class StreamlitLoggerIA(io.StringIO):
                        def write(self, texte):
                            super().write(texte)
                            match = _pattern_ia.search(texte)
                            if match:
                                _i_ia, _tot_ia = int(match.group(1)), int(match.group(2))
                                _progress_ia.progress(
                                    min(_i_ia / _tot_ia, 1.0),
                                    text=f"Détection IA — {_i_ia}/{_tot_ia} passages analysés…",
                                )
                            return len(texte)

                    logs_ia = StreamlitLoggerIA()
                    with contextlib.redirect_stdout(logs_ia):
                        df_pp = analyser_toutes_intersections(
                            df_inter_ia, col_lat="latitude", col_lon="longitude",
                            dossier_images=dossier_images_ia,
                        )
                    _progress_ia.progress(1.0, text=f"Détection IA terminée — {_total_ia}/{_total_ia} passages analysés.")

                    st.session_state["df_pp"]         = df_pp
                    st.session_state["pp_methode"]    = "IA"
                    st.session_state["pp_commune"]    = ville_pp
                    st.session_state["pp_ia_dossier"] = dossier_images_ia
                    st.toast(f"Analyse IA terminée pour {len(df_pp)} intersections.", icon="✅", duration="long")

    if "pp_methode" in st.session_state:
        _m = st.session_state["pp_methode"]
        _c = st.session_state.get("pp_commune", "")

        if _m == "IA" and "df_pp" in st.session_state:
            _df_pp_r = st.session_state["df_pp"]
            st.success(f"✅ **{len(_df_pp_r)} intersections analysées** via IA pour {_c}.")
            with st.expander(f"📋 Voir le tableau ({len(_df_pp_r):,} lignes)", expanded=False):
                st.dataframe(_df_pp_r.head(15), use_container_width=True)
                st.caption(f"{len(_df_pp_r)} lignes au total")

            _dossier_ia = st.session_state.get("pp_ia_dossier")
            if _dossier_ia and Path(_dossier_ia).is_dir():
                _zip_buf_ia = io.BytesIO()
                with zipfile.ZipFile(_zip_buf_ia, "w", zipfile.ZIP_DEFLATED) as zf:
                    for _f in Path(_dossier_ia).iterdir():
                        if _f.is_file():
                            zf.write(_f, arcname=_f.name)
                _zip_buf_ia.seek(0)
                st.download_button(
                    label="📥 Télécharger l'analyse des passages piétons",
                    data=_zip_buf_ia,
                    file_name=f"images_pp_{_c.lower().replace(' ', '_')}.zip",
                    mime="application/zip",
                    key="dl_pp_ia_zip",
                    use_container_width=True,
                )

        elif "df_pp" in st.session_state:
            _df_pp_r = st.session_state["df_pp"]
            st.success(f"✅ **{len(_df_pp_r)} entrées PP** via {_m} pour {_c}.")
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


# ─────────────────────────────────────────────
# 3. Génération des fiches équipes
# ─────────────────────────────────────────────
with st.expander("**Étape 4 — 📄 Générer les fiches équipes**", expanded=False):
    st.markdown(
        "**Objectif :** combiner intersections, lieux d'intérêt et passages piétons "
        "pour répartir les équipes et générer les feuilles terrain prêtes à imprimer."
    )

    n_teams = st.slider(
        "Nombre d'équipes",
        min_value=1, max_value=20,
        value=int(cfg.get("n_teams", 5)), step=1,
        help="Les intersections seront réparties en N groupes géographiques.",
    )

    # ── État des sources (auto par défaut) ──────────────────────────────────
    _inter_geojson_path = st.session_state.get("inter_geojson_path")

    col_status_inter, col_status_lieux = st.columns(2)

    with col_status_inter:
        if _inter_geojson_path and Path(_inter_geojson_path).exists():
            st.success(
                f"✅ Intersections chargées automatiquement : "
                f"`{Path(_inter_geojson_path).name}`"
            )
        else:
            st.info(
                "Aucune intersection auto-chargée — importez un fichier ci-dessous ou utilisez "
                "le bloc « Étape 1 — 🗂️ Intersections » ci-dessus."
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
                "terrain », avec les filtres cochés dans « Étape 2 — 📍 Générer le fichier des "
                "lieux Importants » ci-dessus."
            )

    # ── Importer mes propres fichiers (optionnel, remplace l'auto) ─────────
    with st.expander("📂 Importer mes propres fichiers (avancé)", expanded=False):
        col_upload_inter, col_upload_lieux = st.columns(2)

        with col_upload_inter:
            intersections_file = st.file_uploader(
                "Votre fichier intersections.csv",
                type=["csv"],
                key="uploader_intersections_manuel_e4",
                help="Remplace le téléchargement automatique si un fichier est fourni ici.",
            )

        with col_upload_lieux:
            lieux_file = st.file_uploader(
                "Votre fichier lieux.xlsx (points d'intérêt)",
                type=["xlsx"],
                key="uploader_lieux_manuel",
                help="Remplace les lieux déjà générés si un fichier est fourni ici.",
            )

    # ── Résolution source intersections ─────────────────────────────────────
    # Priorité : CSV uploadé manuellement > GeoJSON téléchargé auto
    if intersections_file is not None:
        intersections_source = "csv"
    elif _inter_geojson_path and Path(_inter_geojson_path).exists():
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


    # ─────────────────────────────────────────────
    # 4. Prévisualisation
    # ─────────────────────────────────────────────
    _has_inter = intersections_source is not None
    _has_lieux = lieux_source is not None
    _has_pp    = "df_pp" in st.session_state

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
                _df_pp_p = st.session_state["df_pp"]
                _pp_methode_p = st.session_state.get("pp_methode", "")
                _pp_commune_p = st.session_state.get("pp_commune", "")
                with st.expander(f"📋 Voir le tableau ({len(_df_pp_p):,} lignes)", expanded=False):
                    st.dataframe(_df_pp_p.head(20), use_container_width=True)
                    st.caption(f"{len(_df_pp_p):,} lignes · méthode {_pp_methode_p} · {_pp_commune_p}")


    @st.dialog("🎉 Feuilles terrain générées !")
    def _popup_resultat_final(nb_feuilles: int, n_equipes: int, ville: str):
        st.success(f"**{nb_feuilles} feuille(s)** générée(s) pour **{n_equipes} équipe(s)** — {ville}.")
        st.caption("La carte, les statistiques par équipe et le téléchargement ZIP sont juste en dessous, sur la page.")
        if st.button("Fermer", use_container_width=True):
            st.rerun()


    # ─────────────────────────────────────────────
    # 5. Bouton Générer
    # ─────────────────────────────────────────────
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
            "filtres cochés dans « 📍 Générer le fichier des lieux Importants (PM, sous format xlsx) »."
        )

    generate_btn = st.button(
        "⚡ Générer les feuilles terrain",
        disabled=not ready,
        type="primary",
        use_container_width=True,
    )


    # ─────────────────────────────────────────────
    # 6. Pipeline principal
    # ─────────────────────────────────────────────
    if generate_btn and ready:
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
                # Charger depuis le GeoJSON local sans interaction console
                from src.telecharger_intersections import charger_en_dataframe_sans_input
                _combos_pipeline = st.session_state.get("combos_selectionnes", [])
                df = charger_en_dataframe_sans_input(_inter_geojson_path, types_voies=[])
                if _combos_pipeline:
                    avant = len(df)
                    df = filtrer_par_combinaisons_voies(df, _combos_pipeline)
                    status.info(f"**Étape 1/6** — Filtre voies : {avant} → {len(df)} intersections.")
            else:
                # Fallback CSV uploadé manuellement
                intersections_path = Path("data/raw/intersections_upload.csv")
                intersections_path.parent.mkdir(parents=True, exist_ok=True)
                intersections_path.write_bytes(intersections_file.read())
                df = charger_intersections(str(intersections_path), commune_str)

                # Filtre combinaisons de voies sur le CSV aussi
                _combos_pipeline = st.session_state.get("combos_selectionnes", [])
                if _combos_pipeline:
                    avant = len(df)
                    df = filtrer_par_combinaisons_voies(df, _combos_pipeline)
                    status.info(f"**Étape 1/6** — Filtre voies : {avant} → {len(df)} intersections.")

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
                # Déjà généré via le bouton "🏗️ Générer les PM" (ou un run précédent) pour
                # cette même commune -> on réutilise directement, pas besoin de refaire les appels API.
                status.info("**Étape 2/6** — Réutilisation des lieux déjà générés…")
                progress.progress(30)
                lieux_path.write_bytes(st.session_state["pm_buffer"])
            else:
                # Pas de fichier fourni manuellement, ni de PM déjà généré pour cette commune
                # -> génération automatique avec les filtres cochés dans le bloc "📍 Générer
                # le fichier des lieux Importants (PM, sous format xlsx)" plus haut.
                _ville_pm = _ville_actuelle
                status.info(f"**Étape 2/6** — Génération des points d'intérêt pour **{_ville_pm}**… (1-2 min)")
                progress.progress(30)

                _cs_choisies  = st.session_state.get("pm_categories_sante_choisies", LABELS_SANTE)
                _ce_choisies  = st.session_state.get("pm_categories_ecoles_choisies", LABELS_ECOLES)
                _co_labels    = st.session_state.get("pm_categories_osm_labels_choisies", LABELS_OSM)
                _co_choisies  = st.session_state.get("pm_categories_osm_choisies")

                # "Tout coché" (cas par défaut) -> None, pour garder le filet de sécurité
                # OSM en cas d'échec réel de FINESS. Toute sélection partielle (y compris
                # "aucune case cochée") est respectée telle quelle.
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
                        "Cochez plus de catégories dans « 📍 Générer le fichier des lieux Importants (PM, sous format xlsx) »."
                    )
                    st.toast(f"Aucun lieu trouvé pour {_ville_pm}.", icon="⚠️", duration="long")
                    st.stop()

                df_pm_genere.to_excel(lieux_path, index=False)

                # Mémorisation pour l'aperçu / téléchargement affichés dans le bloc
                # "📍 Générer le fichier des lieux Importants (PM, sous format xlsx)" plus haut sur la page.
                st.session_state["df_pm"]      = df_pm_genere
                st.session_state["pm_commune"] = _ville_pm
                st.session_state["pm_filters_signature"] = signature_filtres_pm(_cs_choisies, _ce_choisies, _co_labels)
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

            if _pp_methode == "IA":
                _df_pp_cache = st.session_state.get("df_pp")
                _ia_deja_faite = (
                    _df_pp_cache is not None
                    and st.session_state.get("pp_commune") == _ville_actuelle
                    and "intersection" in df.columns
                    and "intersection" in _df_pp_cache.columns
                    and set(df["intersection"]) == set(_df_pp_cache["intersection"])
                )
                if _ia_deja_faite:
                    status.info("**Étape 4/6** — Réutilisation de l'analyse IA déjà effectuée dans « 🚶 Générer les passages piétons »…")
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

            elif _pp_methode in ("OSM", "Accidents") and "df_pp" in st.session_state:
                from src.identification_PP import comparer_coordonnees
                df_pp_session = st.session_state["df_pp"]
                df = comparer_coordonnees(df_pp_session, df)
                if "nb_pp" in df.columns:
                    df["nb_traversees"] = df["nb_pp"]
                elif "nb_passages_pietons" in df.columns:
                    df["nb_traversees"] = df["nb_passages_pietons"]
                else:
                    df["nb_traversees"] = 0

            else:
                df["nb_traversees"] = np.random.randint(1, 5, size=len(df))
                status.info("**Étape 4/6** — Aucune méthode PP configurée, valeurs provisoires utilisées.")

            progress.progress(65)

            # ── Étape 5 — Clustering & routing ────────────────────────────
            status.info("**Étape 5/6** — Répartition par équipes et calcul des itinéraires…")
            progress.progress(75)
            df = assigner_equipes(df, n_equipes=n_teams, meetup_lat=meetup_lat, meetup_long=meetup_lon)
            teams_dict = route_toutes_equipes(df, meetup_lat, meetup_lon)

            # ── Étape 6 — Export XLSX ─────────────────────────────────────
            status.info("**Étape 6/6** — Génération des feuilles terrain XLSX…")
            progress.progress(90)
            output_files = export_final_equipes(teams_dict, str(output_dir), _ville_actuelle)

            # Nettoyage des anciennes villes (images_pp + fiches_equipes) une fois
            # la nouvelle génération terminée, pour ne pas accumuler indéfiniment.
            nettoyer_anciennes_villes_gui(Path(__file__).parent)

            progress.progress(100, text="Terminé ✅")
            status.success(f"**{len(output_files)} feuille(s) générée(s)** pour {n_teams} équipe(s).")

            # Mémorisation du résultat pour qu'il reste affiché (carte, stats, ZIP)
            # même après un rerun (ex: fermeture du popup de confirmation ci-dessous).
            st.session_state["final_teams_dict"]  = teams_dict
            st.session_state["final_pois"]        = pois
            st.session_state["final_output_files"] = output_files
            st.session_state["final_meetup"]      = (meetup_lat, meetup_lon)
            st.session_state["final_pp_methode"]  = _pp_methode
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

    # ─────────────────────────────────────────────
    # 7-9. Résultat de la dernière génération (persiste après un rerun,
    #      ex: fermeture du popup de confirmation) — carte, stats, ZIP.
    # ─────────────────────────────────────────────
    if "final_teams_dict" in st.session_state:
        import pandas as pd

        _teams_dict_f    = st.session_state["final_teams_dict"]
        _pois_f          = st.session_state["final_pois"]
        _output_files_f  = st.session_state["final_output_files"]
        _meetup_lat_f, _meetup_lon_f = st.session_state["final_meetup"]
        _pp_methode_f    = st.session_state.get("final_pp_methode")
        _ville_f         = st.session_state.get("final_ville", "")
        _n_teams_f       = st.session_state.get("final_n_teams", len(_teams_dict_f))

        st.divider()

        # ── Carte Folium ────────────────────────────────────────────
        st.subheader("🗺️ Carte des intersections par équipe")

        COLORS = [
            "red", "blue", "green", "purple", "orange",
            "darkred", "lightred", "beige", "darkblue", "darkgreen",
            "cadetblue", "pink", "lightblue", "lightgreen", "gray",
            "black", "lightgray", "white", "darkpurple", "salmon",
        ]

        m = folium.Map(location=[_meetup_lat_f, _meetup_lon_f], zoom_start=14, tiles="CartoDB positron")
        folium.Marker(
            location=[_meetup_lat_f, _meetup_lon_f],
            popup="<b>Point de rendez-vous</b>",
            icon=folium.Icon(color="black", icon="home", prefix="fa"),
        ).add_to(m)

        for _, poi in _pois_f.iterrows():
            _label_poi = str(poi.get("lieu", "POI"))
            folium.Marker(
                location=[poi["latitude"], poi["longitude"]],
                icon=folium.DivIcon(
                    icon_size=(14, 14),
                    icon_anchor=(7, 7),
                    html=(
                        '<div style="width:14px;height:14px;background-color:#FF6B35;'
                        'border:2px solid white;box-shadow:0 0 2px rgba(0,0,0,0.6);"></div>'
                    ),
                ),
                popup=folium.Popup(_label_poi, max_width=200),
                tooltip=_label_poi,
            ).add_to(m)

        for equipe_id, team_df in _teams_dict_f.items():
            color = COLORS[(equipe_id - 1) % len(COLORS)]
            for _, row in team_df.iterrows():
                nb_pp = int(row.get("nb_traversees", 0))
                popup_html = (
                    f"<b>Équipe {equipe_id}</b><br>"
                    f"Ordre : {int(row.get('ordre', 0))}<br>"
                    f"{row.get('intersection', '')}<br>"
                    f"Passages piétons : {nb_pp}"
                )
                folium.CircleMarker(
                    location=[row["latitude"], row["longitude"]],
                    radius=6, color=color, fill=True, fill_opacity=0.75,
                    popup=folium.Popup(popup_html, max_width=250),
                ).add_to(m)

        st_folium(m, width=None, height=500, returned_objects=[], key="carte_resultat_final")

        # ── Statistiques ────────────────────────────────────────────
        st.subheader("📊 Répartition par équipe")
        stats_rows = []
        for equipe_id, team_df in _teams_dict_f.items():
            stats_rows.append({
                "Équipe": f"Équipe {equipe_id}",
                "Intersections": len(team_df),
                "Passages piétons totaux": int(
                    team_df["nb_traversees"].sum() if "nb_traversees" in team_df.columns else 0
                ),
            })
        st.dataframe(pd.DataFrame(stats_rows), use_container_width=True, hide_index=True)

        _pp_label = {
            "OSM":       "OpenStreetMap (Overpass)",
            "Accidents": "Accidents corporels (CSV)",
            "IA":        "Détection IA YOLOv8",
            None:        "Valeurs provisoires",
        }.get(_pp_methode_f, "Inconnue")
        st.caption(f"Méthode passages piétons : {_pp_label}")

        # ── Téléchargement ZIP ──────────────────────────────────────
        st.subheader("📥 Téléchargement")
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath in _output_files_f:
                zf.write(fpath, arcname=Path(fpath).name)
        zip_buffer.seek(0)

        st.download_button(
            label=f"📦 Télécharger les {len(_output_files_f)} feuilles terrain (.zip)",
            data=zip_buffer,
            file_name=f"defiaccess_{_ville_f.lower().replace(' ', '_')}.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
            key="dl_zip_final",
        )
