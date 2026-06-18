""""

OBJECTIF : Regrouper les croisement majeur , les filtrer par distance , supprimer les doublons  et exporter les resultats

# LISTE DES FONCTIONS:

-  charger_points():

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
from nettoyage import charger_intersections

 

POINT_PRINCIPAL = (48.8381857639848, 2.1865433360720927) # ce point correspond à la gare de Garches.

 

def charger_points(chemin: str):

    """Charge le fichier lieux.xlsx et retourne un DataFrame avec une ligne par points."""
    df = pd.read_excel(chemin) # permet de lire les fichiers excel
    df["latitude"] = df["coordonnees"].str.split(",").str[0].astype(float)
    df["longitude"] = df["coordonnees"].str.split(",").str[1].astype(float)

    return df  

 

def filtre_Distance (df_lieux, df_croisement, rayon_km: float = 0.2):
    dfL = df_lieux.copy()
    dfC = df_croisement.copy()
    dfC["pres_PM"] = False
   
    for nom, lieu in dfL.iterrows():
        #on recupere les coordonnées du point majeur
        lat=lieu["latitude"]
        long=lieu["longitude"]

        distance = dfC.apply(lambda croisement: geodesic((croisement["Latitude"], croisement["Longitude"]),(lat, long)).km,axis=1)

        #on garde les intersections a moins de 200 mètres des points majeurs
        dfC.loc[distance< rayon_km, "pres_PM"] = True

    #supprime la colonne pres_PM avec ses indice
    df = dfC[dfC["pres_PM"] == True].drop(columns=["pres_PM"]).reset_index(drop=True)

    return df

def fusion_croisement(df_Intersections, threshold_km: float = 0.03):
    df=df_Intersections.copy()
    
    df = df.sort_values(by=["Latitude", "Longitude"], ascending=False).reset_index(drop=True)
    df["intersection_n_1"] = df["Intersections"].shift(-1)
    df["Lat_n_1"] = df["Latitude"].shift(-1)
    df["Long_n_1"] = df["Longitude"].shift(-1)
   
    df["dist_inter"] = df.apply(
        lambda row: geodesic((row["Latitude"], row["Longitude"]), (row["Lat_n_1"], row["Long_n_1"])).km, axis=1)

    df["Intersections"] = df.apply(
        lambda row: row["Intersections"] + "/" + row["intersection_n_1"] and row["dist_inter"] < threshold_km, axis=1)

    df = df[~(df["dist_inter"].shift(1) < threshold_km)].reset_index(drop=True)
    df.drop(columns=["intersection_n_1", "Lat_n_1", "Long_n_1", "dist_inter"], inplace=True)

    return df

def assigner_equipes (df: pd.DataFrame, n_teams: int, meetup_lat: float, meetup_long: float):
    coordonnees = df[["latitude", "longitude"]]
    kmeans = KMeans(n_clusters=n_equipes, random_state=1479)
    df["Equipe"] = kmeans.fit_predict(coordonnees)
    df["dist_meetup"] = df.apply(lambda row: geodesic((row["latitude"], row["longitude"]),(meetup_lat, meetup_long)).km,axis=1)
    df = df.sort_values(by=["Equipe", "dist_meetup"]).reset_index(drop=True)
    df["Ordre"] = df.groupby("Equipe").cumcount() + 1
    df.drop(columns=["dist_meetup"], inplace=True)

    return df

#demander le nom de la commune
ville=input("Entrez le nom de la commune : ")
 
#demander le nom du fichier csv
nom = input("Entrez le nom du fichier CSV (sans l'extension .csv) : ")
path="data/raw/" + nom + ".csv"
Intersection=charger_intersections(path, ville)
print (Intersection)

chemin="data/raw/Garches lieux.xlsx"
df_lieux=charger_points(chemin: str)
df_croisement=fusion_croisement(Intersection, threshold_km=0.03)
df=filtre_Distance(df_lieux, df_croisement, rayon_km=0.2)

print(df)

 