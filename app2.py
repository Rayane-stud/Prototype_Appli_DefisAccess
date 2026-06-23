"""
app.py — Interface Streamlit no-code pour DEFIACCESS
Permet aux bénévoles de générer des feuilles terrain sans ligne de code.
"""
import numpy as np
import io                                   # Pour gerer les données en mémoire
import zipfile                              # Crer des fichier zip sans ecrire sur disque ( rester sur RAM)
import contextlib                           # Pour capturer les print(...) de identification_PM
import yaml                                 # lire les fichier type yaml de configuration
import streamlit as st                      # framework principal, c'est la bibli de l'interface graphique
import folium                               # Pour     cartes
from streamlit_folium import st_folium      #      les         intéractives
from pathlib import Path

import streamlit_folium  # Pour afficher les cartes Folium dans Streamlit


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
    layout="wide",                            # utilise tout l'ecran au lieu de centrer
    initial_sidebar_state="expanded",         # la barre latérale est ouverte par defaut
)

# ─────────────────────────────────────────────
# 1. Chargement des configs YAML disponibles
# ─────────────────────────────────────────────
CONFIG_DIR = Path("config")  # Chemin

def load_yaml_configs() -> dict:
    """Retourne un dict {nom_commune: config_dict} pour tous les YAML du dossier config/."""
    configs = {}
    if CONFIG_DIR.exists():
        for yaml_file in sorted(CONFIG_DIR.glob("*.yaml")):    # ".glob(*.yaml)" retrouve tout les fichiers .yaml
            with open(yaml_file, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)                        # Lit le fichier YAML ded facon sécu
            # La clé d'affichage = nom propre de la commune
            nom = cfg.get("commune", yaml_file.stem).split(",")[0].strip()  #recupere la valeur ou le nom du fichier par défaut
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
    commune_names = list(yaml_configs.keys()) #recup des nom des vvilles
    commune_choice = st.selectbox(                                                                        # Renvoie la valeur choisie
        "Commune",
        options=["— Saisie manuelle —"] + commune_names,   # Options de la liste déroulante
        help="Sélectionnez une commune pré-configurée ou saisissez les paramètres manuellement.",        # Texte qui apparait au survol
    )

    # Chargement de la config sélectionnée (ou valeurs par défaut)
    if commune_choice != "— Saisie manuelle —":
        cfg = yaml_configs[commune_choice]
    else:
        cfg = {}

    # widget de saisie — LE SEUL ENDROIT où on saisit le nom de la commune
    commune_str = st.text_input(
        "Nom de la commune",
        value=cfg.get("commune", ""),               # Ce qui est ecrit par defaut dans la case d'input, auto remplissage si selectionné dans la liste
        placeholder="ex. Garches, Hauts-de-Seine",  # Texte en arrière plan au fond de la case d'input qd elle est vide
        help="Ce nom sert à la fois au filtrage des intersections ET à la génération automatique des lieux.",
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
# 2b. Génération des lieux via identification_PM
# ─────────────────────────────────────────────
with st.expander(" Générer le fichier lieux.xlsx automatiquement", expanded=False):
    st.markdown(
        "Récupère automatiquement les points d'intérêt de la commune "
        "(écoles, mairie, supermarchés, pharmacies…) depuis les sources "
        "officielles et OpenStreetMap, puis les charge directement dans l'outil."
    )

    # On réutilise commune_str saisi UNE SEULE FOIS dans la barre latérale.
    # Plus de second champ texte ici.
    if not commune_str.strip():
        st.info("Saisissez d'abord le nom de la commune dans la barre latérale (à gauche).")
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
        # "Réinitialiser" : efface le résultat précédent stocké en session,
        # ce qui permet de relancer proprement une nouvelle génération.
        reset_pm_btn = st.button(
            "Réinitialiser",
            key="btn_reset_pm",
            use_container_width=True,
        )

    if reset_pm_btn:
        # on vide tout ce qui concerne la génération PM en session
        for cle in ("df_pm", "pm_logs", "pm_buffer", "pm_commune"):
            st.session_state.pop(cle, None)
        st.rerun()

    if generer_pm_btn and commune_str.strip():
        from src.identification_PM import construire_dataframe_PM  # import local

        ville_cible = commune_str.split(",")[0].strip()

        # Conteneur Streamlit où les messages s'afficheront EN TEMPS RÉEL.
        # st.empty() est une zone qu'on peut réécrire à volonté : à chaque
        # nouveau print, on y réaffiche l'ensemble des lignes accumulées.
        st.markdown("**Progression de la génération :**")
        zone_logs = st.empty()

        class StreamlitLogger(io.StringIO):
            """
            Faux 'stdout' : intercepte chaque print(...) de identification_PM
            et met à jour la zone Streamlit au fur et à mesure, sans modifier
            le module source. On herite de io.StringIO pour garder une copie
            complete du texte (recuperable a la fin via getvalue()).
            """
            def write(self, texte):
                super().write(texte)              # on garde le texte en memoire
                contenu = self.getvalue()
                # on n'affiche que les ~25 dernieres lignes pour rester lisible
                lignes = contenu.splitlines()
                apercu = "\n".join(lignes[-25:])
                zone_logs.code(apercu or "…", language="text")
                return len(texte)

        logs_buffer = StreamlitLogger()
        with st.spinner(f"Récupération des lieux pour **{ville_cible}**… (peut prendre 1-2 min)"):
            # redirect_stdout envoie tous les print(...) vers notre logger,
            # qui les affiche en direct dans zone_logs.
            with contextlib.redirect_stdout(logs_buffer):
                df_pm = construire_dataframe_PM(ville_cible)

        # On stocke le résultat en session pour qu'il survive aux reruns Streamlit
        st.session_state["df_pm"] = df_pm
        st.session_state["pm_logs"] = logs_buffer.getvalue()
        st.session_state["pm_commune"] = ville_cible

        # Si des lieux ont été trouvés, on prépare le fichier en mémoire
        # qui sera injecté directement dans le slot lieux (section 3)
        if not df_pm.empty:
            buffer_pm = io.BytesIO()
            df_pm.to_excel(buffer_pm, index=False)
            buffer_pm.seek(0)
            st.session_state["pm_buffer"] = buffer_pm.getvalue()

    # ── Logs consultables après coup (persistants via session_state) ──
    # L'affichage en direct ci-dessus disparaît au rerun ; cet expander
    # permet de revoir l'historique complet de la dernière génération.
    if "pm_logs" in st.session_state:

        with st.expander("📜 Revoir les messages de la dernière génération", expanded=False):

            st.code(st.session_state["pm_logs"] or "(aucun message)", language="text")

    if "df_pm" in st.session_state:
        df_pm = st.session_state["df_pm"]
        if df_pm.empty:
            st.warning("Aucun lieu trouvé pour cette commune. Vérifiez le nom saisi.")
        else:
            st.success(
                f"**{len(df_pm)} lieux** trouvés pour "
                f"{st.session_state.get('pm_commune', commune_str)}."
            )
            st.dataframe(df_pm.head(30), use_container_width=True)
            st.caption(f"{len(df_pm)} lieux au total · {df_pm['type'].nunique()} types")
            st.info(
                " Ce fichier est déjà chargé dans l'outil ci-dessous : "
                "pas besoin de le télécharger ni de le re-déposer."
            )

            # Téléchargement optionnel (si l'utilisateur veut garder une copie)
            if "pm_buffer" in st.session_state:
                st.download_button(
                    label="Télécharger lieux.xlsx (optionnel)",
                    data=st.session_state["pm_buffer"],
                    file_name=f"lieux_{st.session_state.get('pm_commune', 'commune').lower().replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )


# ─────────────────────────────────────────────
# 3. Zone principale — Uploads
# ─────────────────────────────────────────────
st.header("|DF| DEFIACCESS — Générateur de feuilles terrain")
st.markdown(
    "Chargez vos fichiers sources, ajustez les paramètres dans la barre latérale, "
    "puis cliquez sur **Générer** pour obtenir les feuilles terrain par équipe."
)

col_upload1, col_upload2 = st.columns(2)

with col_upload1:
    intersections_file = st.file_uploader(
        "intersections.csv (export GeoJSON)",
        type=["csv"],
        help="Fichier CSV des intersections exporté depuis l'outil GeoJSON.",
    )

with col_upload2:
    lieux_file = st.file_uploader(
        "lieux.xlsx (points d'intérêt)",
        type=["xlsx"],
        help="Fichier Excel listant les lieux à auditer. "
             "Inutile si vous avez utilisé la génération automatique ci-dessus.",
    )
    if lieux_file is None and st.session_state.get("pm_buffer"):
        st.success(" Fichier lieux généré automatiquement détecté — il sera utilisé.")

# ── Résolution de la source "lieux" : upload manuel OU fichier généré ──
# lieux_source = ce qu'on utilisera partout ensuite, peu importe l'origine.
# Priorité à l'upload manuel s'il existe, sinon au fichier généré en session.
if lieux_file is not None:
    lieux_source = lieux_file
elif st.session_state.get("pm_buffer"):
    lieux_source = io.BytesIO(st.session_state["pm_buffer"])
    lieux_source.name = "lieux_genere.xlsx"
else:
    lieux_source = None

# ─────────────────────────────────────────────
# 4. Prévisualisation des données brutes
# ─────────────────────────────────────────────
if intersections_file or lieux_source:
    st.divider()
    st.subheader("Aperçu des fichiers chargés")

tabs_preview = []
if intersections_file:
    tabs_preview.append("Intersections")
if lieux_source:
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

    if lieux_source:
        with tabs[idx]:
            import pandas as pd
            df_lieux_preview = pd.read_excel(lieux_source)
            if hasattr(lieux_source, "seek"):
                lieux_source.seek(0)  # IMPORTANT : remise du curseur de lecture à 0
            st.dataframe(df_lieux_preview.head(20), use_container_width=True)
            st.caption(f"{len(df_lieux_preview):,} points d'intérêt")

# ─────────────────────────────────────────────
# 5. Bouton Générer
# ─────────────────────────────────────────────
st.divider()

ready = (
    intersections_file is not None
    and lieux_source is not None
    and commune_str.strip() != ""
)

if not ready:
    manquants = []
    if not intersections_file:
        manquants.append("intersections.csv")
    if lieux_source is None:
        manquants.append("lieux.xlsx (upload ou génération auto)")
    if not commune_str.strip():
        manquants.append("nom de la commune")
    st.info(f"En attente : **{', '.join(manquants)}**") # encadré bleu

generate_btn = st.button(
    " Générer les feuilles terrain",
    disabled=not ready,
    type="primary",
    use_container_width=True,
)

# ─────────────────────────────────────────────
# 6. main principal
# ─────────────────────────────────────────────
if generate_btn and ready:
    output_dir = Path("data/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sauvegarde temporaire des fichiers uploadés
    intersections_path = Path("data/raw/intersections_upload.csv")
    lieux_path = Path("data/raw/lieux_upload.xlsx")
    intersections_path.parent.mkdir(parents=True, exist_ok=True) # Creation du dossier si il n'existe pas deja

    intersections_path.write_bytes(intersections_file.read())  # ecriture des fichiers

    # Le fichier lieux peut venir d'un upload manuel OU de la génération auto :
    if lieux_file is not None:
        lieux_path.write_bytes(lieux_file.read())
    else:
        lieux_path.write_bytes(st.session_state["pm_buffer"])

    # Barre de progression
    progress = st.progress(0, text="Initialisation…")
    status = st.empty()

    try:
        # Étape 1 — Chargement & nettoyage (charger_intersections fait déjà tout le nettoyage en interne)
        status.info("**Étape 1/5** — Chargement et nettoyage des intersections…")
        progress.progress(10)
        df = charger_intersections(str(intersections_path), commune_str)

        # Étape 2 — Chargement des POI
        status.info("**Étape 2/5** — Chargement des points d'intérêt…")
        progress.progress(30)
        pois = charger_points(str(lieux_path))

        # Étape 3 — Filtrage géographique (ordre des arguments : lieux puis intersections)
        status.info("**Étape 3/5** — Filtrage des intersections proches des POI…")
        progress.progress(50)
        df = filtre_distance(pois, df, rayon_km=radius_km)
        df = fusion_croisement(df, threshold_km=0.03)

        # ⚠️ Provisoire — nombre de traversées aléatoire, à remplacer
        df["nb_traversees"] = np.random.randint(1, 5, size=len(df))

        # Étape 4 — Clustering & routing (n_equipes, pas n_teams)
        status.info("**Étape 4/5** — Répartition par équipes et calcul des itinéraires…")
        progress.progress(70)
        df = assigner_equipes(df, n_equipes=n_teams, meetup_lat=meetup_lat, meetup_long=meetup_lon)
        teams_dict = route_toutes_equipes(df, meetup_lat, meetup_lon)

        # Étape 5 — Export XLSX
        status.info("**Étape 5/5** — Génération des feuilles terrain XLSX…")
        progress.progress(90)
        output_files = export_final_equipes(teams_dict, str(output_dir))

        progress.progress(100, text="Terminé ")
        status.success(
            f"**{len(output_files)} feuille(s) terrain générée(s)** pour {n_teams} équipe(s)."
        )

        # ─────────────────────────────────────────
        # 7. Carte Folium
        # ─────────────────────────────────────────
        st.subheader(" Carte des intersections par équipe")

        # Palette couleurs pour les équipes
        COLORS = [
            "red", "blue", "green", "purple", "orange",
            "darkred", "lightred", "beige", "darkblue", "darkgreen",
            "cadetblue", "pink", "lightblue", "lightgreen", "gray",
            "black", "lightgray", "white", "darkpurple", "salmon",
        ]

        m = folium.Map(location=[meetup_lat, meetup_lon], zoom_start=14, tiles="CartoDB positron") # Creation de la carte

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
                popup=folium.Popup(str(poi.get("lieu", "POI")), max_width=200),
                tooltip=str(poi.get("lieu", "POI")),  # bonus : affiche le nom au survol, sans avoir à cliquer
            ).add_to(m)

        # Intersections par équipe
        for equipe_id, team_df in teams_dict.items():
            color = COLORS[(equipe_id - 1) % len(COLORS)]
            for _, row in team_df.iterrows():
                popup_html = (
                    f"<b>Équipe {equipe_id}</b><br>"
                    f"Ordre : {int(row.get('ordre', 0))}<br>"
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
        st.subheader(" Répartition par équipe")
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
        st.subheader(" Téléchargement")

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath in output_files:
                zf.write(fpath, arcname=Path(fpath).name)
        zip_buffer.seek(0)

        st.download_button(
            label=f" Télécharger les {len(output_files)} feuilles terrain (.zip)",
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