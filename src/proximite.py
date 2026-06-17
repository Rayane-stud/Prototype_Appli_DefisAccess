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

    return pd.DataFrame


def supprimer_doublons ():
    return suppr_doublons

def division_zone ():
    return zone

def exporter_resultats ():
    return resultat

