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
                  "ville" de type str, optionnel (defaut "Garches"), utilise
                  dans le nom du fichier genere
    # REPONSE : str (chemin complet du fichier XLSX genere)

- _creer_dossier_horodate():
    # ROLE : Creer un sous-dossier horodate (ex: "Garches_20250625_143022")
              dans le dossier de sortie, pour ranger les fichiers d'une
              meme generation sans ecraser les generations precedentes
    # ARGUMENTS : "dossier_sortie" de type str (dossier parent)
                  "ville" de type str, optionnel (defaut "Garches")
    # REPONSE : str (chemin complet du sous-dossier cree)

- exporter_toutes_equipes():
    # ROLE : Creer un sous-dossier horodate (_creer_dossier_horodate) puis
              appliquer vers_xlsx() pour chaque equipe du dictionnaire
              et recuperer la liste de tous les fichiers generes
              (utile pour creer le ZIP Streamlit)
    # ARGUMENTS : "dict_equipes" de type dict {int : DataFrame}
                  (cle = id equipe, valeur = DataFrame de l equipe)
                  "dossier_sortie" de type str (chemin du dossier de sortie)
                  "ville" de type str, optionnel (defaut "Garches")
    # REPONSE : list[str] (liste des chemins de tous les fichiers XLSX generes)

- export_final_equipes():
    # ROLE : Orchestrer les etapes (creation dossier horodate, calcul de la
              colonne coordonnees, duplication des lignes, ajout des colonnes
              de notation terrain, export xlsx) pour chaque equipe en une
              seule fonction
    # ARGUMENTS : "dict_equipes" de type dict {int : DataFrame}
                  (cle = id equipe, valeur = DataFrame de l equipe)
                  "dossier_sortie" de type str (chemin du dossier de sortie)
                  "ville" de type str, optionnel (defaut "Garches")
    # REPONSE : list[str] (liste des chemins de tous les fichiers XLSX generes)
"""
import os
import pandas as pd
import numpy as np
import xml.etree.ElementTree as ET
from pathlib import Path
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



def generer_kml_global_une_colonne(dict_equipes, nom_fichier_sortie="carte_globale_intersections.kml"):
    """
    GÉNÉRATEUR DE CARTE GOOGLE MY MAPS (FORMAT KML)
    
    Principe :
    Le format KML (Keyhole Markup Language) est un fichier XML structuré que Google Maps 
    comprend nativement. Cette fonction traduit un dictionnaire de DataFrames Python 
    en balises géographiques (<Placemark>, <Point>, <coordinates>) ordonnées.
    
    Utilité majeure :
    En créant des balises <Folder> (Dossiers), Google My Maps va automatiquement 
    créer un 'calque' (layer) par équipe avec une case à cocher. L'utilisateur pourra 
    masquer ou afficher les équipes d'un clic pour organiser ses itinéraires.
    
    Paramètres :
    ------------
    dict_equipes : dict
        Un dictionnaire où la clé est le nom de l'équipe (ex: "Équipe Nord") et la valeur 
        est son DataFrame contenant les intersections attribuées.
    nom_fichier_sortie : str
        Le nom du fichier .kml final qui sera généré.
    """
    
    # -------------------------------------------------------------------------
    # 1 INITIALISATION DE LA STRUCTURE DU FICHIER KML
    # -------------------------------------------------------------------------
    # Utilité : On crée la racine du document. La balise <kml> indique au système 
    # (comme Google Earth ou Google Maps) qu'il s'agit de données géographiques 
    # conformes au standard officiel (xmlns="...").
    kml = ET.Element('kml', xmlns="http://www.opengis.net/kml/2.2")
    
    # Utilité : Le <Document> est le conteneur principal à l'intérieur du KML. 
    # C'est dans ce conteneur que l'on va ranger nos dossiers et nos points.
    document = ET.SubElement(kml, 'Document')
    
    # Utilité : Definir le titre principal qui apparaitra en haut du menu 
    # de gauche lorsque l'utilisateur ouvrira sa carte sur Google My Maps.
    nom_carte = ET.SubElement(document, 'name')
    nom_carte.text = "DEFIACCESS - Toutes les Équipes"

    # -------------------------------------------------------------------------
    # 2 BOUCLE SUR CHAQUE ÉQUIPE (CRÉATION DES CALQUES INTERACTIFS)
    # -------------------------------------------------------------------------
    # Principe : On parcourt le dictionnaire équipe par équipe.
    for nom_equipe, df_equipe in dict_equipes.items():
        
        # Utilité : La balise <Folder> agit exactement comme un calque dans Google Maps.
        # Tout ce qui sera mis à l'intérieur de ce Folder appartiendra à cette équipe 
        # spécifique et possédera sa propre case à cocher [X] dans l'interface Google.
        folder = ET.SubElement(document, 'Folder')
        
        # Utilité : Donner le nom de l'équipe au calque (ex: "Équipe 1"). 
        # C'est ce texte qui apparaîtra à côté de la case à cocher.
        folder_name = ET.SubElement(folder, 'name')
        folder_name.text = str(nom_equipe)
        
        # ---------------------------------------------------------------------
        # 3 EXTRACTION ET CONVERSION DES COORDONNÉES DE CHAQUE INTERSECTION
        # ---------------------------------------------------------------------
        # Principe : On parcourt chaque ligne du tableau (DataFrame) de l'équipe actuelle.
        for idx, row in df_equipe.iterrows():
            
            # Securité & Utilité : On vérifie que la colonne 'coordonnee' existe sur la ligne 
            # et qu'elle n'est pas vide (pd.notna). Cela évite que le script ne plante si un 
            # champ est mal rempli dans la base de données.
            if hasattr(row, 'coordonnee') and pd.notna(row['coordonnee']):
                
                # Nettoyage : On transforme en texte et on retire les espaces superflus 
                # au début et à la fin (ex: " 48.85, 2.34 " devient "48.85,2.34")
                coord_str = str(row['coordonnee']).strip()
                
                try:
                    # Principe : Puisque la latitude et la longitude sont dans la même case séparées 
                    # par une virgule, on "coupe" la chaîne en deux morceaux distincts.
                    part1, part2 = coord_str.split(',')
                    
                    # ATTENTION / PIÈGE TECHNIQUE DU FORMAT KML :
                    # En cartographie standard (et dans Excel), on écrit souvent "Latitude, Longitude".
                    # MAIS le format KML de Google exige STRICTEMENT l'inverse : "Longitude, Latitude".
                    # Ici, on extrait en supposant que votre Excel est au format classique "Lat, Lon".
                    lat = float(part1.strip())
                    lon = float(part2.strip())
                    
                    # Note : Si l'Excel était déjà au format "Lon, Lat", il faudrait inverser :
                    # lon = float(part1.strip())
                    # lat = float(part2.strip())
                    
                    # ---------------------------------------------------------
                    # 4. CRÉATION DU MARQUEUR (PLACEMARK) SUR LA CARTE
                    # ---------------------------------------------------------
                    # Utilité : La balise <Placemark> représente le repère visuel (le pin/l'épingle) 
                    # qui va apparaître physiquement sur la carte de l'utilisateur.
                    placemark = ET.SubElement(folder, 'Placemark')
                    
                    # Utilité : Définir le nom spécifique du repère (ex: "Point 1", "Point 2").
                    # Ce texte s'affichera directement à côté de l'épingle sur la carte.
                    name = ET.SubElement(placemark, 'name')
                    name.text = f"Point {idx + 1}"
                    
                    # Utilité : La bulle d'information. Lorsque l'utilisateur cliquera sur l'épingle 
                    # dans Google Maps, une petite fenêtre s'ouvrira avec ce texte descriptif.
                    description = ET.SubElement(placemark, 'description')
                    description.text = f"Équipe : {nom_equipe}\nCoordonnées : {lat}, {lon}"
                    
                    # ---------------------------------------------------------
                    # 5. ENREGISTREMENT GÉOGRAPHIQUE DU POINT
                    # ---------------------------------------------------------
                    # Utilité : <Point> indique à Google qu'il s'agit d'un élément ponctuel (et non 
                    # d'une ligne ou d'un polygone).
                    point = ET.SubElement(placemark, 'Point')
                    
                    # Utilité : La balise <coordinates> stocke la position mathématique exacte.
                    # Règle KML absolue : format "Longitude,Latitude,Altitude". 
                    # On met l'altitude à 0 car nous travaillons à plat sur le sol.
                    coordinates = ET.SubElement(point, 'coordinates')
                    coordinates.text = f"{lon},{lat},0"
                    
                except ValueError:
                    # Sécurité & Utilité : Si une ligne contient du texte corrompu (ex: "Erreur_GPS" 
                    # ou une double virgule), le bloc `try` va échouer. Le `except ValueError` 
                    # intercepte l'erreur, ignore cette ligne défectueuse avec `continue` et passe 
                    # immédiatement au point suivant sans bloquer le reste de l'application.
                    continue
                
    # -------------------------------------------------------------------------
    # 6. ÉCRITURE ET SAUVEGARDE DU FICHIER FINAL
    # -------------------------------------------------------------------------
    # Utilité : On convertit toute notre structure d'arbre de balises XML en un véritable 
    # fichier texte informatique (.kml), encodé proprement en UTF-8 pour gérer les accents.
    tree = ET.ElementTree(kml)
    tree.write(nom_fichier_sortie, encoding='utf-8', xml_declaration=True)
    
    # Utilité : On renvoie le nom du fichier créé pour que la partie de votre code Streamlit 
    # qui s'occupe de faire le fichier ZIP sache quel fichier récupérer sur le disque.
    return nom_fichier_sortie