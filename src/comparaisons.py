"""
On effectue la comparaisons de l'éfficacité des differentes sources ici

Faire en fonction de 2 fichier ou 3 fichier

avec index, pour indiquer quel fichier sort quelle ligne
"""
import pandas as pd
from geopy.distance import geodesic

def recuperation_comp(fichier1, nom_fichier1, nom_fichier2, rayon =10):
    
    fichier2 = pd.read_csv(nom_fichier2, sep=";", encoding="utf-8-sig")
    fich1=fichier1.copy().to_dict("records")
    fich2=fichier2.to_dict("records")


    if "osm" in nom_fichier1:
        nom1 = "Fichier OSM"
    elif "IA" in nom_fichier1:
        nom1 = "Fichier IA"
    elif "mixte" in nom_fichier1:
        nom1 = "Fichier MIXTE"

    if "osm" in nom_fichier2:
        nom2 = "Fichier OSM"
    elif "IA" in nom_fichier2:
        nom2 = "Fichier IA"
    elif "mixte" in nom_fichier2:
        nom2 = "Fichier MIXTE"

    egaux = []
    diff= []

    for i in fich1:
        for j in fich2:
            dist=geodesic((i["latitude"],i["longitude"]),
                          (j["latitude"],j["longitude"])
                          ).meters
            if dist < rayon:

                if i["nb_traversees"] == j["nb_traversees"]:
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
    
    fichier_sortie="data/output/comparaisons/comparaison.xlsx"

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