import sys   # bibliothèque pour interagir avec l'interpréteur Python
import os    # bibliothèque pour manipuler les chemins d'accès aux fichiers
import shutil

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))  # ajoute le dossier src/ à la liste
                                                                       # des endroits où Python cherche ses modules
# Import des modules du src
from datetime import datetime
import routage
import proximite
import export
import  identification_PM
import identification_PP as pp
import IA_PP
import telecharger_intersections
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

    # ── Téléchargement des intersections EN PREMIER ────────────────────
    # On valide la ville et on télécharge ses données AVANT de chercher les PMs,
    # pour ne pas faire de requêtes inutiles si la ville est introuvable ou le
    # téléchargement échoue. Les données locales déjà présentes sont réutilisées.
    fichiers = telecharger_intersections.telecharger_intersections_ville(ville)
    if not fichiers:
        print(f"  Données introuvables pour '{ville}'. Vérifiez le nom ou votre connexion.")
        return None

    # ── Récupération des PMs (seulement si la ville est valide) ────────
    nomFich = identification_PM.exporter_PM_excel(
        identification_PM.construire_dataframe_PM(ville),
        dossier_sortie=str(BASE_DIR / "data" / "raw"),
        nom_fichier=f"PM_{ville}.xlsx"
   )
    # None signifie que la ville n'a pas été trouvée sur geo.api.gouv.fr
    if nomFich is None:
        return None
    xlsx_path_lieux = Path(nomFich)  # on réutilise ce que la fonction a écrit

    nettoyer_anciennes_villes(BASE_DIR)

    try:
        # ── Chargement et nettoyage des données ────────────────────────────
        tableau_nettoye = telecharger_intersections.charger_en_dataframe(fichiers[0])
        tableau_villes  = proximite.charger_points(xlsx_path_lieux)
    except Exception as e:
        print(f"Erreur lors du chargement des données : {e}")
        return []

    # ── Calcul de proximité et assignation aux équipes ─────────────────
    tab_croisement = proximite.assigner_equipes(
        pp.main(ville,
        proximite.fusion_croisement(proximite.filtre_distance(tableau_villes, tableau_nettoye)))
        ,nb_equipes, rdv_lat, rdv_long)


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


def nettoyer_anciennes_villes(base_dir: Path, garder: int = 2):
    """
    Supprime les données (PM + images_pp) des villes les plus anciennes
    quand le nombre de villes dépasse `garder`.
    Le tri se fait par date de modification du fichier PM_{ville}.xlsx.
    """
    dossier_pm     = base_dir / "data" / "raw" / "PM"
    dossier_images = base_dir / "data" / "raw" / "images_pp"

    if not dossier_pm.exists():
        return

    fichiers_pm = sorted(
        [f for f in dossier_pm.iterdir()
         if f.is_file() and f.name.startswith("PM_") and f.suffix == ".xlsx"],
        key=lambda f: f.stat().st_mtime
    )

    while len(fichiers_pm) > garder:
        fichier = fichiers_pm.pop(0)
        ville_ancienne = fichier.stem[3:]  # enlève le préfixe "PM_"

        fichier.unlink()
        print(f"  Nettoyage — supprimé : {fichier.name}")

        if dossier_images.exists():
            for dossier in dossier_images.iterdir():
                if dossier.is_dir() and _normaliser(dossier.name).startswith(
                    "images_" + _normaliser(ville_ancienne) + "_"
                ):
                    shutil.rmtree(dossier)
                    print(f"  Nettoyage — supprimé : {dossier.name}")



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

        # None = ville non trouvée → message et on redemande
        if liste_chemins is None:
            print(f"\n La ville '{ville}' est introuvable.")
            print("   Vérifiez l'orthographe et réessayez (majuscules et tirets optionnels).\n")
            continue

        break  # ville valide, analyse terminée

    # Affiche le nombre de fichiers générés (le \n ajoute une ligne vide avant pour aérer l'affichage)
    print(f"\n Export terminé — {len(liste_chemins)} fichier(s) généré(s) :")

    # Parcourt la liste des chemins et affiche chacun d'eux
    for chemin in liste_chemins:
        print(f"   → {chemin}")  # affiche le chemin du fichier exporté