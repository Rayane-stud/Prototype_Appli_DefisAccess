import sys   # bibliothèque pour interagir avec l'interpréteur Python
import os    # bibliothèque pour manipuler les chemins d'accès aux fichiers

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))  # ajoute le dossier src/ à la liste
                                                                       # des endroits où Python cherche ses modules
# Import des modules du src
import routage
import nettoyage
import proximite
import export
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

    
    BASE_DIR = Path(__file__).parent                           # dossier du fichier .py courant
    csv_path = BASE_DIR / "data" / "raw" / "intersections-92.csv"   #chemin du fichier csv avec les intersections du 92
    xlsx_path_lieux = BASE_DIR/ "data" / "raw" / (ville + "_lieux.xlsx")   #chemin du fichier xlsx avec les lieux de Garches

    try:
        # ── Chargement et nettoyage des données ────────────────────────────
        tableau_nettoye = nettoyage.charger_intersections(csv_path, ville)
        tableau_villes  = proximite.charger_points(xlsx_path_lieux)
    except Exception as e:
        print(f"Erreur lors du chargement des données : {e}")
        return []

    # ── Calcul de proximité et assignation aux équipes ─────────────────
    tab_croisement = proximite.assigner_equipes(
        proximite.fusion_croisement(
            proximite.filtre_distance(tableau_villes, tableau_nettoye)
        ),
        nb_equipes, rdv_lat, rdv_long
    )

    # ⚠️ Provisoire — nombre de traversées aléatoire, à remplacer
    tab_croisement["nb_traversees"] = np.random.randint(1, 5, size=len(tab_croisement))

    # ── Calcul des routes optimales et export ──────────────────────────
    dict_route_par_equipe = routage.route_toutes_equipes(tab_croisement, rdv_lat, rdv_long)
    liste_chemins = export.export_final_equipes(dict_route_par_equipe, BASE_DIR / "data" / "output")

    return liste_chemins


# Vérifie que ce fichier est exécuté directement (et non importé depuis un autre script)
if __name__ == "__main__":
    
    # Lance le pipeline complet avec les constantes définies en haut du fichier
    liste_chemins = main(RDV_LAT, RDV_LONG, NB_EQUIPES, ville = "Garches")
    
    # Affiche le nombre de fichiers générés (le \n ajoute une ligne vide avant pour aérer l'affichage)
    print(f"\n✅ Export terminé — {len(liste_chemins)} fichier(s) généré(s) :")
    
    # Parcourt la liste des chemins et affiche chacun d'eux
    for chemin in liste_chemins:
        print(f"   → {chemin}")  # affiche le chemin du fichier exporté