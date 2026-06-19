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
# from nettoyage import charger_intersections


POINT_PRINCIPAL = (48.8381857639848, 2.1865433360720927)  # Gare de Garches


# FONCTION : charger_points() --------------------------------------------------

def charger_points(chemin):
    # ETAPE 1 : on charge l'Excel sans en-tete automatique
    # header=None signifie que pandas ne suppose pas que la 1ere ligne est un titre
    df = pd.read_excel(chemin, header=None)

    # ETAPE 2 : on extrait les lieux et les coordonnees directement par position
    # iloc[0, 1:] = ligne 0 (noms des lieux), toutes les colonnes sauf la 1ere ("Info")
    # iloc[1, 1:] = ligne 1 (coordonnees), toutes les colonnes sauf la 1ere
    lieux = df.iloc[0, 1:].values
    coordonnees = df.iloc[1, 1:].values

    # ETAPE 3 : on reconstruit un DataFrame propre avec les bonnes colonnes
    df_propre = pd.DataFrame({
        "lieu": lieux,
        "coordonnees": coordonnees
    })

    # ETAPE 4 : on supprime les lignes vides (colonnes Excel vides)
    df_propre = df_propre.dropna(subset=["coordonnees"])

    # ETAPE 5 : on extrait latitude et longitude depuis la colonne coordonnees
    # le format attendu est "48.838, 2.186" (virgule comme separateur)
    # .str.strip() supprime les espaces avant/apres pour eviter les erreurs de parsing
    df_propre["latitude"] = (
        df_propre["coordonnees"].astype(str).str.split(",").str[0].str.strip().astype(float)
    )
    df_propre["longitude"] = (
        df_propre["coordonnees"].astype(str).str.split(",").str[1].str.strip().astype(float)
    )

    return df_propre


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

    # ETAPE 2 : on extrait les coordonnees pour le KMeans
    coordonnees = df[["latitude", "longitude"]]

    # ETAPE 3 : on cree le modele KMeans avec n_equipes groupes
    # random_state fixe pour que le resultat soit reproductible
    kmeans = KMeans(n_clusters=n_equipes, random_state=1479)

    # ETAPE 4 : on assigne le numero d'equipe a chaque intersection
    # les numeros commencent a 0, on ajoute 1 pour commencer a 1
    df["equipe"] = kmeans.fit_predict(coordonnees) + 1

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

    return df