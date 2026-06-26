"""
Fonction :
    Charger Accident(path,ville):
        on importe le document pour le trier

        
idée :
    une fonction pour qui trie le dossier brute et garde seulement les accidents su passage piétons,
    peut importes la ville, il créer un tableau de référence qu'il met a jour 1 fois par mois

    Une fonction qui d'apres ce tableau de référence, vas trier en fonction de la ville puis 
    appelle une autre pour attribuer les passages piétons aux intersections correspondantes
"""

"""
Pour lié les 2 méthodes :
    - tri par intersections a 20m environ, puis ensuite on compare les coodronnées des pp a 5m environ 
        pour determiner lequel est le meme
"""

import pandas as pd
import csv
from geopy.distance import geodesic

import identification_PP as pp
from nettoyage import charger_intersections
from proximite import fusion_croisement 

def charger_accidents(path, ville):
    # charger le fichier CSV
    df = pd.read_csv(path, sep=";").copy()

    #on trie celon le nom de la ville
    col="commune"
    df_ville = df[df[col].str.contains(ville, case=False, na=False)]
    df_ville = df_ville.reset_index(drop=True)

    #on garde les colonnes souhaitées
    garde=["geo_point_2d","commune","adresse"
           ,"usager1","loc_usa1"
           ,"usager2","loc_usa2"
           ,"usager3","loc_usa3"
           ,"usager4","loc_usa4"
           ,"usager5","loc_usa5"
           ,"usager6","loc_usa6"]
    df_ville=df_ville[garde]

    tableau = df_ville.rename(columns={"geo_point_2d": "coordonnees",})

    tableau=trier_accidents(tableau)
    tableau=coordonnees_accident(tableau)

    
    return tableau

def trier_accidents(df_ville):
    #Trier par contient "Sur le passage piéton"
    #dans les colonnes : "AZ"=loc_usa1 , "BI"=loc_usa2 , "BR"=loc_usa3 , "CA"=loc_usa4 etc
    #Attention, passage pieton peut etre dans l'un mais pas dans les autres, 
    # donc ne pas trier à la suite à causes des pertes de données
    df = df_ville.copy()
    colonne=["loc_usa1","loc_usa2","loc_usa3","loc_usa4","loc_usa5","loc_usa6"]
    trie= df[colonne].apply(lambda col: col.str.contains("Sur le passage piéton"
                        , case=False, na=False)).any(axis=1)
    df= df[trie]
    df = df.reset_index(drop=True)

    return df


def coordonnees_accident(tableau, rayon=5):
    #on separe la longitude et la latitude en 2 colonnes distinctes
    #on traitre les doublons
    #On regroupe les accidents a moins de 5m

    df=tableau.copy()
    df[["latitude", "longitude"]] = (df["coordonnees"].str.split(",", expand=True))
    df = df.drop(columns=["coordonnees"])

    df["longitude"] = pd.to_numeric(df["longitude"])
    df["latitude"] = pd.to_numeric(df["latitude"])
    df= df.drop_duplicates(subset=["longitude", "latitude"],keep="first")

    lignes = df.to_dict("records")

    i = 0
    while i < len(lignes):
        j = i + 1
        while j < len(lignes):
            dist= geodesic((lignes[i]["latitude"], lignes[i]["longitude"]),
                (lignes[j]["latitude"], lignes[j]["longitude"])).meters
            
            if dist <= rayon:
                lignes.pop(j)
            else:
                j += 1
        i += 1

    df_final= pd.DataFrame(lignes)
    df_final = df_final.reset_index(drop=True)
    return df_final


def comparer_coordonnees(passage_pieton, intersection_retenue, rayon=30):
    #on compare les coordonnées des intersections avec celles des passage piétons
    #a qq metres pres et on ajoute le nb de passage pietons à l'intersections
    pp=passage_pieton.copy().to_dict("records")
    inter=intersection_retenue.copy().to_dict("records")

    for i in inter:
        nb=0
        x=0
        for j in pp:
            dist= geodesic((i["latitude"], i["longitude"])
                    ,(j["latitude"], j["longitude"])).meters

            if dist<=rayon:
                nb+=1
                x+=1
                i["latitude_pp"+str(x)]=j["latitude"]
                i["longitude_pp"+str(x)]=j["longitude"]
        i["nb_pp"]=nb
    
    inter = pd.DataFrame(inter)
    inter= inter[inter["nb_pp"] != 0]

    colonnes = ["latitude", "longitude", "intersection", "Ville/Commune", "nb_pp"]
    for col in inter.columns:
        if col not in colonnes:
            colonnes.append(col)
    inter = inter[colonnes]

    return inter


Ville= input("Entrez le nom de la ville : ")
#nomF = input("Entrez le nom du fichier (sans l'extension .csv) : ")
#path="data/raw/source_pp/accidents-corporels-de-la-circulation-routiere fichier entier.csv"
csv_path = "data/raw/intersections-92.csv"
intersections=charger_intersections(csv_path, Ville)

final=pp.main(Ville,intersections)
#tableau = charger_accidents(path, Ville)
#print (tableau.head)
#nettoyer=fusion_croisement(intersections)
#final=comparer_coordonnees(tableau, nettoyer)

final.to_csv(
    "data/output/passages_pietons"+Ville+".csv",
    sep=";", index=False, encoding="utf-8-sig")