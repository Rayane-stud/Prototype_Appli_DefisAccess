"""
app.py — Interface Streamlit no-code pour DEFIACCESS
Permet aux bénévoles de générer des feuilles terrain sans ligne de code.
"""

import io                                   # Pour gerer les données en mémoire
import zipfile                              # Crer des fichier zip sans ecrire sur disque ( rester sur RAM) 
import yaml                                 # lire les fichier type yaml de configuration
import streamlit as st                      # framework principal, c'est la bibli de l'interface graphique
import folium                               # Pour     cartes
from streamlit_folium import st_folium      #      les         intéractives
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
from src.routage import route_all_teams
from src.export import export_all_teams
import pipeline

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
CONFIG_DIR = Path("config")  # Chemin

def load_yaml_configs() -> dict:
    """Retourne un dict {nom_commune: config_dict} pour tous les YAML du dossier config/."""
    configs = {}
    if CONFIG_DIR.exists():
        for yaml_file in sorted(CONFIG_DIR.glob("*.yaml")):
            with open(yaml_file, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            # La clé d'affichage = nom propre de la commune
            nom = cfg.get("commune", yaml_file.stem).split(",")[0].strip()
            configs[nom] = cfg
    return configs

yaml_configs = load_yaml_configs()

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

    # Chargement de la config sélectionnée (ou valeurs par défaut)
    if commune_choice != "— Saisie manuelle —":
        cfg = yaml_configs[commune_choice]
    else:
        cfg = {}

    commune_str = st.text_input(
        "Nom de la commune (filtrage CSV)",
        value=cfg.get("commune", ""),
        placeholder="ex. Garches, Hauts-de-Seine",
    )

    st.divider()

    # --- Paramètres géographiques ---
    st.subheader("Point de rendez-vous")
    col_lat, col_lon = st.columns(2)
    meetup_lat = col_lat.number_input(
        "Latitude", value=float(cfg.get("meetup_lat", 48.8566)), format="%.6f"
    )
    meetup_lon = col_lon.number_input(
        "Longitude", value=float(cfg.get("meetup_long", 2.3522)), format="%.6f"
    )

    st.divider()

    # --- Sliders ---
    st.subheader("Paramètres de recherche")
    radius_km = st.slider(
        "Rayon autour des POI (km)",
        min_value=0.05,
        max_value=1.0,
        value=float(cfg.get("radius_km", 0.2)),
        step=0.05,
        help="Seules les intersections dans ce rayon autour d'un point d'intérêt sont conservées.",
    )
    n_teams = st.slider(
        "Nombre d'équipes",
        min_value=1,
        max_value=20,
        value=int(cfg.get("n_teams", 5)),
        step=1,
        help="Les intersections seront réparties en N groupes géographiques.",
    )

    st.divider()
    st.caption("v1.0 — DEFIACCESS © 2025")

# ─────────────────────────────────────────────
# 3. Zone principale — Uploads
# ─────────────────────────────────────────────
st.header("♿ DEFIACCESS — Générateur de feuilles terrain")
st.markdown(
    "Chargez vos fichiers sources, ajustez les paramètres dans la barre latérale, "
    "puis cliquez sur **Générer** pour obtenir les feuilles terrain par équipe."
)

col_upload1, col_upload2 = st.columns(2)

with col_upload1:
    intersections_file = st.file_uploader(
        "📂 intersections.csv (export GeoJSON)",
        type=["csv"],
        help="Fichier CSV des intersections exporté depuis l'outil GeoJSON.",
    )

with col_upload2:
    lieux_file = st.file_uploader(
        "📍 lieux.xlsx (points d'intérêt)",
        type=["xlsx"],
        help="Fichier Excel listant les lieux à auditer avec leurs coordonnées.",
    )

# ─────────────────────────────────────────────
# 4. Prévisualisation des données brutes
# ─────────────────────────────────────────────
if intersections_file or lieux_file:
    st.divider()
    st.subheader("Aperçu des fichiers chargés")

tabs_preview = []
if intersections_file:
    tabs_preview.append("Intersections")
if lieux_file:
    tabs_preview.append("Lieux d'intérêt")

if tabs_preview:
    tabs = st.tabs(tabs_preview)
    idx = 0

    if intersections_file:
        with tabs[idx]:
            import pandas as pd
            df_preview = pd.read_csv(intersections_file)
            intersections_file.seek(0)  # reset pour usage ultérieur
            st.dataframe(df_preview.head(20), use_container_width=True)
            st.caption(f"{len(df_preview):,} lignes · {len(df_preview.columns)} colonnes")
        idx += 1

    if lieux_file:
        with tabs[idx]:
            import pandas as pd
            df_lieux_preview = pd.read_excel(lieux_file)
            lieux_file.seek(0)
            st.dataframe(df_lieux_preview.head(20), use_container_width=True)
            st.caption(f"{len(df_lieux_preview):,} points d'intérêt")

# ─────────────────────────────────────────────
# 5. Bouton Générer
# ─────────────────────────────────────────────
st.divider()

ready = intersections_file is not None and lieux_file is not None and commune_str.strip() != ""

if not ready:
    manquants = []
    if not intersections_file:
        manquants.append("intersections.csv")
    if not lieux_file:
        manquants.append("lieux.xlsx")
    if not commune_str.strip():
        manquants.append("nom de la commune")
    st.info(f"En attente : **{', '.join(manquants)}**")

generate_btn = st.button(
    "⚙️ Générer les feuilles terrain",
    disabled=not ready,
    type="primary",
    use_container_width=True,
)

# ─────────────────────────────────────────────
# 6. Pipeline principal
# ─────────────────────────────────────────────
if generate_btn and ready:
    output_dir = Path("data/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sauvegarde temporaire des fichiers uploadés
    intersections_path = Path("data/raw/intersections_upload.csv")
    lieux_path = Path("data/raw/lieux_upload.xlsx")
    intersections_path.parent.mkdir(parents=True, exist_ok=True)

    intersections_path.write_bytes(intersections_file.read())
    lieux_path.write_bytes(lieux_file.read())

    # Barre de progression
    progress = st.progress(0, text="Initialisation…")
    status = st.empty()

    try:
        # Étape 1 — Chargement & nettoyage
        status.info("**Étape 1/5** — Chargement et nettoyage des intersections…")
        progress.progress(10)
        df = load_intersections(str(intersections_path), commune_str)
        df = correction_intersections(df)
        df = normalisation_intersections(df)
        df = doublons_intersection(df)
        df = filtre_intersections(df)

        # Étape 2 — Chargement des POI
        status.info("**Étape 2/5** — Chargement des points d'intérêt…")
        progress.progress(30)
        pois = load_pois(str(lieux_path))

        # Étape 3 — Filtrage géographique
        status.info("**Étape 3/5** — Filtrage des intersections proches des POI…")
        progress.progress(50)
        df = filter_nearby(df, pois, radius_km=radius_km)
        df = merge_close_crossings(df, threshold_km=0.03)

        # Étape 4 — Clustering & routing
        status.info("**Étape 4/5** — Répartition par équipes et calcul des itinéraires…")
        progress.progress(70)
        df = cluster_teams(df, n_teams=n_teams, meetup_lat=meetup_lat, meetup_long=meetup_lon)
        teams_dict = route_all_teams(df, meetup_lat=meetup_lat, meetup_long=meetup_lon)

        # Étape 5 — Export XLSX
        status.info("**Étape 5/5** — Génération des feuilles terrain XLSX…")
        progress.progress(90)
        output_files = export_all_teams(teams_dict, str(output_dir))

        progress.progress(100, text="Terminé ✅")
        status.success(
            f"**{len(output_files)} feuille(s) terrain générée(s)** pour {n_teams} équipe(s)."
        )

        # ─────────────────────────────────────────
        # 7. Carte Folium
        # ─────────────────────────────────────────
        st.subheader("🗺️ Carte des intersections par équipe")

        # Palette couleurs pour les équipes
        COLORS = [
            "red", "blue", "green", "purple", "orange",
            "darkred", "lightred", "beige", "darkblue", "darkgreen",
            "cadetblue", "pink", "lightblue", "lightgreen", "gray",
            "black", "lightgray", "white", "darkpurple", "salmon",
        ]

        m = folium.Map(location=[meetup_lat, meetup_lon], zoom_start=14, tiles="CartoDB positron")

        # Point de rendez-vous
        folium.Marker(
            location=[meetup_lat, meetup_lon],
            popup="<b>Point de rendez-vous</b>",
            icon=folium.Icon(color="black", icon="home", prefix="fa"),
        ).add_to(m)

        # POI
        for _, poi in pois.iterrows():
            folium.CircleMarker(
                location=[poi["latitude"], poi["longitude"]],
                radius=8,
                color="#FF6B35",
                fill=True,
                fill_opacity=0.9,
                popup=folium.Popup(str(poi.get("nom", "POI")), max_width=200),
            ).add_to(m)

        # Intersections par équipe
        for equipe_id, team_df in teams_dict.items():
            color = COLORS[(equipe_id - 1) % len(COLORS)]
            for _, row in team_df.iterrows():
                popup_html = (
                    f"<b>Équipe {equipe_id}</b><br>"
                    f"Ordre : {int(row.get('Ordre', 0))}<br>"
                    f"{row.get('intersection', '')}"
                )
                folium.CircleMarker(
                    location=[row["latitude"], row["longitude"]],
                    radius=6,
                    color=color,
                    fill=True,
                    fill_opacity=0.75,
                    popup=folium.Popup(popup_html, max_width=250),
                ).add_to(m)

        st_folium(m, width=None, height=500, returned_objects=[])

        # ─────────────────────────────────────────
        # 8. Statistiques par équipe
        # ─────────────────────────────────────────
        st.subheader("📊 Répartition par équipe")
        import pandas as pd

        stats_rows = []
        for equipe_id, team_df in teams_dict.items():
            stats_rows.append({
                "Équipe": f"Équipe {equipe_id}",
                "Intersections": len(team_df),
                "Passages totaux": int(team_df.get("nb_traversees", pd.Series([1] * len(team_df))).sum()),
            })
        st.dataframe(pd.DataFrame(stats_rows), use_container_width=True, hide_index=True)

        # ─────────────────────────────────────────
        # 9. Téléchargement ZIP
        # ─────────────────────────────────────────
        st.subheader("⬇️ Téléchargement")

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
        st.error(
            f"Colonne manquante dans vos données : **{e}**. "
            "Vérifiez que votre CSV contient bien les colonnes latitude, longitude et intersection."
        )
    except Exception as e:
        progress.empty()
        st.error(f"Une erreur inattendue s'est produite : {e}")
        with st.expander("Détails de l'erreur (pour le débogage)"):
            import traceback
            st.code(traceback.format_exc())
