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
import numpy as np
import io
import zipfile
import contextlib
import yaml
import streamlit as st
import plotly.graph_objects as go
from math import cos, radians, sin, pi
from pathlib import Path

from src.nettoyage import charger_intersections
from src.proximite import (
    charger_points,
    filtre_distance,
    fusion_croisement,
    assigner_equipes,
)
from src.routage import route_toutes_equipes2
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
from src.telecharger_intersections import (
    generer_combinaisons_voies,
    filtrer_par_combinaisons_voies,
    TYPES_VOIES_COMBO,
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
INTERSECTIONS_DIR = Path("intersections")


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

    commune_str = st.text_input(
        "Nom de la commune",
        value=st.session_state.get("commune_val", cfg.get("commune", "")),
        placeholder="ex. Garches, Hauts-de-Seine",
        help="Ce nom sert au filtrage des intersections ET à la génération automatique des lieux.",
        key="input_commune",
    )
    # Mémorisation dans une clé "normale" (non liée au widget) : la valeur d'un
    # widget disparaît de session_state dès qu'il n'est plus affiché (ex: en
    # naviguant vers une autre page) — cette copie, elle, survit au changement de page.
    st.session_state["commune_val"] = commune_str

    st.markdown("**Objectif :** récupérer les intersections de la commune — automatique, rien à faire.")

    if not commune_str.strip():
        st.info("Saisissez d'abord le nom de la commune ci-dessus.")
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
                if st.session_state.get("last_uploaded_name") != fichier_perso.name:
                    st.session_state.pop("inter_df_preview", None)
                    st.session_state["last_uploaded_name"] = fichier_perso.name
            elif st.session_state.get("is_fichier_perso"):
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
                st.error(f"Intersections introuvables pour '{ville_inter}'. Vérifiez l'orthographe de la commune.")
                if st.button("Réessayer", key="btn_retry_inter"):
                    st.session_state.pop("intersections_auto_echec", None)
                    st.session_state.pop("intersections_auto_ville", None)
                    st.rerun()

            elif st.session_state.get("intersections_auto_ville") != ville_inter:
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
            elif st.session_state.get("is_fichier_perso_pm"):
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

    _options_pp = ["OSM (Overpass)", "Accidents (CSV)", "IA (YOLO — best.pt requis)"]
    _methode_pp_persistee = st.session_state.get("methode_pp_val", _options_pp[0])
    methode_pp = st.radio(
        "Méthode de détection",
        options=_options_pp,
        index=_options_pp.index(_methode_pp_persistee),
        horizontal=True,
        key="input_methode_pp",
    )
    st.session_state["methode_pp_val"] = methode_pp

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

    inter_file_pp = None
    pm_file_pp = None
    pp_deja_fait_file = None
    if methode_pp == "IA (YOLO — best.pt requis)":
        import os
        if os.path.exists(os.path.join("models", "best.pt")):
            st.success("✅ Modèle `models/best.pt` détecté.")
        else:
            st.error("❌ `models/best.pt` introuvable — placez votre modèle dans `models/`.")

        with st.expander("⚙️ Utiliser mes propres fichiers (avancé)", expanded=False):
            st.caption(
                "La méthode IA a besoin de savoir où sont les intersections et les lieux "
                "d'intérêt. Importez-les ici pour analyser vos propres fichiers sans passer "
                "par les Étapes 1 et 2 — sinon les données déjà chargées/générées pour "
                "cette commune sont réutilisées automatiquement."
            )
            col_upload_inter_pp, col_upload_pm_pp = st.columns(2)
            with col_upload_inter_pp:
                inter_file_pp = st.file_uploader(
                    "Votre fichier intersections.csv",
                    type=["csv"],
                    key="uploader_inter_pp_e3",
                )
            with col_upload_pm_pp:
                pm_file_pp = st.file_uploader(
                    "Votre fichier lieux.xlsx",
                    type=["xlsx"],
                    key="uploader_pm_pp_e3",
                )

            st.divider()
            pp_deja_fait_file = st.file_uploader(
                "Votre fichier passages_pietons.csv déjà généré ou modifié (optionnel)",
                type=["csv"],
                key="uploader_pp_deja_fait_e3",
                help=(
                    "Pour réutiliser un résultat IA déjà obtenu (éventuellement corrigé à la "
                    "main) sans relancer la détection — 1 à 2 min économisées. Formats "
                    "acceptés : 'intersection'/'nb_traversees' (déjà agrégé) ou "
                    "'latitude'/'longitude' (points bruts)."
                ),
            )

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

            _inter_source_ia = inter_file_pp if inter_file_pp is not None else st.session_state.get("inter_geojson_path")
            _inter_prete = bool(
                _inter_source_ia
                and (
                    not _intersections_source_est_chemin(_inter_source_ia)
                    or Path(_inter_source_ia).exists()
                )
            )
            _pm_prete = bool(pm_file_pp is not None) or (
                "df_pm" in st.session_state
                and st.session_state.get("pm_commune") == ville_pp
            )

            if not os.path.exists(os.path.join("models", "best.pt")):
                st.error("Modèle introuvable.")
                st.toast("Modèle models/best.pt introuvable.", icon="❌", duration="long")
            elif not _inter_prete:
                st.error(
                    "Générez d'abord les intersections (Étape 1) avant de lancer la détection IA, "
                    "ou importez votre fichier intersections.csv ci-dessus."
                )
                st.toast("Intersections manquantes pour lancer l'IA.", icon="⚠️", duration="long")
            elif not _pm_prete:
                st.error(
                    "Générez d'abord les lieux d'intérêt (Étape 2) pour cette commune avant de "
                    "lancer la détection IA, ou importez votre fichier lieux.xlsx ci-dessus."
                )
                st.toast("Lieux d'intérêt (PM) manquants pour lancer l'IA.", icon="⚠️", duration="long")
            else:
                import pandas as pd
                from datetime import datetime

                with st.spinner(f"Préparation de l'analyse IA pour **{ville_pp}**…"):
                    _combos_ia = st.session_state.get("combos_selectionnes", [])
                    df_inter_ia = charger_intersections_quelconque(_inter_source_ia, _combos_ia)

                    pois_ia = pd.read_excel(pm_file_pp) if pm_file_pp is not None else st.session_state["df_pm"]

                    df_inter_ia = filtre_distance(pois_ia, df_inter_ia, rayon_km=radius_km)
                    df_inter_ia = fusion_croisement(df_inter_ia, threshold_km=0.03)

                if df_inter_ia.empty:
                    st.warning("Aucune intersection après filtrage géographique — IA non lancée.")
                    st.toast("Aucune intersection à analyser après filtrage.", icon="⚠️", duration="long")

                elif pp_deja_fait_file is not None:
                    # Raccourci : réutilise un résultat déjà généré (ou corrigé à la main)
                    # au lieu de relancer la détection IA (économise 1-2 min).
                    df_pp_deja_fait = pd.read_csv(pp_deja_fait_file)

                    if "nb_traversees" in df_pp_deja_fait.columns and "intersection" in df_pp_deja_fait.columns:
                        df_pp = df_inter_ia.merge(
                            df_pp_deja_fait[["intersection", "nb_traversees"]],
                            on="intersection", how="left",
                        )
                        df_pp["nb_traversees"] = df_pp["nb_traversees"].fillna(0)
                    else:
                        from src.identification_PP import comparer_coordonnees
                        df_pp = comparer_coordonnees(df_pp_deja_fait, df_inter_ia)
                        if "nb_pp" in df_pp.columns:
                            df_pp["nb_traversees"] = df_pp["nb_pp"]
                        elif "nb_passages_pietons" in df_pp.columns:
                            df_pp["nb_traversees"] = df_pp["nb_passages_pietons"]
                        else:
                            df_pp["nb_traversees"] = 0

                    st.session_state["df_pp"]      = df_pp
                    st.session_state["pp_methode"] = "IA"
                    st.session_state["pp_commune"] = ville_pp
                    st.session_state.pop("pp_ia_dossier", None)
                    st.toast(
                        f"{len(df_pp)} intersections chargées depuis le fichier importé.",
                        icon="✅", duration="long",
                    )

                else:
                    from src.IA_PP import analyser_toutes_intersections
                    import re

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
        with st.spinner("Préparation du tableau et des images…"):
            _m = st.session_state["pp_methode"]
            _c = st.session_state.get("pp_commune", "")

            if _m == "IA" and "df_pp" in st.session_state:
                _df_pp_r = st.session_state["df_pp"]
                st.success(f"✅ **{len(_df_pp_r)} intersections analysées** via IA pour {_c}.")
                with st.expander(f"📋 Voir le tableau ({len(_df_pp_r):,} lignes)", expanded=False):
                    st.dataframe(_df_pp_r.head(15), use_container_width=True)
                    st.caption(f"{len(_df_pp_r)} lignes au total")

                col_dl_ia_csv, col_dl_ia_zip = st.columns(2)
                with col_dl_ia_csv:
                    st.download_button(
                        label="📥 Télécharger les résultats (.csv)",
                        data=_df_pp_r.to_csv(index=False).encode("utf-8"),
                        file_name=f"passages_pietons_ia_{_c.lower().replace(' ', '_')}.csv",
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
                teams_dict = route_toutes_equipes2(df, meetup_lat, meetup_lon)

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
            "Accidents": "Accidents corporels (CSV)",
            "IA":        "Détection IA YOLOv8",
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
