""""
OBJECTIF : Regrouper les croisement majeur , les filtrer par distance , supprimer les doublons  et exporter les resultats
# LISTE DES FONCTIONS:
-  charger_pois(): 
    #ROLE: charge le fichier lieux et retourne un dataFrame avec une ligne par point.
    #ARGUMENTS: path de type str
    #REPONSE: fichier df DataFrame avec une ligne par point
 
-  filtre_Distance(): 
    #ROLE: compare les distances entre les croisements etgarde uniquement ceux dont la distance est inférieure à 200 mètres

    #ARGUMENTS: "df" de type dataFrame point de type list et rayon_km de type float
    #REPONSE: fichier df DataFrame avec uniquement les croisements dont la distance est inférieure à 200 mètres 

 - fusion_croisement():
    # ROLE : fusionner les croisements espacées de moins de 30 mètres
    # ARGUMENTS : "df" de typeDataFrame, threshold_km de type float 
    # REPONSE : pd.DataFrame avec les croisement de moins de 30 mètres fusionnés 

- vers_xlsx():
    # ROLE : Exporter le DataFrame d'une equipe en fichier XLSX formate
              et lisible sur le terrain
    # ARGUMENTS : "df" de type DataFrame
                  "id_equipe" de type int (numero de l'equipe ex: 1, 2, 3...)
                  "dossier_sortie" de type str (chemin du dossier ou sauvegarder le fichier)
    # REPONSE : str (chemin complet du fichier XLSX genere)

- assigner_equipes():
    # ROLE : Appliquer un k-means sur les coordonnées pour répartir les intersections
          en N équipes et calculer l'ordre de passage au sein de chaque équipe
# ARGUMENTS : "df" de type DataFrame 
              "n_equipes" de type int 
              "meetup_lat" de type float 
              "meetup_long" de type float 
# REPONSE : pd.DataFrame (DataFrame avec les colonnes "Equipe" et "Ordre" ajoutées)
"""
import pandas as pd
import numpy as np
from geopy.distance import geodesic
from sklearn.cluster import KMeans

POINT_PRINCIPAL = (48.8381857639848, 2.1865433360720927) # ce point correspond à la gare de Garches.
Points_Majeur = [
    "MairiedeGarches", "MarchéSaintLouis", "MaternellePasteur",
    "MaternelleSaintExupéry", "MaternelleRamon", "ÉcoleélémentairePasteurA",
    "ÉcoleélémentairePasteurB", "ÉcoleélémentaireGastonRamon",
    "CollègeHenriBergson", "LycéeJeanMonnet", "LycéeJacquesBrel",
    "EcoleJeanPaulII", "GaredeGarches", "ÉgliseSaintLouis",
    "Synagogue", "HôpitalRaymondPoincaré", "Monoprix",
    "Franprix", "SupermarchéG20"
]

def charger_pois(chemin: str):
    """Charge le fichier lieux.xlsx et retourne un DataFrame avec une ligne par POI."""
    df = pd.read_excel(chemin)
    df["latitude"] = df["coordonnees"].str.split(",").str[0].astype(float)
    df["longitude"] = df["coordonnees"].str.split(",").str[1].astype(float)
    return df   

def filtre_Distance (df: pd.DataFrame, points: list, rayon_km: float = 0.2):
    df["pres_PM"] = 0
    for v in points:
        df[f"dist_{v}"] = df.apply(lambda row: geodesic((row["latitude"], row["longitude"]),(row[f"{v}_Lat"], row[f"{v}_Long"])).km,axis=1)
    df.loc[df[f"dist_{v}"] < rayon_km, "pres_PM"] = 1
    df.drop(columns=[f"{v}_Lat", f"{v}_Long", f"dist_{v}"], inplace=True)
    df = df[df["pres_PM"] == 1].drop(columns=["pres_PM"]).reset_index(drop=True)
    return df

def fusion_croisement (df: pd.DataFrame, threshold_km: float = 0.03): # cette fonction nous permet de concatener les croisements proches 
    df = df.sort_values(by=["latitude", "longitude"], ascending=True)
    df["intersection_n_1"] = df["intersection"].shift(-1)
    # Équivalent de : gen Lat_n_1 = latitude[_n+1]
    df["Lat_n_1"] = df["latitude"].shift(-1)

    # Équivalent de : gen Long_n_1 = longitude[_n+1]
    df["Long_n_1"] = df["longitude"].shift(-1)
    df["dist_inter"] = df.apply(
    lambda row: geodesic((row["latitude"], row["longitude"]),(row["Lat_n_1"], row["Long_n_1"])).km if pd.notna(row["Lat_n_1"]) else None,axis=1)
    return pd.DataFrame


def assigner_equipes (df: DataFrame, n_teams: int, meetup_lat: float, meetup_long: float):
    coordonnees = df[["latitude", "longitude"]]
    kmeans = KMeans(n_clusters=n_equipes, random_state=1479)
    df["Equipe"] = kmeans.fit_predict(coordonnees)
    df["dist_meetup"] = df.apply(lambda row: geodesic((row["latitude"], row["longitude"]),(meetup_lat, meetup_long)).km,axis=1)
    df = df.sort_values(by=["Equipe", "dist_meetup"]).reset_index(drop=True)
    df["Ordre"] = df.groupby("Equipe").cumcount() + 1
    df.drop(columns=["dist_meetup"], inplace=True)
    return df

def exporter_resultats ():
    return resultat

