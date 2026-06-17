"""
FICHIER contenant la logique metier gerant l'etape 4 : "Calcul d'itinéraires"
- ordre de visite optimal
- un fichier par equipe 
- Le dataframe est deja nettoyé et filtré au prealable (etape 2 et 3), ici n'aura lieu que la logique de tri.

Liste des fonctions : 

A)- voisin_lePlus_proche(df, start_lat, start_long) : 
    Paramètres : 
        df : dataframe contenant les points à visiter
        start_lat : float : latitude du point de départ
        start_long : float : longitude du point de départ
    Retourne :
        df : dataframe contenant les points à visiter dans l'ordre optimal de visite
    ce que ca fait : 
        Algorithme du plus proche voisin depuis le point de rendez-vous ; ajoute une colonne Ordre indiquant la séquence de visite optimale
    objectif :
        - optimiser l'ordre de visite des points pour minimiser la distance totale parcourue

B)-  route_toutes_equipes(df, rdv_lat, rdv_long) :
    Paramètres :
        df : dataframe contenant les points à visiter
        rdv_lat : float : latitude du point de rendez-vous
        rdv_long : float : longitude du point de rendez-vous
    Retourne :
        dictionnaire : dictionnaire de dataframes, chacun contenant les points à visiter dans l'ordre optimal pour une équipe
    ce que ca fait :
        Applique nearest_neighbor() pour chaque équipe ; retourne un dictionnaire {equipe_id: DataFrame trié}
    objectif :
        - optimiser la répartition des points entre les équipes
        - minimiser la distance totale parcourue par toutes les équipes


Docu imports : 
    pandas : pour la manipulation des dataframes
    geodesic de geopy.distance : pour calculer les distances géodésiques entre deux points GPS
    KDTree de scipy.spatial : pour une recherche efficace du plus proche voisin ( optimisation de l'algorithme du plus proche voisin pour plus tard)

"""
#Imports : 
import pandas as pd
from geopy.distance import geodesic 
from scipy.spatial import KDTree
