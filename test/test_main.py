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
rdv_lat = 0 #intialisation de la variable rdv_lat de type float
rdv_long = 0
ville = "Garches" #variable ville de type str

BASE_DIR = Path(__file__).parent                           # dossier du fichier .py courant
csv_path = BASE_DIR.parent / "data" / "raw" / "intersections-92.csv"   #chemin du fichier csv avec les intersections du 92
xlsx_path_lieux = BASE_DIR.parent / "data" / "raw" / "garches_lieu.xlsx"   #chemin du fichier xlsx avec les lieux de Garches
#________________________________________________________________________________________________________________

tableau_nettoye = nettoyage.charger_intersections(csv_path, ville) # appel le fichier nettoyage pour avoir un tableau clair et exploitable depuis le csv

tableau_villes = proximite.charger_points(xlsx_path_lieux)    # appel le fichier proximite pour avoir les coordonnées des points
tab_croisement = proximite.assigner_equipes(proximite.fusion_croisement(proximite.filtre_distance( tableau_villes,tableau_nettoye)),5,rdv_lat,rdv_long)
#appel des fonctions de proximité permettant d'assigner les intersections aux équipes en fonction de la distance avec les points d'intérêt + regrouper les PM en si très proches

"""
ATTENTE DU FICHIER PROXIMITE POUR OBTENIR LE TABLEAU FINAL
"""
# génération aléatoire d'un nombre de traversé par intersection allant de 1 à 5
tab_croisement["nb_traversees"] = np.random.randint(1, 5, size=len(tab_croisement)) #PAS BON DU TOUT C PROVISOIRE

#utilisation de des fonctions de routage afin de pouvoir avoir les routes optimales pour chaque équipe
#et les exporter dans un fichier csv en fonction des intersection qui leur sont attribuées
dict_route_par_equipe = routage.route_toutes_equipes(tab_croisement,rdv_lat, rdv_long )
#exportation des routes optimales pour chaque équipe dans un fichier csv
liste_chemins = export.export_final_equipes(dict_route_par_equipe,BASE_DIR.parent / "data" / "output")




