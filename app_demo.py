"""
app_demo.py — Version de démonstration DEFIACCESS
100% autonome : aucune dépendance sur src/, pipeline.py ou les fichiers de données.
Toutes les données sont générées aléatoirement autour de Garches.

Lancer avec :
    pip install streamlit folium streamlit-folium pandas openpyxl
    streamlit run app_demo.py
"""

import io
import time
import random
import zipfile

import pandas as pd
import numpy as np
import streamlit as st
import folium
from streamlit_folium import st_folium

# ─────────────────────────────────────────────
# 0. Config page
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="DEFIACCESS — Démo",
    page_icon="♿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# 1. Données fictives
# ─────────────────────────────────────────────
MEETUP_LAT  = 48.8382
MEETUP_LON  = 2.1865

RUES = [
    "Rue de la Paix", "Avenue du Général de Gaulle", "Boulevard Victor Hugo",
    "Rue Jean Jaurès", "Avenue Foch", "Rue du Moulin", "Rue des Écoles",
    "Avenue de la République", "Rue Pasteur", "Rue Gambetta",
    "Allée des Marronniers", "Rue du 8 Mai 1945", "Avenue de la Gare",
    "Rue Voltaire", "Rue de la Liberté", "Boulevard Clémenceau",
    "Rue du Docteur Schweitzer", "Avenue des Fleurs", "Rue Saint-Exupéry",
    "Boulevard de la Marne",
]

POI_NOMS = [
    "Mairie de Garches", "École primaire Jules Ferry",
    "Pharmacie du Centre", "Médiathèque municipale",
    "Marché couvert", "Cabinet médical",
]

COLORS = [
    "#E63946", "#457B9D", "#2A9D8F", "#E9C46A", "#F4A261",
    "#6A4C93", "#1982C4", "#8AC926", "#FF595E", "#6A994E",
]

TEAM_LABELS = ["🔴", "🔵", "🟢", "🟡", "🟠", "🟣", "🔷", "🟩", "🔶", "🟪"]

def generate_mock_data(n_intersections: int, n_teams: int, seed: int = 42) -> tuple:
    """Génère un DataFrame d'intersections fictives autour de Garches."""
    rng = random.Random(seed)
    np.random.seed(seed)

    intersections = []
    for i in range(n_intersections):
        rue_a = rng.choice(RUES)
        rue_b = rng.choice([r for r in RUES if r != rue_a])
        lat = MEETUP_LAT + np.random.uniform(-0.012, 0.012)
        lon = MEETUP_LON + np.random.uniform(-0.018, 0.018)
        equipe = (i % n_teams) + 1
        ordre = (i // n_teams) + 1
        intersections.append({
            "intersection": f"{rue_a} / {rue_b}",
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "Equipe": equipe,
            "Ordre": ordre,
            "nb_traversees": rng.choice([1, 1, 1, 2, 2, 3]),
            "bande_de_guidage": "",
            "bande_eveil": "",
            "Feu_Parlant": "",
            "Commentaire": "",
        })

    df = pd.DataFrame(intersections)

    pois = []
    for nom in POI_NOMS:
        pois.append({
            "nom": nom,
            "latitude": round(MEETUP_LAT + np.random.uniform(-0.008, 0.008), 6),
            "longitude": round(MEETUP_LON + np.random.uniform(-0.012, 0.012), 6),
        })
    pois_df = pd.DataFrame(pois)

    teams = {
        eid: df[df["Equipe"] == eid].reset_index(drop=True)
        for eid in range(1, n_teams + 1)
    }
    return df, pois_df, teams


def make_xlsx_bytes(team_df: pd.DataFrame, team_id: int) -> bytes:
    """Génère un XLSX en mémoire pour une équipe."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        team_df.to_excel(writer, index=False, sheet_name=f"Equipe_{team_id}")
    return buf.getvalue()


# ─────────────────────────────────────────────
# 2. Barre latérale
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ♿ DEFIACCESS")
    st.caption("Démo — données simulées")
    st.divider()

    st.markdown("**Commune**")
    commune_str = st.text_input("Nom", value="Garches, Hauts-de-Seine")

    st.divider()
    st.markdown("**Point de rendez-vous**")
    col1, col2 = st.columns(2)
    meetup_lat = col1.number_input("Lat", value=MEETUP_LAT, format="%.4f")
    meetup_lon = col2.number_input("Lon", value=MEETUP_LON, format="%.4f")

    st.divider()
    st.markdown("**Paramètres**")
    radius_km = st.slider("Rayon POI (km)", 0.05, 1.0, 0.2, 0.05)
    n_teams   = st.slider("Nombre d'équipes", 1, 10, 3, 1)
    n_inter   = st.slider("Intersections simulées", 10, 120, 40, 5,
                          help="En prod ce nombre vient de votre CSV.")

    st.divider()
    st.caption("⚠️ Mode démo — remplacez les mocks par vos vrais modules `src/` une fois prêts.")

# ─────────────────────────────────────────────
# 3. Zone principale
# ─────────────────────────────────────────────
st.markdown("## ♿ DEFIACCESS — Générateur de feuilles terrain")
st.markdown(
    "Chargez vos fichiers sources, ajustez les paramètres dans la barre latérale, "
    "puis cliquez sur **Générer** pour obtenir les feuilles terrain par équipe."
)
st.info("🛠️ **Mode démo** — les données sont simulées. Vos fichiers CSV/XLSX ne sont pas encore requis.", icon="ℹ️")

col_u1, col_u2 = st.columns(2)
with col_u1:
    intersections_file = st.file_uploader("📂 intersections.csv (optionnel en démo)", type=["csv"])
with col_u2:
    lieux_file = st.file_uploader("📍 lieux.xlsx (optionnel en démo)", type=["xlsx"])

st.divider()

generate_btn = st.button(
    "⚙️ Générer les feuilles terrain (données simulées)",
    type="primary",
    use_container_width=True,
)

# ─────────────────────────────────────────────
# 4. Pipeline simulé
# ─────────────────────────────────────────────
if generate_btn:
    progress = st.progress(0, text="Initialisation…")

    steps = [
        (15,  "**Étape 1/5** — Chargement et nettoyage des intersections…"),
        (35,  "**Étape 2/5** — Chargement des points d'intérêt…"),
        (55,  "**Étape 3/5** — Filtrage géographique (rayon {:.0f} m)…".format(radius_km * 1000)),
        (75,  "**Étape 4/5** — Clustering k-means + itinéraires…"),
        (95,  "**Étape 5/5** — Export XLSX…"),
    ]

    status = st.empty()
    for pct, msg in steps:
        status.info(msg)
        progress.progress(pct)
        time.sleep(0.4)   # simule le temps de traitement

    df, pois_df, teams_dict = generate_mock_data(n_inter, n_teams)

    progress.progress(100, text="Terminé ✅")
    status.success(f"**{n_inter} intersections** réparties en **{n_teams} équipe(s)** — données simulées.")

    # ─── Carte ───────────────────────────────
    st.subheader("🗺️ Carte des intersections par équipe")

    m = folium.Map(location=[meetup_lat, meetup_lon], zoom_start=14, tiles="CartoDB positron")

    # Rendez-vous
    folium.Marker(
        [meetup_lat, meetup_lon],
        popup="<b>Point de rendez-vous</b>",
        icon=folium.Icon(color="black", icon="home", prefix="fa"),
    ).add_to(m)

    # POI
    for _, poi in pois_df.iterrows():
        folium.CircleMarker(
            [poi["latitude"], poi["longitude"]],
            radius=9, color="#FF6B35", fill=True, fill_opacity=0.9,
            popup=folium.Popup(f"<b>{poi['nom']}</b>", max_width=200),
        ).add_to(m)

    # Intersections
    for equipe_id, team_df in teams_dict.items():
        color = COLORS[(equipe_id - 1) % len(COLORS)]
        for _, row in team_df.iterrows():
            popup_html = (
                f"<b>Équipe {equipe_id}</b><br>"
                f"Ordre : {int(row['Ordre'])}<br>"
                f"{row['intersection']}"
            )
            folium.CircleMarker(
                [row["latitude"], row["longitude"]],
                radius=6, color=color, fill=True, fill_opacity=0.75,
                popup=folium.Popup(popup_html, max_width=260),
            ).add_to(m)

    st_folium(m, width=None, height=500, returned_objects=[])

    # ─── Stats ───────────────────────────────
    st.subheader("📊 Répartition par équipe")
    stats = []
    for eid, tdf in teams_dict.items():
        stats.append({
            "Équipe": f"{TEAM_LABELS[(eid-1) % len(TEAM_LABELS)]} Équipe {eid}",
            "Intersections": len(tdf),
            "Passages totaux": int(tdf["nb_traversees"].sum()),
        })
    st.dataframe(pd.DataFrame(stats), use_container_width=True, hide_index=True)

    # ─── Aperçu feuille terrain ──────────────
    st.subheader("📋 Aperçu — Feuille terrain Équipe 1")
    st.dataframe(
        teams_dict[1][["Ordre", "intersection", "nb_traversees",
                        "bande_de_guidage", "bande_eveil", "Feu_Parlant", "Commentaire"]],
        use_container_width=True, hide_index=True,
    )

    # ─── ZIP téléchargeable ──────────────────
    st.subheader("⬇️ Téléchargement")
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for eid, tdf in teams_dict.items():
            xlsx_bytes = make_xlsx_bytes(tdf, eid)
            zf.writestr(f"equipe_{eid:02d}.xlsx", xlsx_bytes)
    zip_buf.seek(0)

    nom_commune = commune_str.split(",")[0].strip().lower().replace(" ", "_")
    st.download_button(
        label=f"📦 Télécharger les {n_teams} feuilles terrain (.zip)",
        data=zip_buf,
        file_name=f"defiaccess_{nom_commune}_demo.zip",
        mime="application/zip",
        type="primary",
        use_container_width=True,
    )