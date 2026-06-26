import sys   # bibliothèque pour interagir avec l'interpréteur Python
import os    # bibliothèque pour manipuler les chemins d'accès aux fichiers

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))  # ajoute le dossier src/ à la liste
                                                                       # des endroits où Python cherche ses modules
# Import des modules du src
from datetime import datetime
import routage
import nettoyage
import proximite
import export
import  identification_PM
import IA_PP
import numpy as np

from pathlib import Path


# ──────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────

RDV_LAT    = 48.8381857639848  # latitude du point de rendez-vous (coordonnées fictives)
RDV_LONG   = 2.1865433360720927   # longitude du point de rendez-vous
NB_EQUIPES = 5        # nombre d'équipes


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main(rdv_lat: float, rdv_long: float, nb_equipes: int, ville: str):
    """
    Orchestre l'ensemble du pipeline :
      1. Sélection de la ville et des fichiers
      2. Chargement et nettoyage des données
      3. Calcul de proximité et assignation aux équipes
      4. Calcul des routes optimales et export

    Arguments :
        rdv_lat    : latitude du point de rendez-vous
        rdv_long   : longitude du point de rendez-vous
        nb_equipes : nombre d'équipes à constituer

    Retourne :
        liste des chemins vers les fichiers CSV exportés
    """
    # Définit le dossier de base à partir de l'emplacement du fichier courant
    BASE_DIR = Path(__file__).parent
    

    # ── Sélection des fichiers ──────────────────────────────────────────
    # Demande à l'utilisateur le nom de la ville et convertit en minuscules pour éviter les erreurs de saisie
    #ville = input("Choisissez le nom de la ville sur laquelle vous voulez travailler : ").lower()

    #if ville == "garches":
        #csv_path = BASE_DIR.parent / "data" / "raw" / "garches.csv"           # fichier spécifique à Garches
    #else:
        #csv_path = BASE_DIR.parent / "data" / "raw" / "intersections-92.csv"  # fichier général des intersections du 92

    #xlsx_path_lieux = BASE_DIR.parent / "data" / "raw" / "garches_lieu.xlsx   # fichier des lieux (commun aux deux cas)

    nomFich = identification_PM.exporter_PM_excel(
        identification_PM.construire_dataframe_PM(ville),
        dossier_sortie=str(BASE_DIR / "data" / "raw"),
        nom_fichier=f"{ville}_lieux.xlsx"
   )
    # None signifie que la ville n'a pas été trouvée sur geo.api.gouv.fr
    if nomFich is None:
        return None
    xlsx_path_lieux = Path(nomFich)  # on réutilise ce que la fonction a écrit

    BASE_DIR = Path(__file__).parent                           # dossier du fichier .py courant
    csv_path = BASE_DIR / "data" / "raw" / "intersections-92.csv"   #chemin du fichier csv avec les intersections du 92
    #xlsx_path_lieux = BASE_DIR/ "data" / "raw" / (ville + "_lieux.xlsx")   #chemin du fichier xlsx avec les lieux de Garches

    try:
        # ── Chargement et nettoyage des données ────────────────────────────
        tableau_nettoye = nettoyage.charger_intersections(csv_path, ville)
        tableau_villes  = proximite.charger_points(xlsx_path_lieux)
    except Exception as e:
        print(f"Erreur lors du chargement des données : {e}")
        return []

    # ── Calcul de proximité et assignation aux équipes ─────────────────
    tab_croisement = proximite.assigner_equipes(
        #on rajoute pp ici
            proximite.fusion_croisement(proximite.filtre_distance(tableau_villes, tableau_nettoye)),nb_equipes, rdv_lat, rdv_long)

    # ── Détection des passages piétons par YOLO ────────────────────────
    # on construit le chemin du dossier de sauvegarde des images annotées
    # le nom inclut la ville et la date au format français pour retrouver facilement l'analyse
    dossier_images = str(
        BASE_DIR / "data" / "output" / "images_pp" / f"images_{ville}_{datetime.now().strftime('%d-%m-%Y_%Hh%M')}"
    )
    # YOLO analyse chaque intersection et sauvegarde les images avec les bounding boxes dans le dossier
    # la colonne nb_traversees est ajoutée au tableau avec le nombre de passages piétons détectés
    tab_croisement = IA_PP.analyser_toutes_intersections(
        tab_croisement, col_lat="latitude", col_lon="longitude", dossier_images=dossier_images
    )

    # ── Calcul des routes optimales et export ──────────────────────────
    dict_route_par_equipe = routage.route_toutes_equipes(tab_croisement, rdv_lat, rdv_long)
    liste_chemins = export.export_final_equipes(
        dict_route_par_equipe,
        str(BASE_DIR / "data" / "output" / "fiches_equipes"),
        ville
    )
    return liste_chemins


# ──────────────────────────────────────────────
# VÉRIFICATION D'ANALYSE EXISTANTE
# ──────────────────────────────────────────────

def _normaliser(texte: str) -> str:
    # Traite tirets et espaces comme identiques pour comparer les noms de villes
    return texte.lower().replace("-", " ").replace("_", " ")



def verifier_analyse_existante(ville: str) -> list:
    """
    Cherche si une analyse a déjà été faite pour cette ville.
    Retourne la liste des dossiers de résultats existants (vide si aucun).
    """
    dossier_fiches = Path(__file__).parent / "data" / "output" / "fiches_equipes"
    if not dossier_fiches.exists():
        return []
    ville_norm = _normaliser(ville)
    # Un dossier par analyse, nommé "{ville}_{horodatage}"
    # On normalise pour que "Rueil Malmaison" == "Rueil-Malmaison"
    return sorted([
        str(d) for d in dossier_fiches.iterdir()
        if d.is_dir() and _normaliser(d.name).startswith(ville_norm + " ")
    ])


# Vérifie que ce fichier est exécuté directement (et non importé depuis un autre script)
if __name__ == "__main__":
    # Demande le nom de la ville à analyser — .strip() supprime les espaces accidentels en début/fin
    while True:
        ville = input("Nom de la ville à analyser : ").strip()

        # ── Vérification d'une analyse déjà existante ──────────────────────
        analyses_existantes = verifier_analyse_existante(ville)
        if analyses_existantes:
            print(f"\n  Une analyse existe déjà pour '{ville}' :")
            for dossier in analyses_existantes:
                print(f"   → {dossier}")
            reponse = input("\nVoulez-vous refaire une nouvelle analyse ? (o/n) : ").strip().lower()
            if reponse != "o":
                print(f"\nConservation de l'analyse existante. Aucune nouvelle analyse lancée.")
                exit(0)
            print()

        liste_chemins = main(RDV_LAT, RDV_LONG, NB_EQUIPES, ville=ville)

        # None = ville non trouvée sur geo.api.gouv.fr → message et on redemande
        if liste_chemins is None:
            print(f"\n❌ La ville '{ville}' est introuvable.")
            print("   Vérifiez l'orthographe et réessayez (majuscules et tirets optionnels).\n")
        continue

        break  # ville valide, analyse terminée

    # Affiche le nombre de fichiers générés (le \n ajoute une ligne vide avant pour aérer l'affichage)
    print(f"\n Export terminé — {len(liste_chemins)} fichier(s) généré(s) :")

    # Parcourt la liste des chemins et affiche chacun d'eux
    for chemin in liste_chemins:
        print(f"   → {chemin}")  # affiche le chemin du fichier exporté