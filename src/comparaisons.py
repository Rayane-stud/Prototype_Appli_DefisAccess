"""
On effectue la comparaisons de l'éfficacité des differentes sources ici

Faire en fonction de 2 fichier ou 3 fichier

avec index, pour indiquer quel fichier sort quelle ligne
"""
import pandas as pd
from geopy.distance import geodesic
import io
import matplotlib.pyplot as plt


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

def calcul_pourcentage_erreur(valeur_reelle, valeur_estimee):
    if valeur_reelle == 0:
        if valeur_estimee == 0:
            return 0.0
        else:
            return None  # erreur non définie (division par zéro), à traiter à part
    return abs(valeur_estimee - valeur_reelle) / valeur_reelle * 100

"""
def histogramme_erreurs(fichier_benevole, fichier_source, nom_source, rayon=10):

    fichref = lire_fichier_benevole(fichier_benevole)
    fichier_src = pd.read_csv(fichier_source, sep=";", encoding="utf-8-sig")

    # Même nettoyage que dans comparaison_IRL
    fichref = (fichref.sort_values("traversee", ascending=False)
                       .drop_duplicates(subset=["coordonnees"], keep="first"))
    fichref[["latitude", "longitude"]] = fichref["coordonnees"].astype(str).str.split(",", expand=True)
    fichref["latitude"] = pd.to_numeric(fichref["latitude"])
    fichref["longitude"] = pd.to_numeric(fichref["longitude"])

    fichref = fichref.to_dict("records")
    fich_src = fichier_src.to_dict("records")

    resultats = []

    for ref in fichref:
        meilleur = None
        for i in fich_src:
            dist = geodesic(
                (ref["latitude"], ref["longitude"]),
                (i["latitude"], i["longitude"])
            ).meters
            if dist < rayon:
                meilleur = i

        # On ne garde que les points où une correspondance existe
        if meilleur is not None:
            ecart = meilleur["nb_traversees"] - ref["nb_traversee_reel"]
            resultats.append({
                "nb_traversee_reel": ref["nb_traversee_reel"],
                "nb_traversees_source": meilleur["nb_traversees"],
                "ecart": ecart
            })

    df = pd.DataFrame(resultats)

    if df.empty:
        print(f"Aucune correspondance trouvée entre {nom_source} et le fichier de référence.")
        return df

    # --- Graphique 1 : distribution des écarts (sur/sous-estimation) ---
    plt.figure(figsize=(10, 6))
    largeur_bins = range(int(df["ecart"].min()) - 1, int(df["ecart"].max()) + 2)
    plt.hist(df["ecart"], bins=largeur_bins, edgecolor="black", align="left")
    plt.xlabel(f"Écart (nb_traversées {nom_source} − nb_traversée réelle)")
    plt.ylabel("Nombre d'intersections")
    plt.title(f"Distribution des écarts entre {nom_source} et le terrain")
    plt.axvline(0, color="red", linestyle="--", label="Aucune erreur")
    plt.legend()
    plt.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"data/output/comparaisons/histogramme_ecarts_{nom_source}.png")
    plt.show()

    # --- Graphique 2 : nombre d'erreurs par valeur réelle de traversées ---
    df["est_une_erreur"] = df["ecart"] != 0
    synthese = df.groupby("nb_traversee_reel")["est_une_erreur"].agg(["sum", "count"]).reset_index()
    synthese.columns = ["nb_traversee_reel", "nb_erreurs", "nb_total"]

    plt.figure(figsize=(10, 6))
    plt.bar(synthese["nb_traversee_reel"], synthese["nb_erreurs"], color="orange", edgecolor="black")
    plt.xlabel("Nombre de traversées réel (terrain)")
    plt.ylabel(f"Nombre d'erreurs {nom_source}")
    plt.title(f"Nombre d'erreurs {nom_source} par nombre de traversées réel")
    plt.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"data/output/comparaisons/erreurs_par_traversee_{nom_source}.png")
    plt.show()

    return df
"""

def histogramme_depuis_sortie(fichier_sortie, nom_source, colonne_source="source"):

    # Lecture des deux feuilles et fusion
    df_egaux = pd.read_excel(fichier_sortie, sheet_name="Egaux")
    df_diff = pd.read_excel(fichier_sortie, sheet_name="Differents")
    df = pd.concat([df_egaux, df_diff], ignore_index=True)

    # On garde uniquement les lignes de la source demandée (ex: "Fichier IA")
    df_source = df[df[colonne_source] == nom_source].copy()

    # On retire les lignes sans écart valide (ex: lignes vides séparatrices)
    df_source = df_source.dropna(subset=["ecart"])

    if df_source.empty:
        print(f"Aucune donnée trouvée pour la source '{nom_source}' dans {fichier_sortie}.")
        return df_source

    # --- Graphique 1 : distribution des écarts (sur/sous-estimation) ---
    plt.figure(figsize=(10, 6))
    largeur_bins = range(int(df_source["ecart"].min()) - 1, int(df_source["ecart"].max()) + 2)
    plt.hist(df_source["ecart"], bins=largeur_bins, edgecolor="black", align="left")
    plt.xlabel(f"Écart (nb_traversées {nom_source} − nb_traversée réelle)")
    plt.ylabel("Nombre d'intersections")
    plt.title(f"Distribution des écarts entre {nom_source} et le terrain")
    plt.axvline(0, color="red", linestyle="--", label="Aucune erreur")
    plt.legend()
    plt.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"data/output/comparaisons/histogramme_ecarts_{nom_source}.png")
    plt.show()

    # --- Graphique 2 : nombre d'erreurs par valeur réelle de traversées ---
    df_source["est_une_erreur"] = df_source["ecart"] != 0
    synthese = (df_source.groupby("nb_traversee_reel")["est_une_erreur"]
                          .agg(["sum", "count"]).reset_index())
    synthese.columns = ["nb_traversee_reel", "nb_erreurs", "nb_total"]

    plt.figure(figsize=(10, 6))
    plt.bar(synthese["nb_traversee_reel"], synthese["nb_erreurs"], color="orange", edgecolor="black")
    plt.xlabel("Nombre de traversées réel (terrain)")
    plt.ylabel(f"Nombre d'erreurs {nom_source}")
    plt.title(f"Nombre d'erreurs {nom_source} par nombre de traversées réel")
    plt.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"data/output/comparaisons/erreurs_par_traversee_{nom_source}.png")
    plt.show()

    return df_source

def comparaison_IRL(fichier_benevole, fichier_osm, fichier_IA, rayon=10):
    
    fichref = lire_fichier_benevole(fichier_benevole)
    fichier1 = pd.read_csv(fichier_osm, sep=";", encoding="utf-8-sig")
    fichier2 = pd.read_csv(fichier_IA, sep=";", encoding="utf-8-sig")

    # Garder uniquement la ligne avec le plus grand nombre de traversées par coordonnées
    fichref["traversee"] = pd.to_numeric(fichref["traversee"], errors="coerce")
    idx = fichref.groupby("coordonnees")["traversee"].idxmax()
    fichref = fichref.loc[idx].reset_index(drop=True)
    print("nb_traversee_reel" in fichref.columns)

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

        erreur1 = None
        erreur2 = None
        if meilleur1 is not None:
            erreur1 = calcul_pourcentage_erreur(ref["nb_traversee_reel"], meilleur1["nb_traversees"])
        if meilleur2 is not None:
            erreur2 = calcul_pourcentage_erreur(ref["nb_traversee_reel"], meilleur2["nb_traversees"])

        ligne_ref = ref.copy()
        ligne_ref["source"] = "Référence"

        # EGAUX
        if egal1 or egal2:
            egaux.append(ligne_ref)
            if egal1:
                ligne1 = meilleur1.copy()
                ligne1["source"] = nom1
                ligne1["pourcentage_erreur"] = erreur1
                ligne1["ecart"]= meilleur1["nb_traversees"] - ref["nb_traversee_reel"]
                egaux.append(ligne1)

            if egal2:
                ligne2 = meilleur2.copy()
                ligne2["source"] = nom2
                ligne2["pourcentage_erreur"] = erreur2
                ligne2["ecart"]= meilleur2["nb_traversees"] - ref["nb_traversee_reel"]
                egaux.append(ligne2)

            egaux.append({})


        # DIFFERENTS
        if (not egal1) or (not egal2):
            diff.append(ligne_ref)
            if meilleur1 is not None and not egal1:
                ligne1 = meilleur1.copy()
                ligne1["source"] = nom1
                ligne1["pourcentage_erreur"] = erreur1
                ligne1["ecart"]= meilleur1["nb_traversees"] - ref["nb_traversee_reel"]
                diff.append(ligne1)

            if meilleur2 is not None and not egal2:
                ligne2 = meilleur2.copy()
                ligne2["source"] = nom2
                ligne2["pourcentage_erreur"] = erreur2
                ligne2["ecart"]= meilleur2["nb_traversees"] - ref["nb_traversee_reel"]
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
        "nb_traversees",
        "pourcentage_erreur",
        "ecart"
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
    return fichier_sortie


ville = input("Veuillez donnée le nom de la ville :").lower()

fichier_benevole = "data/raw/comparaisons/fiches_excell_montrouge_equipe3.csv"
nom_fichier1 = "data/raw/comparaisons/" + ville + "pp_osm.csv"
nom_fichier2 = "data/raw/comparaisons/" + ville + "IA.csv"

fichier_sortie = comparaison_IRL(fichier_benevole, nom_fichier1, nom_fichier2)

histogramme_depuis_sortie(fichier_sortie, "Fichier OSM")
histogramme_depuis_sortie(fichier_sortie, "Fichier IA")