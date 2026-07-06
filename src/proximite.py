"""
FICHIER contenant la logique metier gerant l'etape 3 :
Regrouper les croisements majeurs, les filtrer par distance,
supprimer les doublons et exporter les resultats.

# LISTE DES FONCTIONS :

- charger_points(chemin) :
    # ROLE : Charger le fichier lieux.xlsx et retourner un DataFrame
              avec une ligne par point d'interet (mairie, gare, etc.)
    # ARGUMENTS : "chemin" de type str
    # REPONSE : pd.DataFrame avec colonnes : lieu, coordonnees, latitude, longitude

- filtre_distance(df_lieux, df_intersections, rayon_km) :
    # ROLE : Garder uniquement les intersections situees
              a moins de rayon_km d'un point d'interet
    # ARGUMENTS : "df_lieux" de type DataFrame (points d'interet)
                  "df_intersections" de type DataFrame (intersections)
                  "rayon_km" de type float (defaut : 0.2)
    # REPONSE : pd.DataFrame avec uniquement les intersections proches

- fusion_croisement(df_intersections, threshold_km) :
    # ROLE : Fusionner les intersections espacees de moins de threshold_km
    # ARGUMENTS : "df_intersections" de type DataFrame
                  "threshold_km" de type float (defaut : 0.03)
    # REPONSE : pd.DataFrame avec les intersections fusionnees

- assigner_equipes(df, n_equipes, meetup_lat, meetup_long) :
    # ROLE : Appliquer un k-means sur les coordonnees pour repartir
              les intersections en N equipes et calculer l'ordre
              de passage au sein de chaque equipe
    # ARGUMENTS : "df" de type DataFrame
                  "n_equipes" de type int
                  "meetup_lat" de type float
                  "meetup_long" de type float
    # REPONSE : pd.DataFrame avec les colonnes "equipe" et "ordre" ajoutees
"""

import pandas as pd
import numpy as np
from geopy.distance import geodesic
from sklearn.cluster import KMeans
from k_means_constrained import KMeansConstrained 
# from nettoyage import charger_intersections


POINT_PRINCIPAL = (48.8381857639848, 2.1865433360720927)  # Gare de Garches


# FONCTION : charger_points() --------------------------------------------------

def charger_points(chemin):
    df = pd.read_excel(chemin)

    # Nouveau format (identifier_PM_hybride) : colonnes nommées
    # nom | type | source | latitude | longitude | coordonnees
    if "latitude" in df.columns and "longitude" in df.columns:
        df["latitude"]  = pd.to_numeric(df["latitude"],  errors="coerce")
        df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
        df = df.dropna(subset=["latitude", "longitude"])

        # on ajoute "lieu" pour que le reste du pipeline (filtre_distance, etc.)
        # continue de fonctionner sans modification
        if "lieu" not in df.columns:
            df["lieu"] = df["nom"]

        return df[["lieu", "latitude", "longitude"]]

    # Ancien format (fichier manuel) : lieux en ligne 0, coordonnées en ligne 1
    df_raw = pd.read_excel(chemin, header=None)
    lieux       = df_raw.iloc[0, 1:].values
    coordonnees = df_raw.iloc[1, 1:].values

    df_propre = pd.DataFrame({"lieu": lieux, "coordonnees": coordonnees})
    df_propre = df_propre.dropna(subset=["coordonnees"])

    df_propre["latitude"] = (
        df_propre["coordonnees"].astype(str).str.split(",").str[0].str.strip().astype(float)
    )
    df_propre["longitude"] = (
        df_propre["coordonnees"].astype(str).str.split(",").str[1].str.strip().astype(float)
    )

    return df_propre[["lieu", "latitude", "longitude"]]


# FONCTION : filtre_distance() -------------------------------------------------

def filtre_distance(df_lieux, df_intersections, rayon_km: float = 0.2):
    # ETAPE 1 : on travaille sur des copies pour ne pas modifier les originaux
    df_l = df_lieux.copy()
    df_i = df_intersections.copy()

    # ETAPE 2 : on cree une colonne booleen pour marquer les intersections retenues
    df_i["pres_pm"] = False

    # ETAPE 3 : pour chaque point d'interet on calcule la distance
    # a chaque intersection et on marque celles qui sont dans le rayon
    for _, lieu in df_l.iterrows():
        lat = lieu["latitude"]
        long = lieu["longitude"]

        distances = df_i.apply(
            lambda row: geodesic(
                (row["latitude"], row["longitude"]),
                (lat, long)
            ).km,
            axis=1
        )

        # on marque True les intersections dans le rayon
        df_i.loc[distances < rayon_km, "pres_pm"] = True

    # ETAPE 4 : on ne garde que les intersections proches
    # et on supprime la colonne temporaire pres_pm
    df_filtre = (
        df_i[df_i["pres_pm"]]
        .drop(columns=["pres_pm"])
        .reset_index(drop=True)
    )

    return df_filtre


# FONCTION : fusion_croisement() -----------------------------------------------

def fusion_croisement(df_intersections, threshold_km: float = 0.03):
    lignes = df_intersections.copy().reset_index(drop=True).to_dict("records")

    if lignes:
        print("COLONNES DISPONIBLES :", list(lignes[0].keys()))

    i = 0
    while i < len(lignes):
        j = i + 1
        while j < len(lignes):
            dist = geodesic(
                (lignes[i]["latitude"], lignes[i]["longitude"]),
                (lignes[j]["latitude"], lignes[j]["longitude"])
            ).km
            if dist <= threshold_km:
                lignes[i]["intersection"] += " / " + lignes[j]["intersection"]  #  "lieu" au lieu de "intersection"
                lignes.pop(j)
            else:
                j += 1
        i += 1

    df_fusionne = pd.DataFrame(lignes).reset_index(drop=True)
    return df_fusionne

# FONCTION : assigner_equipes() ------------------------------------------------

def assigner_equipes(df, n_equipes: int, meetup_lat: float, meetup_long: float):
    # ETAPE 1 : on travaille sur une copie pour ne pas modifier le DataFrame d'origine
    df = df.copy()

    # Projection locale en mètres (suffisant à l'échelle d'une ville)
    lat0 = df["latitude"].mean()
    x = df["longitude"] * 111320 * np.cos(np.radians(lat0))
    y = df["latitude"] * 110540
    coordonnees = np.column_stack([x, y])

    # ETAPE 2 : on extrait les coordonnees pour le KMeans
    #coordonnees = df[["latitude", "longitude"]]

    # Parametre pour le Kmeans constrained : pour avoir des equipes équilibrées 
    n_total = len(df)
    taille_min = n_total // n_equipes - 4
    taille_max = int(np.ceil(n_total / n_equipes)) + 2 # ceil : pour arrondir au sup

    # garde fou du taille_max 
    if taille_max * n_equipes < n_total:
        raise ValueError(
            f"Contraintes infaisables : {n_total} points, {n_equipes} equipes, "
            f"taille_max={taille_max} -> capacite max {taille_max * n_equipes}"
        )

    # Model kmeans avec les contraintes : 
    kmeans = KMeansConstrained(
        n_clusters=n_equipes,
        size_min=max(taille_min, 1),
        size_max=taille_max,
        random_state=1479
    )


    # ETAPE 3 : on cree le modele KMeans avec n_equipes groupes
    # random_state fixe pour que le resultat soit reproductible
    kmeans2 = KMeans(n_clusters=n_equipes, random_state=1479, n_init=10)

    # ETAPE 4 : on assigne le numero d'equipe a chaque intersection
    # les numeros commencent a 0, on ajoute 1 pour commencer a 1
    df["equipe"] = kmeans.fit_predict(coordonnees) + 1


    
    # PARTIE INUTILE A PRESENT, SEULEMENT GARDEE AU CAS OU 
    '''
        # ETAPE 5 : on calcule la distance de chaque intersection au point de rassemblement
        # cette distance servira uniquement a trier l'ordre de visite
        df["dist_meetup"] = df.apply(
            lambda row: geodesic(
                (row["latitude"], row["longitude"]),
                (meetup_lat, meetup_long)
            ).km,
            axis=1
        )

        # ETAPE 6 : on trie par equipe puis par distance au point de rassemblement
        df = df.sort_values(by=["equipe", "dist_meetup"]).reset_index(drop=True)

        # ETAPE 7 : on numerote les intersections au sein de chaque equipe en partant de 1
        df["ordre"] = df.groupby("equipe").cumcount() + 1

        # ETAPE 8 : on supprime la colonne temporaire dist_meetup
        df = df.drop(columns=["dist_meetup"])
    '''

    return df