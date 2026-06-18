import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

import routage
import nettoyage
import proximite 
import export

from pathlib import Path

#_________________PARAMETRES_____________________________________________________________________________________
rdv_lat = 0
rdv_long = 0
ville = "Garches"

BASE_DIR = Path(__file__).parent                           # dossier du fichier .py courant
csv_path = BASE_DIR.parent / "data" / "raw" / "intersections-92.csv"
xlsx_path_lieux = BASE_DIR.parent / "data" / "raw" / "garches_lieu.xlsx"
#________________________________________________________________________________________________________________

tableau_nettoye = nettoyage.charger_intersections(csv_path, ville)

tableau_villes = proximite.charger_points(xlsx_path_lieux)
tab_croisement = proximite.assigner_equipes(proximite.fusion_croisement(proximite.filtre_Distance(tableau_nettoye, tableau_villes)),5,rdv_lat,rdv_long)
"""
ATTENTE DU FICHIER PROXIMITE POUR OBTENIR LE TABLEAU FINAL
"""


dict_route_par_equipe = routage.route_toutes_equipes(tab_croisement,rdv_lat, rdv_long )
liste_chemins = export.export_final_equipes(dict_route_par_equipe,BASE_DIR.parent / "data" / "output")




