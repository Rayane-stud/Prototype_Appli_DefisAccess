"""
app.py — Interface Streamlit no-code pour DEFIACCESS
Permet aux bénévoles de générer des feuilles terrain sans ligne de code.
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
# 1b. Constantes & helpers
# ─────────────────────────────────────────────

TYPES_VOIES = [
    "Avenue", "Boulevard", "Route", "Esplanade", "Rue", "Allée",
    "Place", "Square", "Passage", "Impasse", "Voie", "Chemin",
    "Résidence", "Rond-Point",
]

# Dossier où telecharger_intersections.py sauvegarde les GeoJSON filtrés
INTERSECTIONS_DIR = Path("intersections")


def chemin_geojson_commune(code_insee: str) -> Path:
    """Chemin du fichier GeoJSON local pour un code INSEE donné."""
    return INTERSECTIONS_DIR / f"intersections_{code_insee}.geojson"


def trouver_geojson_existant(ville: str) -> Path | None:
    """
    Cherche si un fichier intersections_{code_insee}.geojson existe déjà
    pour la commune donnée, en récupérant le code INSEE via geo.api.gouv.fr.
    Retourne le Path si trouvé, None sinon.
    """
    try:
        from src.telecharger_intersections import trouver_departements
        resultats = trouver_departements(ville)
        if not resultats:
            return None
        # On prend le premier résultat (commune la plus peuplée)
        _, _, code_insee = resultats[0]
        chemin = chemin_geojson_commune(code_insee)
        return chemin if chemin.exists() else None
    except Exception:
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
            st.success(f"Mairie trouvée : {_lat_m:.6f}, {_lon_m:.6f}")
        else:
            st.warning("Mairie introuvable — saisissez les coordonnées manuellement.")

    _default_lat = st.session_state.get("mairie_lat", float(cfg.get("meetup_lat", 48.8566)))
    _default_lon = st.session_state.get("mairie_lon", float(cfg.get("meetup_long", 2.3522)))

    col_lat, col_lon = st.columns(2)
    meetup_lat = col_lat.number_input("Latitude",  value=_default_lat, format="%.6f", key="input_lat")
    meetup_lon = col_lon.number_input("Longitude", value=_default_lon, format="%.6f", key="input_lon")
    st.caption("Modifiez les valeurs ci-dessus pour ajuster le point de RDV.")

    st.divider()

    # --- Sliders ---
    st.subheader("Paramètres de recherche")
    radius_km = st.slider(
        "Rayon autour des POI (km)",
        min_value=0.05, max_value=1.0,
        value=float(cfg.get("radius_km", 0.2)), step=0.05,
        help="Seules les intersections dans ce rayon autour d'un point d'intérêt sont conservées.",
    )
    n_teams = st.slider(
        "Nombre d'équipes",
        min_value=1, max_value=20,
        value=int(cfg.get("n_teams", 5)), step=1,
        help="Les intersections seront réparties en N groupes géographiques.",
    )

    st.divider()
    st.caption("v1.2 — DEFIACCESS © 2025")


# ─────────────────────────────────────────────
# 2a. Intersections — téléchargement automatique
# ─────────────────────────────────────────────
with st.expander("🗂️ Intersections — téléchargement automatique", expanded=True):
    st.markdown(
        "Télécharge automatiquement les intersections de la commune depuis "
        "**data.gouv.fr** (source officielle OpenStreetMap), les filtre par ville "
        "et les sauvegarde localement. Pas besoin d'uploader un CSV à la main."
    )

    if not commune_str.strip():
        st.info("Saisissez d'abord le nom de la commune dans la barre latérale.")
    else:
        ville_inter = commune_str.split(",")[0].strip()
        st.write(f"Commune ciblée : **{ville_inter}**")

        # ── Détection d'un fichier déjà téléchargé ────────────────────
        geojson_existant = trouver_geojson_existant(ville_inter)

        if geojson_existant is not None:
            st.success(f"✅ Fichier déjà présent : `{geojson_existant.name}`")
            st.caption(
                "Les intersections seront chargées depuis ce fichier local. "
                "Cliquez sur 'Forcer le re-téléchargement' pour actualiser depuis data.gouv.fr."
            )

            col_inter_use, col_inter_force = st.columns([3, 2])
            with col_inter_use:
                # Indique que le fichier existant sera utilisé automatiquement
                st.info("📂 Fichier local utilisé — aucune action requise.")
            with col_inter_force:
                forcer_btn = st.button(
                    "🔄 Forcer le re-téléchargement",
                    key="btn_forcer_retelecharge",
                    use_container_width=True,
                )

            if forcer_btn:
                # Supprime le fichier local pour forcer le re-téléchargement
                try:
                    geojson_existant.unlink()
                    st.session_state.pop("inter_geojson_path", None)
                    st.session_state.pop("inter_df_preview", None)
                    st.success("Fichier supprimé — cliquez sur 'Télécharger les intersections' pour relancer.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Impossible de supprimer le fichier : {e}")
            else:
                # Fichier existant → on l'enregistre en session directement
                st.session_state["inter_geojson_path"] = str(geojson_existant)

        else:
            # Aucun fichier local → bouton de téléchargement
            col_inter_dl, col_inter_rst = st.columns([3, 1])
            with col_inter_dl:
                telecharger_inter_btn = st.button(
                    "⬇️ Télécharger les intersections",
                    key="btn_telecharger_inter",
                    type="secondary",
                    use_container_width=True,
                    disabled=not commune_str.strip(),
                )
            with col_inter_rst:
                reset_inter_btn = st.button(
                    "Réinitialiser",
                    key="btn_reset_inter",
                    use_container_width=True,
                )

            if reset_inter_btn:
                st.session_state.pop("inter_geojson_path", None)
                st.session_state.pop("inter_df_preview", None)
                st.rerun()

            if telecharger_inter_btn and commune_str.strip():
                from src.telecharger_intersections import telecharger_intersections_ville

                zone_logs_inter = st.empty()

                class InterLogger(io.StringIO):
                    def write(self, texte):
                        super().write(texte)
                        lignes = self.getvalue().splitlines()
                        zone_logs_inter.code("\n".join(lignes[-20:]) or "…", language="text")
                        return len(texte)

                logs_inter = InterLogger()
                with st.spinner(f"Téléchargement des intersections pour **{ville_inter}**… (peut prendre 1-2 min)"):
                    with contextlib.redirect_stdout(logs_inter):
                        # departements_preresolus=None → la fonction détecte automatiquement
                        # le département via geo.api.gouv.fr, sans interaction console
                        fichiers = telecharger_intersections_ville(
                            ville_inter,
                            departements_preresolus=None,
                        )

                if fichiers:
                    st.session_state["inter_geojson_path"] = fichiers[0]
                    st.success(f"✅ Intersections téléchargées : `{Path(fichiers[0]).name}`")
                else:
                    st.error(
                        "Téléchargement échoué. Vérifiez le nom de la commune ou votre connexion internet. "
                        "Vous pouvez aussi uploader un CSV manuellement ci-dessous."
                    )

        # ── Filtre types de voies (dans le même expander) ─────────────
        st.divider()
        st.markdown("**Filtrer par types de voies**")
        st.caption(
            "Sélectionnez les types de voies à inclure. "
            "Par défaut tous les types sont conservés."
        )

        col_sel_all, col_desel_all = st.columns(2)
        with col_sel_all:
            if st.button("Tout sélectionner", key="voies_select_all", use_container_width=True):
                st.session_state["voies_selectionnees"] = TYPES_VOIES.copy()
                st.rerun()
        with col_desel_all:
            if st.button("Tout désélectionner", key="voies_desel_all", use_container_width=True):
                st.session_state["voies_selectionnees"] = []
                st.rerun()

        _default_voies = st.session_state.get("voies_selectionnees", TYPES_VOIES.copy())
        voies_selectionnees = st.multiselect(
            "Types de voies à inclure",
            options=TYPES_VOIES,
            default=_default_voies,
            key="voies_multiselect",
            help="Laissez vide pour conserver toutes les intersections.",
        )
        st.session_state["voies_selectionnees"] = voies_selectionnees

        if voies_selectionnees:
            st.caption(f"Filtre actif : {', '.join(voies_selectionnees)}")
        else:
            st.caption("Aucun filtre — toutes les intersections seront conservées.")

        # ── Aperçu du GeoJSON chargé ───────────────────────────────────
        if st.session_state.get("inter_geojson_path"):
            _geojson_path = st.session_state["inter_geojson_path"]
            if "inter_df_preview" not in st.session_state:
                try:
                    from src.telecharger_intersections import charger_en_dataframe_sans_input
                    import pandas as pd
                    _df_inter_prev = charger_en_dataframe_sans_input(
                        _geojson_path,
                        types_voies=voies_selectionnees or [],
                    )
                    st.session_state["inter_df_preview"] = _df_inter_prev
                except Exception as e:
                    st.warning(f"Aperçu impossible : {e}")

            if "inter_df_preview" in st.session_state:
                _df_prev = st.session_state["inter_df_preview"]
                st.dataframe(_df_prev.head(20), use_container_width=True)
                st.caption(f"{len(_df_prev):,} intersections chargées après filtrage")


# ─────────────────────────────────────────────
# 2b. Génération des lieux via identification_PM
# ─────────────────────────────────────────────
with st.expander("📍 Générer le fichier lieux.xlsx automatiquement", expanded=False):
    st.markdown(
        "Récupère automatiquement les points d'intérêt de la commune "
        "(écoles, mairie, supermarchés, pharmacies…) depuis les sources "
        "officielles et OpenStreetMap."
    )

    if not commune_str.strip():
        st.info("Saisissez d'abord le nom de la commune dans la barre latérale.")
    else:
        st.write(f"Commune ciblée : **{commune_str.split(',')[0].strip()}**")

    col_gen, col_reset = st.columns([3, 1])
    with col_gen:
        generer_pm_btn = st.button(
            "Générer les lieux",
            key="btn_generer_pm",
            type="secondary",
            use_container_width=True,
            disabled=not commune_str.strip(),
        )
    with col_reset:
        reset_pm_btn = st.button("Réinitialiser", key="btn_reset_pm", use_container_width=True)

    if reset_pm_btn:
        for cle in ("df_pm", "pm_logs", "pm_buffer", "pm_commune"):
            st.session_state.pop(cle, None)
        st.rerun()

    if generer_pm_btn and commune_str.strip():
        from src.identification_PM import construire_dataframe_PM
        ville_cible = commune_str.split(",")[0].strip()
        st.markdown("**Progression :**")
        zone_logs = st.empty()

        class StreamlitLogger(io.StringIO):
            def write(self, texte):
                super().write(texte)
                zone_logs.code("\n".join(self.getvalue().splitlines()[-25:]) or "…", language="text")
                return len(texte)

        logs_buffer = StreamlitLogger()
        with st.spinner(f"Récupération des lieux pour **{ville_cible}**… (1-2 min)"):
            with contextlib.redirect_stdout(logs_buffer):
                df_pm = construire_dataframe_PM(ville_cible)

        st.session_state["df_pm"]      = df_pm
        st.session_state["pm_logs"]    = logs_buffer.getvalue()
        st.session_state["pm_commune"] = ville_cible

        if not df_pm.empty:
            buf = io.BytesIO()
            df_pm.to_excel(buf, index=False)
            buf.seek(0)
            st.session_state["pm_buffer"] = buf.getvalue()

    if "pm_logs" in st.session_state:
        with st.expander("📜 Revoir les messages de la dernière génération", expanded=False):
            st.code(st.session_state["pm_logs"] or "(aucun message)", language="text")

    if "df_pm" in st.session_state:
        df_pm_disp = st.session_state["df_pm"]
        if df_pm_disp.empty:
            st.warning("Aucun lieu trouvé. Vérifiez le nom saisi.")
        else:
            st.success(f"**{len(df_pm_disp)} lieux** trouvés pour {st.session_state.get('pm_commune', commune_str)}.")
            st.dataframe(df_pm_disp.head(30), use_container_width=True)
            st.caption(f"{len(df_pm_disp)} lieux · {df_pm_disp['type'].nunique()} types")
            st.info("✅ Déjà chargé — pas besoin de le re-déposer.")
            if "pm_buffer" in st.session_state:
                st.download_button(
                    label="Télécharger lieux.xlsx (optionnel)",
                    data=st.session_state["pm_buffer"],
                    file_name=f"lieux_{st.session_state.get('pm_commune', 'commune').lower().replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )


# ─────────────────────────────────────────────
# 2b-bis. PIPELINE TOUT-EN-UN
# ─────────────────────────────────────────────
with st.expander("🚀 Générer tout automatiquement (depuis le nom de la ville)", expanded=False):
    st.markdown(
        "Lance **toutes les étapes** à la suite : détection de la mairie, "
        "téléchargement des intersections, génération des lieux, "
        "des passages piétons (OSM) — sans manipulation manuelle."
    )

    if not commune_str.strip():
        st.info("Saisissez d'abord le nom de la commune dans la barre latérale.")
    else:
        st.write(f"Commune ciblée : **{commune_str.split(',')[0].strip()}**")

    col_auto_run, col_auto_reset = st.columns([3, 1])
    with col_auto_run:
        auto_run_btn = st.button(
            "🚀 Tout générer",
            key="btn_auto_run",
            type="primary",
            use_container_width=True,
            disabled=not commune_str.strip() or st.session_state.get("auto_running", False),
        )
    with col_auto_reset:
        auto_reset_btn = st.button("🔄 Réinitialiser", key="btn_auto_reset", use_container_width=True)

    if auto_reset_btn:
        for cle in ("df_pm", "pm_logs", "pm_buffer", "pm_commune",
                    "df_pp", "pp_methode", "pp_commune",
                    "mairie_lat", "mairie_lon", "auto_running",
                    "inter_geojson_path", "inter_df_preview"):
            st.session_state.pop(cle, None)
        st.rerun()

    if auto_run_btn and commune_str.strip():
        st.session_state["auto_running"] = True
        ville_auto = commune_str.split(",")[0].strip()

        # ── A : Mairie ────────────────────────────────────────────────
        with st.spinner("📍 Étape 1/4 — Détection de la mairie…"):
            _lat_a, _lon_a = recuperer_coords_mairie(commune_str)
        if _lat_a is not None:
            st.session_state["mairie_lat"] = _lat_a
            st.session_state["mairie_lon"] = _lon_a
            st.success(f"Mairie : {_lat_a:.6f}, {_lon_a:.6f}")
        else:
            st.warning("Mairie introuvable — coordonnées par défaut utilisées.")

        # ── B : Intersections ─────────────────────────────────────────
        geojson_auto = trouver_geojson_existant(ville_auto)
        if geojson_auto is not None:
            st.info(f"📂 Étape 2/4 — Fichier intersections déjà présent : `{geojson_auto.name}`")
            st.session_state["inter_geojson_path"] = str(geojson_auto)
        else:
            from src.telecharger_intersections import telecharger_intersections_ville
            zone_auto_inter = st.empty()

            class AutoInterLogger(io.StringIO):
                def write(self, texte):
                    super().write(texte)
                    zone_auto_inter.code("\n".join(self.getvalue().splitlines()[-15:]) or "…", language="text")
                    return len(texte)

            logs_auto_inter = AutoInterLogger()
            with st.spinner(f"⬇️ Étape 2/4 — Téléchargement des intersections pour **{ville_auto}**…"):
                with contextlib.redirect_stdout(logs_auto_inter):
                    fichiers_auto = telecharger_intersections_ville(
                        ville_auto,
                        departements_preresolus=None,
                    )

            if fichiers_auto:
                st.session_state["inter_geojson_path"] = fichiers_auto[0]
                st.success(f"✅ Intersections : `{Path(fichiers_auto[0]).name}`")
            else:
                st.error("Téléchargement des intersections échoué.")
                st.session_state["auto_running"] = False
                st.stop()

        # ── C : Lieux (POI) ───────────────────────────────────────────
        from src.identification_PM import construire_dataframe_PM
        zone_auto_pm = st.empty()

        class AutoPMLogger(io.StringIO):
            def write(self, texte):
                super().write(texte)
                zone_auto_pm.code("\n".join(self.getvalue().splitlines()[-10:]) or "…", language="text")
                return len(texte)

        logs_auto_pm = AutoPMLogger()
        with st.spinner(f"🏪 Étape 3/4 — Génération des lieux pour **{ville_auto}**…"):
            with contextlib.redirect_stdout(logs_auto_pm):
                df_pm_auto = construire_dataframe_PM(ville_auto)

        if df_pm_auto.empty:
            st.error("Aucun lieu trouvé — vérifiez le nom de la commune.")
            st.session_state["auto_running"] = False
            st.stop()

        buf_auto = io.BytesIO()
        df_pm_auto.to_excel(buf_auto, index=False)
        buf_auto.seek(0)
        st.session_state["df_pm"]      = df_pm_auto
        st.session_state["pm_buffer"]  = buf_auto.getvalue()
        st.session_state["pm_commune"] = ville_auto
        st.success(f"✅ {len(df_pm_auto)} lieux générés.")

        # ── D : Passages piétons OSM ──────────────────────────────────
        from src.identification_PP import get_osm_area_id, telecharger_passages_par_zone
        with st.spinner(f"🚶 Étape 4/4 — Passages piétons OSM pour **{ville_auto}**…"):
            id_zone_auto = get_osm_area_id(ville_auto)
            if id_zone_auto:
                df_pp_auto = telecharger_passages_par_zone(id_zone_auto, rayon_metres=25)
                if not df_pp_auto.empty:
                    st.session_state["df_pp"]       = df_pp_auto
                    st.session_state["pp_methode"]  = "OSM"
                    st.session_state["pp_commune"]  = ville_auto
                    st.success(f"✅ {len(df_pp_auto)} passages piétons chargés.")
                else:
                    st.warning("Aucun passage piéton trouvé via OSM.")
            else:
                st.warning("Zone OSM introuvable — passages piétons ignorés.")

        st.session_state["auto_running"] = False
        st.session_state.pop("inter_df_preview", None)  # force refresh aperçu
        st.success("✅ **Tout est prêt !** Cliquez sur **Générer les feuilles terrain** ci-dessous.")
        st.rerun()


# ─────────────────────────────────────────────
# 2c. Génération des passages piétons (PP)
# ─────────────────────────────────────────────
with st.expander("🚶 Générer les passages piétons", expanded=False):
    st.markdown(
        "Identifie les passages piétons autour des intersections selon la méthode choisie."
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
        for cle in ("df_pp", "pp_methode", "pp_commune"):
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
                    else:
                        st.warning("Aucun passage piéton trouvé via OSM.")
                else:
                    st.error(f"Zone OSM introuvable pour '{ville_pp}'.")

        elif methode_pp == "Accidents (CSV)":
            if accidents_file is None:
                st.error("Uploadez d'abord le fichier CSV d'accidents.")
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
                        else:
                            st.warning(f"Aucun accident sur PP trouvé pour '{ville_pp}'.")
                    except Exception as e:
                        os.unlink(tmp_path)
                        st.error(f"Erreur CSV : {e}")

        elif methode_pp == "IA (YOLO — best.pt requis)":
            import os
            if not os.path.exists(os.path.join("models", "best.pt")):
                st.error("Modèle introuvable.")
            else:
                st.info("Détection IA lancée pendant la génération des feuilles terrain.")
                st.session_state["pp_methode"] = "IA"
                st.session_state["pp_commune"] = ville_pp

    if "pp_methode" in st.session_state:
        _m = st.session_state["pp_methode"]
        _c = st.session_state.get("pp_commune", "")
        if _m == "IA":
            st.success(f"✅ Méthode IA sélectionnée pour **{_c}**.")
        elif "df_pp" in st.session_state:
            _df_pp_r = st.session_state["df_pp"]
            st.success(f"✅ **{len(_df_pp_r)} entrées PP** via {_m} pour {_c}.")
            st.dataframe(_df_pp_r.head(15), use_container_width=True)
            st.caption(f"{len(_df_pp_r)} lignes au total")


# ─────────────────────────────────────────────
# 3. Zone principale — Upload lieux + fallback intersections CSV
# ─────────────────────────────────────────────
st.header("|DF| DEFIACCESS — Générateur de feuilles terrain")
st.markdown(
    "Ajustez les paramètres dans la barre latérale, "
    "puis cliquez sur **Générer** pour obtenir les feuilles terrain par équipe."
)

# ── Résolution source intersections ───────────────────────────────────
# Priorité : GeoJSON téléchargé auto > CSV uploadé manuellement
_inter_geojson_path = st.session_state.get("inter_geojson_path")

col_upload_inter, col_upload_lieux = st.columns(2)

with col_upload_inter:
    if _inter_geojson_path and Path(_inter_geojson_path).exists():
        st.success(
            f"✅ Intersections chargées automatiquement : "
            f"`{Path(_inter_geojson_path).name}`"
        )
        intersections_file = None          # pas d'upload manuel nécessaire
        intersections_source = "geojson"   # marqueur pour le pipeline
    else:
        st.markdown("**intersections.csv** — upload manuel (si pas de téléchargement auto)")
        intersections_file = st.file_uploader(
            "intersections.csv",
            type=["csv"],
            help="CSV des intersections — utilisez l'expander ci-dessus pour l'obtenir automatiquement.",
        )
        intersections_source = "csv" if intersections_file else None

with col_upload_lieux:
    lieux_file = st.file_uploader(
        "lieux.xlsx (points d'intérêt)",
        type=["xlsx"],
        help="Inutile si vous avez utilisé la génération automatique ci-dessus.",
    )
    if lieux_file is None and st.session_state.get("pm_buffer"):
        st.success("✅ Fichier lieux généré automatiquement — il sera utilisé.")

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

if _has_inter or _has_lieux:
    st.divider()
    st.subheader("Aperçu des données chargées")

    import pandas as pd

    tabs_preview = []
    if _has_inter:
        tabs_preview.append("Intersections")
    if _has_lieux:
        tabs_preview.append("Lieux d'intérêt")

    tabs = st.tabs(tabs_preview)
    idx = 0

    if _has_inter:
        with tabs[idx]:
            if intersections_source == "geojson" and "inter_df_preview" in st.session_state:
                _df_p = st.session_state["inter_df_preview"]
                st.dataframe(_df_p.head(20), use_container_width=True)
                st.caption(f"{len(_df_p):,} intersections · filtrage voies appliqué")
            elif intersections_source == "csv" and intersections_file:
                _df_p = pd.read_csv(intersections_file)
                intersections_file.seek(0)
                st.dataframe(_df_p.head(20), use_container_width=True)
                st.caption(f"{len(_df_p):,} lignes · {len(_df_p.columns)} colonnes")
        idx += 1

    if _has_lieux:
        with tabs[idx]:
            _df_l = pd.read_excel(lieux_source)
            if hasattr(lieux_source, "seek"):
                lieux_source.seek(0)
            st.dataframe(_df_l.head(20), use_container_width=True)
            st.caption(f"{len(_df_l):,} points d'intérêt")


# ─────────────────────────────────────────────
# 5. Bouton Générer
# ─────────────────────────────────────────────
st.divider()

ready = (
    (intersections_source is not None)
    and (lieux_source is not None)
    and commune_str.strip() != ""
)

if not ready:
    manquants = []
    if intersections_source is None:
        manquants.append("intersections (téléchargement auto ou CSV manuel)")
    if lieux_source is None:
        manquants.append("lieux.xlsx (upload ou génération auto)")
    if not commune_str.strip():
        manquants.append("nom de la commune")
    st.info(f"En attente : **{', '.join(manquants)}**")

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

    output_dir = Path("data/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    progress = st.progress(0, text="Initialisation…")
    status   = st.empty()

    try:
        # ── Étape 1 — Chargement des intersections ────────────────────
        status.info("**Étape 1/6** — Chargement et nettoyage des intersections…")
        progress.progress(8)

        if intersections_source == "geojson":
            # Charger depuis le GeoJSON local sans interaction console
            from src.telecharger_intersections import charger_en_dataframe_sans_input
            _voies_pipeline = st.session_state.get("voies_selectionnees", [])
            df = charger_en_dataframe_sans_input(
                _inter_geojson_path,
                types_voies=_voies_pipeline or [],
            )
        else:
            # Fallback CSV uploadé manuellement
            intersections_path = Path("data/raw/intersections_upload.csv")
            intersections_path.parent.mkdir(parents=True, exist_ok=True)
            intersections_path.write_bytes(intersections_file.read())
            df = charger_intersections(str(intersections_path), commune_str)

            # Filtre types de voies sur le CSV aussi
            _voies_pipeline = st.session_state.get("voies_selectionnees", [])
            if _voies_pipeline:
                pattern = "|".join(_voies_pipeline)
                avant = len(df)
                df = df[df["intersection"].str.contains(pattern, case=False, na=False)].reset_index(drop=True)
                status.info(f"**Étape 1/6** — Filtre voies : {avant} → {len(df)} intersections.")

        progress.progress(15)

        if df.empty:
            st.error(
                "Aucune intersection après chargement/filtrage. "
                "Vérifiez le nom de la commune ou les types de voies sélectionnés."
            )
            st.stop()

        # ── Étape 2 — Chargement des POI ──────────────────────────────
        status.info("**Étape 2/6** — Chargement des points d'intérêt…")
        progress.progress(30)
        lieux_path = Path("data/raw/lieux_upload.xlsx")
        lieux_path.parent.mkdir(parents=True, exist_ok=True)
        if lieux_file is not None:
            lieux_path.write_bytes(lieux_file.read())
        else:
            lieux_path.write_bytes(st.session_state["pm_buffer"])
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
            from src.IA_PP import analyser_toutes_intersections
            from datetime import datetime
            dossier_images = str(
                Path("data/raw/images_pp")
                / f"images_{commune_str.split(',')[0].strip()}_{datetime.now().strftime('%d-%m-%Y_%Hh%M')}"
            )
            df = analyser_toutes_intersections(
                df, col_lat="latitude", col_lon="longitude", dossier_images=dossier_images
            )

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
        output_files = export_final_equipes(teams_dict, str(output_dir))

        progress.progress(100, text="Terminé ✅")
        status.success(f"**{len(output_files)} feuille(s) générée(s)** pour {n_teams} équipe(s).")

        # ─────────────────────────────────────────
        # 7. Carte Folium
        # ─────────────────────────────────────────
        st.subheader("🗺️ Carte des intersections par équipe")

        COLORS = [
            "red", "blue", "green", "purple", "orange",
            "darkred", "lightred", "beige", "darkblue", "darkgreen",
            "cadetblue", "pink", "lightblue", "lightgreen", "gray",
            "black", "lightgray", "white", "darkpurple", "salmon",
        ]

        m = folium.Map(location=[meetup_lat, meetup_lon], zoom_start=14, tiles="CartoDB positron")
        folium.Marker(
            location=[meetup_lat, meetup_lon],
            popup="<b>Point de rendez-vous</b>",
            icon=folium.Icon(color="black", icon="home", prefix="fa"),
        ).add_to(m)

        for _, poi in pois.iterrows():
            folium.CircleMarker(
                location=[poi["latitude"], poi["longitude"]],
                radius=8, color="#FF6B35", fill=True, fill_opacity=0.9,
                popup=folium.Popup(str(poi.get("lieu", "POI")), max_width=200),
                tooltip=str(poi.get("lieu", "POI")),
            ).add_to(m)

        for equipe_id, team_df in teams_dict.items():
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

        st_folium(m, width=None, height=500, returned_objects=[])

        # ─────────────────────────────────────────
        # 8. Statistiques
        # ─────────────────────────────────────────
        st.subheader("📊 Répartition par équipe")
        stats_rows = []
        for equipe_id, team_df in teams_dict.items():
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
        }.get(_pp_methode, "Inconnue")
        st.caption(f"Méthode passages piétons : {_pp_label}")

        # ─────────────────────────────────────────
        # 9. Téléchargement ZIP
        # ─────────────────────────────────────────
        st.subheader("📥 Téléchargement")
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath in output_files:
                zf.write(fpath, arcname=Path(fpath).name)
        zip_buffer.seek(0)

        st.download_button(
            label=f"📦 Télécharger les {len(output_files)} feuilles terrain (.zip)",
            data=zip_buffer,
            file_name=f"defiaccess_{commune_str.split(',')[0].strip().lower().replace(' ', '_')}.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
        )

    except FileNotFoundError as e:
        progress.empty()
        st.error(f"Fichier introuvable : {e}")
    except KeyError as e:
        progress.empty()
        st.error(f"Colonne manquante : **{e}** — vérifiez que vos données contiennent latitude, longitude et intersection.")
    except Exception as e:
        progress.empty()
        st.error(f"Erreur inattendue : {e}")
        with st.expander("Détails (débogage)"):
            import traceback
            st.code(traceback.format_exc())