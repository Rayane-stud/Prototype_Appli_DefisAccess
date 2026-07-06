"""
On effectue la comparaisons de l'éfficacité des differentes sources ici

Faire en fonction de 2 fichier ou 3 fichier

avec index, pour indiquer quel fichier sort quelle ligne
"""
import pandas as pd
from geopy.distance import geodesic

def recuperation_comp(fichier1, nom_fichier1, nom_fichier2, rayon =20):
    
    fichier2=pd.read_excel(nom_fichier2)
    fich1=fichier1.copy().to_dict("records")
    fich2=fichier2.to_dict("records")


    if nom_fichier1.contains("osm"):
        nom1= "Fichier OSM"
    elif nom_fichier1.contains("IA"):
        nom1= "Fichier IA"
    elif nom_fichier1.contains("mixte"):
        nom1= "Fichier MIXTE"
    
    if nom_fichier2.contains("osm"):
        nom1= "Fichier OSM"
    elif nom_fichier2.contains("IA"):
        nom1= "Fichier IA"
    elif nom_fichier2.contains("mixte"):
        nom1= "Fichier MIXTE"

    egaux = []
    diff= []

    for i in fich1:
        for j in fich2:
            dist=geodesic((i["latitude"],i["longitude"]),
                          (j["latitude"],j["longitude"])
                          ).meters
            if dist < rayon:

                if i["nb_pp"] == j["nb_pp"]:
                    ligne1 = i.copy()
                    ligne1["source"] = nom1

                    ligne2 = j.copy()
                    ligne2["source"] = nom2

                    egaux.append(ligne1)
                    egaux.append(ligne2)
                    egaux.append({})      # ligne vide

                else:
                    ligne1 = i.copy()
                    ligne1["source"] = nom1

                    ligne2 = j.copy()
                    ligne2["source"] = nom2

                    diff.append(ligne1)
                    diff.append(ligne2)
                    diff.append({})  # ligne vide

                break
    
    fichier_sortie="comparaison.xlsx"

    with pd.ExcelWriter(fichier_sortie) as writer:

        pd.DataFrame(egaux).to_excel(
            writer,
            sheet_name="Egaux",
            index=False
        )

        pd.DataFrame(diff).to_excel(
            writer,
            sheet_name="Differents",
            index=False
        )

    return