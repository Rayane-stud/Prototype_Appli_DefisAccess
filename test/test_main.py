import routage
import nettoyage
import proximite 
import export

from pathlib import Path

BASE_DIR = Path(__file__).parent                           # dossier du fichier .py courant
csv_path = BASE_DIR / "data" / "intersection-92.csv"
xlsx_path_lieux = BASE_DIR / "data" / "intersection-92.csv"

tableau_nettoye = nettoyage.charger_intersections(csv_path)
tableau_nettoye = nettoyage.filtrer_intersections(nettoyage.doublons_intersections(nettoyage.normailisation_intersections(nettoyage.correction_intersections(tableau_nettoye))))

tableau_villes = proximite.charger_points(xlsx_path_lieux)
"""
ATTENTE DU FICHIER PROXIMITE POUR OBTENIR LE TABLEAU FINAL
"""





