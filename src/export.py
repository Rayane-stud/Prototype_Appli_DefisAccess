"""
FICHIER contenant la logique metier gerant l'etape 5 :
# BUT :
- Generation des feuilles terrain XLSX pour que les benevoles puissent
remplir les questionnaires

# LISTE DES FONCTIONS:
- duplication_lignes():
    # ROLE : Dupliquer les lignes pour chaque intersection
              par les n nb_traversees + ajout d'une colonne traversee
    # ARGUMENTS : "df" de type DataFrame
    # REPONSE : pd.DataFrame avec duplication des lignes et une colonne traversee

- ajouter_col_notation_terrain():
    # ROLE : Ajouter les colonnes de saisie vides que les benevoles
              rempliront sur le terrain pour chaque passage
              (bande_de_guidage, bande_eveil, feu_parlant, commentaire)
    # ARGUMENTS : "df" de type DataFrame
    # REPONSE : pd.DataFrame avec 4 nouvelles colonnes vides de type None

- vers_xlsx():
    # ROLE : Exporter le DataFrame d'une equipe en fichier XLSX formate
              et lisible sur le terrain
    # ARGUMENTS : "df" de type DataFrame
                  "id_equipe" de type int (numero de l'equipe ex: 1, 2, 3...)
                  "dossier_sortie" de type str (chemin du dossier ou sauvegarder le fichier)
    # REPONSE : str (chemin complet du fichier XLSX genere)

- exporter_toutes_equipes():
    # ROLE : Appliquer vers_xlsx() pour chaque equipe du dictionnaire
              et recuperer la liste de tous les fichiers generes
              (utile pour creer le ZIP Streamlit)
    # ARGUMENTS : "dict_equipes" de type dict {int : DataFrame}
                  (cle = id equipe, valeur = DataFrame de l equipe)
                  "dossier_sortie" de type str (chemin du dossier de sortie)
    # REPONSE : list[str] (liste des chemins de tous les fichiers XLSX generes)

- export_final_equipes():
    # ROLE : Orchestrer les 3 etapes (duplication, ajout colonnes, export xlsx)
              pour chaque equipe en une seule fonction
    # ARGUMENTS : "dict_equipes" de type dict {int : DataFrame}
                  (cle = id equipe, valeur = DataFrame de l equipe)
                  "dossier_sortie" de type str (chemin du dossier de sortie)
    # REPONSE : list[str] (liste des chemins de tous les fichiers XLSX generes)
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime



'''ATTTENNNTIONNNNNNNNNNNNNNN A LA METHODE PROVISOIRE PR LE NB TRAVERSEES'''
# FONCTION : duplication_lignes ------------------------------------------------

def duplication_lignes(df):
    # ETAPE 1 : on verifie que la colonne nb_traversees existe
    # si absente on arrete avec un message clair plutot qu'une erreur cryptique
    if "nb_traversees" not in df.columns:
        print("La colonne 'nb_traversees' est absente du DataFrame.")
        raise ValueError("La colonne 'nb_traversees' est absente du DataFrame.")

    # ETAPE 2 : on duplique chaque ligne selon le nb de passages pietons (nb_traversees)
    # df.index recupere la liste des numeros de lignes du tableau
    # .repeat() repete chaque numero d'index autant de fois que nb_traversees
    # .loc[repeat_idxs] va chercher dans le tableau les lignes correspondantes
    # .reset_index(drop=True) remet les index proprement de 0 a N, drop=True jette les anciens
    repeat_idxs = df.index.repeat(df["nb_traversees"])
    df_developpe = df.loc[repeat_idxs].reset_index(drop=True)

    # ETAPE 3 : on numerote chaque passage pieton pour un meme croisement
    # .groupby("Intersection", sort=False) regroupe les lignes par nom de croisement
    # sort=False preserve l'ordre original sans retrier par ordre alphabetique
    # .cumcount() numerote les occurrences en partant de 0
    # +1 car Python commence a 0 alors que Stata commence a 1
    df_developpe["traversee"] = (
        df_developpe.groupby("intersection", sort=False).cumcount() + 1
    )

    # ETAPE 4 : on supprime nb_traversees qui ne sert plus
    # et on reordonne les colonnes comme dans le Stata
    # en Stata : "keep Equipe Coordonnees Intersection Ordre traversee"
    df_developpe = df_developpe[["equipe", "coordonnees", "intersection", "ordre", "traversee"]]

    # ETAPE 5 : on trie comme dans le Stata
    # en Stata : "sort Ordre Intersection traversee"
    # .reset_index(drop=True) remet les index dans l'ordre apres le tri
    df_developpe = df_developpe.sort_values(
        ["ordre", "intersection", "traversee"]
    ).reset_index(drop=True)

    return df_developpe


# FONCTION : ajouter_col_notation_terrain() ------------------------------------

def ajouter_col_notation_terrain(df):
    # ETAPE 1 : on fait une copie du tableau pour ne pas modifier l'original
    df_terrain = df.copy()

    # ETAPE 2 : on ajoute les 4 colonnes de saisie avec None comme valeur par defaut
    # None en Python = "." en Stata (valeur manquante)
    # le benevole les remplira a la main sur le terrain
    # en Stata : "gen bande_de_guidage=." etc.
    
    # ARTTTTENNNNTTTTIIIIIOOOONNNNNNNNNNNNNNNNNNNNNNNNNNNNN
    df_terrain["bande_de_guidage"] = None
    df_terrain["bande_eveil"] = None
    df_terrain["feu_parlant"] = None
    df_terrain["commentaire"] = None

    return df_terrain


# FONCTION : vers_xlsx() -------------------------------------------------------

def vers_xlsx(df, id_equipe, dossier_sortie, ville="Garches"):
    nom_fichier = f"{ville}_Equipe_{id_equipe}_feuille.xlsx"

    # ETAPE 2 : on construit le chemin complet du fichier (nom + adresse)
    # os.path.join colle le dossier et le nom de fichier avec le bon separateur
    # "/" sur Mac/Linux et "\" sur Windows
    chemin_fichier = os.path.join(dossier_sortie, nom_fichier)

    # ETAPE 3 : on exporte le tableau en fichier XLSX
    # index=False : on n'exporte pas les numeros de lignes pandas
    # en Stata : "export excel using ... firstrow(variables) replace"
    df.to_excel(chemin_fichier, index=False)

    # ETAPE 4 : on retourne le chemin du fichier genere
    # utile pour export_final_equipes() qui accumule tous les chemins
    return chemin_fichier


def _creer_dossier_horodate(dossier_sortie, ville="Garches"):
    # ETAPE 1 : on génère un horodatage au format YYYYMMDD_HHMMSS
    # ex : "20250625_143022" → lisible, triable alphabétiquement, sans caractères spéciaux
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ETAPE 2 : on construit le nom du sous-dossier
    # ex : "Garches_20250625_143022"
    nom_dossier = f"{ville}_{horodatage}"

    # ETAPE 3 : on construit le chemin complet et on crée le dossier
    # exist_ok=True évite une erreur si le dossier existe déjà (normalement impossible
    # avec l'horodatage à la seconde, mais bonne pratique défensive)
    chemin_dossier = os.path.join(dossier_sortie, nom_dossier)
    os.makedirs(chemin_dossier, exist_ok=True)

    return chemin_dossier






# FONCTION : exporter_toutes_equipes() -----------------------------------------

def exporter_toutes_equipes(dict_equipes, dossier_sortie, ville="Garches"):
    
    dossier_export = _creer_dossier_horodate(dossier_sortie, ville)
    # ETAPE 1 : on cree une liste vide qui va accumuler les chemins de chaque fichier genere
    liste_chemins = []

    # ETAPE 2 : on boucle sur chaque equipe du dictionnaire
    # id_equipe = la cle (1, 2, 3...)
    # df_equipe = le tableau de cette equipe
    # .items() permet de recuperer en meme temps la cle et la valeur
    for id_equipe, df_equipe in dict_equipes.items():

        # ETAPE 3 : on appelle vers_xlsx() pour chaque equipe
        # qui cree le fichier XLSX et retourne son chemin
        chemin = vers_xlsx(df_equipe, id_equipe, dossier_export, ville)

        # ETAPE 4 : on ajoute le chemin du fichier genere a la liste
        liste_chemins.append(chemin)

    # ETAPE 5 : on retourne la liste de tous les chemins
    # utile pour creer le ZIP Streamlit avec tous les fichiers
    return liste_chemins


# FONCTION : export_final_equipes() --------------------------------------------

def export_final_equipes(dict_equipes, dossier_sortie, ville="Garches"):

    dossier_export = _creer_dossier_horodate(dossier_sortie, ville)
    # ETAPE 1 : on cree une liste vide qui va accumuler les chemins de chaque fichier genere
    liste_chemins = []

    # ETAPE 2 : on boucle sur chaque equipe du dictionnaire
    # id_equipe = la cle (1, 2, 3...)
    # df_equipe = le tableau de cette equipe
    # .items() permet de recuperer en meme temps la cle et la valeur
    for id_equipe, df_equipe in dict_equipes.items():

        # ETAPE 3 : on applique les 3 etapes dans l'ordre pour chaque equipe
        
        # df_equipe = duplication_lignes(df_equipe)
        
        df_equipe["coordonnees"] = df_equipe["latitude"].astype(str)+","+df_equipe["longitude"].astype(str)
        df_equipe = duplication_lignes(df_equipe)
        df_equipe = ajouter_col_notation_terrain(df_equipe)
       # df_equipe = df_equipe.drop(columns=["latitude", "longitude"])


        # ETAPE 4 : on appelle vers_xlsx() pour chaque equipe
        # qui cree le fichier XLSX et retourne son chemin
        chemin = vers_xlsx(df_equipe, id_equipe, dossier_export, ville)

        # ETAPE 5 : on ajoute le chemin du fichier genere a la liste
        liste_chemins.append(chemin)

    # ETAPE 6 : on retourne la liste de tous les chemins
    return liste_chemins