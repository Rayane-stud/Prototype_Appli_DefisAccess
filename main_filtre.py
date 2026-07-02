"""
FICHIER : main_filtre.py

# BUT : Variante console de main.py qui pilote le pipeline complet de génération
      des feuilles terrain DEFIACCESS, avec les filtres affinés développés dans
      identification_PM.py et telecharger_intersections.py :
        - choix des intersections par combinaison exacte de types de voies
          (Rue/Avenue, Rue/Rue, Avenue/Boulevard...) au lieu d'un filtre par
          type "large" appliqué indépendamment à chaque segment
        - choix des catégories d'établissements de santé FINESS (Hôpitaux,
          Cliniques, Laboratoires, Centres de santé, Autres)
        - choix des types d'écoles (Maternelles, Élémentaires, Collèges,
          Lycées, Autres)

      main.py n'est pas modifié, pour ne pas changer son comportement existant
      (les deux scripts peuvent être lancés indépendamment).

LOGIQUE GLOBALE :
    Nom de ville saisi en console
        ↓
    1. Vérification qu'une analyse n'existe pas déjà pour cette ville
       (verifier_analyse_existante) — proposition de la réutiliser
        ↓
    2. Téléchargement des intersections de la commune
       (telecharger_intersections.telecharger_intersections_ville)
        ↓
    3. Construction du fichier PM (lieux d'intérêt), avec choix interactif des
       catégories santé / écoles / OSM (identification_PM.construire_dataframe_PM_avec_filtres)
        ↓
    4. Nettoyage des anciennes analyses pour ne pas saturer le disque
       (nettoyer_anciennes_villes)
        ↓
    5. Chargement des intersections avec choix interactif des combinaisons de
       types de voies (telecharger_intersections.charger_en_dataframe_avec_combinaisons)
        ↓
    6. Filtrage géographique des intersections proches d'un lieu d'intérêt (proximite)
        ↓
    7. Détection des passages piétons via YOLO (IA_PP)
        ↓
    8. Calcul des itinéraires par équipe et export des feuilles terrain Excel (routage, export)

LISTE DES FONCTIONS :

- main() :
    # ROLE : Orchestre tout le pipeline, du téléchargement des données à l'export
              des feuilles terrain
    # ARGUMENTS : "rdv_lat", "rdv_long" de type float, "nb_equipes" de type int,
                  "ville" de type str
    # REPONSE : list[str] des chemins des fichiers Excel générés, ou None/[] en cas d'échec

- _normaliser() :
    # ROLE : Normaliser un nom de ville pour comparer deux orthographes
              (tirets et underscores traités comme des espaces)
    # ARGUMENTS : "texte" de type str
    # REPONSE : str normalisé

- _rmtree_force() :
    # ROLE : Supprimer un dossier et son contenu en forçant les permissions
              (utile sur Windows/OneDrive où certains fichiers sont en lecture
              seule), en ignorant avec un avertissement les fichiers verrouillés
              (ex: ouverts dans Excel)
    # ARGUMENTS : "path" (str ou Path)
    # REPONSE : None

- nettoyer_anciennes_villes() :
    # ROLE : Supprimer les données (PM, images IA, fiches équipes) des villes
              les plus anciennes quand le nombre de villes analysées dépasse
              la limite fixée, pour ne pas saturer le disque
    # ARGUMENTS : "base_dir" de type Path, "garder" de type int (nombre d'analyses à conserver)
    # REPONSE : None

- verifier_analyse_existante() :
    # ROLE : Vérifier si une analyse existe déjà pour une ville et lister les
              dossiers de résultats correspondants
    # ARGUMENTS : "ville" de type str
    # REPONSE : list[str] des chemins des analyses existantes (vide si aucune)
"""

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
    # Version "filtres" : laisse choisir Hôpitaux/Cliniques/Laboratoires/... et
    # les types d'écoles au lieu de toujours tout inclure (cf. construire_dataframe_PM_avec_filtres)
    nomFich = identification_PM.exporter_PM_excel(
        identification_PM.construire_dataframe_PM_avec_filtres(ville),
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
        # Version "combinaisons" : demande Rue/Avenue, Rue/Rue... au lieu du
        # filtre par type simple de main.py (cf. charger_en_dataframe_avec_combinaisons)
        tableau_nettoye = telecharger_intersections.charger_en_dataframe_avec_combinaisons(fichiers[0])
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
        BASE_DIR / "data" / "raw" / "images_pp" / f"images_{ville}_{datetime.now().strftime('%d-%m-%Y_%Hh%M')}"
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


def _rmtree_force(path):
    # Sur Windows/OneDrive, certains fichiers sont en lecture seule → on force les permissions avant suppression
    # Si un fichier est verrouillé (ouvert dans Excel), on l'ignore avec un avertissement
    def _on_error(func, p, _):
        try:
            os.chmod(p, 0o777)
            func(p)
        except PermissionError:
            print(f"  Avertissement : impossible de supprimer '{Path(p).name}' (fichier ouvert). Fermez Excel et relancez pour nettoyer.")
    shutil.rmtree(path, onerror=_on_error)


def nettoyer_anciennes_villes(base_dir: Path, garder: int = 2):
    """
    Supprime les données (PM + images_pp + fiches_equipes) des villes les plus
    anciennes quand le nombre de villes dépasse `garder`.
    Le tri se fait par date de modification du fichier PM_{ville}.xlsx.
    """
    dossier_pm     = base_dir / "data" / "raw" / "PM"
    dossier_images = base_dir / "data" / "raw" / "images_pp"
    dossier_fiches = base_dir / "data" / "output" / "fiches_equipes"

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

        # images_pp : dossiers nommés "images_{ville}_{date}"
        # _normaliser convertit les underscores en espaces, donc on compare
        # "images garches 29 06 2026 14h30" avec le préfixe "images garches "
        prefix_images = "images " + _normaliser(ville_ancienne) + " "
        if dossier_images.exists():
            for dossier in dossier_images.iterdir():
                if dossier.is_dir() and _normaliser(dossier.name).startswith(prefix_images):
                    _rmtree_force(dossier)
                    print(f"  Nettoyage — supprimé : {dossier.name}")

        # fiches_equipes : dossiers nommés "{ville}_{horodatage}"
        # ex. "Garches_20250625_143022" → normalisé "garches 20250625 143022"
        prefix_fiches = _normaliser(ville_ancienne) + " "
        if dossier_fiches.exists():
            for dossier in dossier_fiches.iterdir():
                if dossier.is_dir() and _normaliser(dossier.name).startswith(prefix_fiches):
                    _rmtree_force(dossier)
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