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

 

def charger_points(chemin):

    """Charge le fichier lieux.xlsx en ciblant directement les lignes par leur position."""
    # 1. On charge l'Excel SANS en-tête automatique
    df = pd.read_excel(chemin, header=None)
    
    # 2. On sait que la ligne 0 (index 0) = les noms ("Info", "Mairie de Garches"...)
    #    On sait que la ligne 1 (index 1) = les coordonnées ("coordonnees", "48.84...")
    
    # On extrait les lieux et les coordonnées directement depuis leurs positions brutes
    lieux = df.iloc[0, 1:].values         # Prend tout sauf la case "Info"
    coordonnees = df.iloc[1, 1:].values   # Prend tout sauf la case "coordonnees"
    
    # 3. On reconstruit un DataFrame tout neuf, propre et directement dans le bon sens !
    df_propre = pd.DataFrame({
        "lieu": lieux,
        "coordonnees": coordonnees
    })
    
    # 4. Sécurité : Nettoyage des lignes vides (ex: si une colonne Excel était vide)
    df_propre = df_propre.dropna(subset=["coordonnees"])
    
    # 5. Extraction de la latitude et de la longitude
    df_propre["latitude"] = df_propre["coordonnees"].astype(str).str.split(",").str[0].astype(float)
    df_propre["longitude"] = df_propre["coordonnees"].astype(str).str.split(",").str[1].astype(float)

    return df_propre



def filtre_Distance (df_lieux, df_croisement, rayon_km: float = 0.2):
    dfL = df_lieux.copy()
    dfC = df_croisement.copy()
    dfC["pres_PM"] = False
   
    for nom, lieu in dfL.iterrows():
        #on recupere les coordonnées du point majeur
        lat=lieu["latitude"]
        long=lieu["longitude"]

        distance = dfC.apply(lambda croisement: geodesic((croisement["latitude"], croisement["longitude"]),(lat, long)).km,axis=1)

        #on garde les intersections a moins de 200 mètres des points majeurs
        dfC.loc[distance< rayon_km, "pres_PM"] = True

    #supprime la colonne pres_PM avec ses indice
    df = dfC[dfC["pres_PM"] == True].drop(columns=["pres_PM"]).reset_index(drop=True)

    return df

def fusion_croisement(df_intersections, threshold_km: float = 0.03):
    df=df_intersections.copy()

    for i in range(len(df)):
        for j in range(i+1, len(df)):

            dist = geodesic(
                (df.loc[i,"latitude"], df.loc[i,"longitude"]),
            (df.loc[j,"latitude"], df.loc[j, "longitude"])
            ).km
            if dist <= threshold_km:
                df.loc[i,"intersections"]+="/"+df.loc[j,"intersections"]
                df.drop(j, inplace=True)
                df.reset_index(drop=True, inplace=True)
                
                #Peut etre necessaire de faire j-1 ici, car risque de sauté un case
    
    return df

def assigner_equipes (df: pd.DataFrame, n_equipes: int, meetup_lat: float, meetup_long: float):
    # Extrait uniquement les colonnes latitude et longitude pour le KMeans

    coordonnees = df[["latitude", "longitude"]]

    # Crée le modèle KMeans avec n_equipes groupes et une graine aléatoire fixe pour la reproductibilité
    kmeans = KMeans(n_clusters=n_equipes, random_state=1479)

    # Entraîne le KMeans et assigne le numéro d'équipe à chaque intersection
    df["equipe"] = kmeans.fit_predict(coordonnees)

    # Calcule la distance en km entre chaque intersection et le point de rassemblement
    df["dist_meetup"] = df.apply(lambda row: geodesic(
        (row["latitude"], row["longitude"]),  # coordonnées de l'intersection
        (meetup_lat, meetup_long)             # coordonnées du point de rassemblement
        ).km,axis=1)
    

    # Trie les intersections par équipe puis par distance au point de rassemblement
    df = df.sort_values(by=["equipe", "dist_meetup"]).reset_index(drop=True)

    # Numérote les intersections au sein de chaque équipe en commençant à 1
    df["ordre"] = df.groupby("equipe").cumcount() + 1
    df.drop(columns=["dist_meetup"], inplace=True)

    return df

'''
#demander le nom de la commune
ville=input("Entrez le nom de la commune : ")
 
#demander le nom du fichier csv
nom = input("Entrez le nom du fichier CSV (sans l'extension .csv) : ")
path="data/raw/" + nom + ".csv"
Intersection=charger_intersections(path, ville)
print (Intersection)

chemin="data/raw/Garches lieux.xlsx"
df_lieux=charger_points(chemin)
df_croisement=fusion_croisement(Intersection, threshold_km=0.03)
df=filtre_Distance(df_lieux, df_croisement, rayon_km=0.2)

print(df)
'''
 