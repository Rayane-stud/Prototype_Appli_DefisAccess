import sys   #bibliothèque pour manipuler les chemins d'accès aux fichiers
import os    #idem
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src')) # ajoute un chemin à la liste des endroits 
                                                                      # où python cherche ses modules

# import des fiichiers du src
import routage
import nettoyage
import proximite 
import export
import numpy as np

from pathlib import Path

#_________________PARAMETRES_____________________________________________________________________________________
# Demande à l'utilisateur le nom de la ville et convertit en minuscules pour éviter les erreurs de saisie
ville = input("Choisissez le nom de la ville sur laquelle vous voulez travailler : ").lower()
# Définit le dossier de base à partir de l'emplacement du fichier courant
BASE_DIR = Path(__file__).parent
# Sélectionne le fichier CSV selon la ville choisie
if ville == "garches":
    csv_path = BASE_DIR.parent / "data" / "raw" / "garches.csv"          # fichier spécifique à Garches
else:
    csv_path = BASE_DIR.parent / "data" / "raw" / "intersections-92.csv" # fichier général des intersections du 9
# Chemin vers le fichier des lieux de Garches (commun aux deux cas)
xlsx_path_lieux = BASE_DIR.parent / "data" / "raw" / "garches_lieu.xlsx"
#________________________________________________________________________________________________________________


def main():
    return None