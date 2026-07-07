"""
On effectue la comparaisons de l'éfficacité des differentes sources ici

Faire en fonction de 2 fichier ou 3 fichier

avec index, pour indiquer quel fichier sort quelle ligne
"""
import pandas as pd
from geopy.distance import geodesic
import io


def comparaison_code(fichier1, nom_fichier1, nom_fichier2, rayon =10):
    
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

def lire_fichier_benevole(fichier_benevole):
    with open(fichier_benevole, encoding="utf-8-sig") as f:
        lignes_brutes = f.readlines()

    header = lignes_brutes[0].strip()
    
    lignes_nettoyees = [header]
    for ligne in lignes_brutes[1:]:
        ligne = ligne.strip()
        if ligne.startswith('"') and ligne.endswith('"'):
            ligne = ligne[1:-1]
        ligne = ligne.replace('""', '"')
        lignes_nettoyees.append(ligne)

    contenu_propre = "\n".join(lignes_nettoyees)
    fichref = pd.read_csv(io.StringIO(contenu_propre))
    return fichref

def comparaison_IRL(fichier_benevole, fichier_osm, fichier_IA, rayon=10):
    
    fichref = lire_fichier_benevole(fichier_benevole)
    fichier1 = pd.read_csv(fichier_osm, sep=";", encoding="utf-8-sig")
    fichier2 = pd.read_csv(fichier_IA, sep=";", encoding="utf-8-sig")

    # Garder uniquement la ligne avec le plus grand nombre de traversées par coordonnées
    fichref = (fichref.sort_values("traversee", ascending=False).drop_duplicates(subset=["coordonnees"], keep="first"))
    fichref[["latitude", "longitude"]] = (fichref["coordonnees"].astype(str).str.split(",", expand=True))
    fichref["latitude"] = pd.to_numeric(fichref["latitude"])
    fichref["longitude"] = pd.to_numeric(fichref["longitude"])


    fichref=fichref.to_dict("records")
    fich1=fichier1.copy().to_dict("records")
    fich2=fichier2.to_dict("records")
    
    nom1 = "Fichier OSM"
    nom2 = "Fichier IA"

    egaux = []
    diff= []

    for ref in fichref:
        meilleur1 = None
        meilleur2 = None

        # Recherche de l'intersection dans le fichier osm
        for i in fich1:
            dist = geodesic(
                (ref["latitude"], ref["longitude"]),
                (i["latitude"], i["longitude"])
                ).meters

            if dist < rayon:
                meilleur1 = i

        # Recherche de l'intersection dans le fichier IA
        for j in fich2:
            dist = geodesic(
                (ref["latitude"], ref["longitude"]),
                (j["latitude"], j["longitude"])
            ).meters

            if dist < rayon:
                meilleur2 = j

        # Comparaison des nombres de traversées
        egal1 = (meilleur1 is not None and ref["nb_traversee_reel"] == meilleur1["nb_traversees"])
        egal2 = (meilleur2 is not None and ref["nb_traversee_reel"] == meilleur2["nb_traversees"])

        ligne_ref = ref.copy()
        ligne_ref["source"] = "Référence"

        # EGAUX
        if egal1 or egal2:
            egaux.append(ligne_ref)
            if egal1:
                ligne1 = meilleur1.copy()
                ligne1["source"] = nom1
                egaux.append(ligne1)

            if egal2:
                ligne2 = meilleur2.copy()
                ligne2["source"] = nom2
                egaux.append(ligne2)

            egaux.append({})


        # DIFFERENTS
        if (not egal1) or (not egal2):
            diff.append(ligne_ref)
            if meilleur1 is not None and not egal1:
                ligne1 = meilleur1.copy()
                ligne1["source"] = nom1
                diff.append(ligne1)

            if meilleur2 is not None and not egal2:
                ligne2 = meilleur2.copy()
                ligne2["source"] = nom2
                diff.append(ligne2)

            diff.append({})

    
    df_egaux = pd.DataFrame(egaux)
    df_diff = pd.DataFrame(diff)

    colonnes_voulues = [
        "latitude",
        "longitude",
        "intersection",
        "source",
        "nb_traversee_reel",
        "nb_traversees"
    ]
    df_egaux = df_egaux[colonnes_voulues]
    df_diff = df_diff[colonnes_voulues]
   
    fichier_sortie = "data/output/comparaisons/comparaison_terrain.xlsx"
    with pd.ExcelWriter(fichier_sortie) as writer:

        df_egaux.to_excel(
            writer,
            sheet_name="Egaux",
            index=False
        )

        df_diff.to_excel(
            writer,
            sheet_name="Differents",
            index=False
        )
    return


ville=input("Veuillez donnée le nom de la ville :").lower()

fichier_benevole="data/raw/comparaisons/fiches_excell_montrouge_equipe3.csv"
nom_fichier1="data/raw/comparaisons/"+ville+"pp_osm.csv"
nom_fichier2="data/raw/comparaisons/"+ville+"IA.csv"

comparaison_IRL(fichier_benevole, nom_fichier1, nom_fichier2)