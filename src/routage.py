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

        
C)- voisin_leplus_proche_pieton(df, start_lat, start_long, G):
    Paramètres : 
        df :  dataframe contenant tous les points que l'equipe doit visiter
        start_lat : (Float) latitude du point de depart initial de la tournée 
        start_long : (Float) longitude du pts de depart initial 
        G : (Graph) c'est la structure  de donnée qui conitnet les "itinéraires", la vraie carte de zone ( rues, trotoirs, parcs, escaliers)
    Retourne : 
        DataFrame : les memes data frame trié dans l'ordre optimal de la tournée avec une colonne supplémentaire ordre contenant des entiers croissant qui indiquent la sequence exaacte 
    Ce que ca fait : 
        appliquation du principe du plus proche voisin mais en utilisant la realité du terrain plutot que la geometrie 
        1- projette le pts de depart et les poitns du data frame sur le vrais reseau de pieton OpenStreetMap (G) 
        2- a partir de la position actuelle , elel calcule le temp de marche reelle a travers les rues trotoires et parcs pour atteindre chacun des points restants 
        3- selectionne le point le plus rapide d'ccès , m'ajoute a la liste des points visités et se depalce virtuellement sur ce point
        4- retir ce point de la liste des choix xrestants et repete l'opération jusqu'a ce que tous les points aient été planifiés 
        5- recontrstruit le dataframe numéroté de 1 a N 

        
Docu imports : 
    pandas : pour la manipulation des dataframes
    geodesic de geopy.distance : pour calculer les distances géodésiques entre deux points GPS
    KDTree de scipy.spatial : pour une recherche efficace du plus proche voisin ( optimisation de l'algorithme du plus proche voisin pour plus tard)

    osmnx : manipulation des graphes de reseaux routiers 
    networkx : manipulation des graphes 

"""


#Imports : 
import pandas as pd
from geopy.distance import geodesic 
from scipy.spatial import KDTree

import osmnx as ox
import networkx as nx 


'''
Entrée : 
    - df : dataframe contenant les points à visiter sous cette structure : latitude longitude intersection rue_1 rue_2 poi_proche distance_poi_km Equipe
    - start_lat : float : latitude du point de départ
    - start_long : float : longitude du point de départ
Sortie : 
    - df : dataframe contenant les points à visiter, avec une colonne supplémentaire "Ordre" indiquant la séquence de visite optimale
Description :
'''
def voisin_lePlus_proche_avec_rondeur(df, start_lat, start_long):

    intersections_restantes = df.copy()  # Crée une copie du dataframe pour éviter de modifier l'original
    intersections_visitées = []  # Liste pour stocker les intersections visitées dans l'ordre
    lat_actuelle, long_actuelle = start_lat, start_long  # Point de départ

    while not intersections_restantes.empty:
        #Calcul des distances : 
        intersections_restantes['distance_tempo'] = intersections_restantes.apply(     # Applique la fonction geodesic à chaque ligne du dataframe (evite une boucle for explicite)
            lambda row: geodesic(                                                      # lambda row: c'est pour definir une ligne "lambda", ca permet de pouvoir definir les manipulations "type" sur un ligne
                (lat_actuelle, long_actuelle), (row['latitude'], row['longitude'])     # deux points GPS entre lesquels geodisque calcule la distance 
                ).km, 
                axis=1   # Axis 1 c'est horizontalement, ca permet de dire que c'est les lignes et pas les colonnes qui sont parcourues.
            ) 
        
        # Trouver l'intersection la plus proche : 
        indice_proche = intersections_restantes['distance_tempo'].idxmin()  # Récupère l'index de la ligne avec la distance minimale
        intersection_proche = intersections_restantes.loc[indice_proche]  # Récupère la ligne correspondante à l'index trouvé


        #Enregistrer la visite et avancer : 
        intersections_visitées.append(indice_proche)

        lat_actuelle = intersection_proche['latitude']
        long_actuelle = intersection_proche['longitude']

        intersections_restantes = intersections_restantes.drop(indice_proche)

    #On reconstruit le dataFrame final : 
    df_ordonne = df.loc[intersections_visitées].copy()   # on copie le df et ordonnons les lignes grace aux indexes contenus dans la liste intersections visitées
    df_ordonne["ordre"] = range(1, len(df_ordonne) + 1)  # generer une suite de nombre croissante jusqu'au nombre de point et les stock dans la colonne ordre
    df_ordonne = df_ordonne.drop(columns=["distance_tempo"], errors="ignore") # suppression de la variable temporaire ( colone ) et ignore les erreures liées a si le dataset est vide


    return df_ordonne






'''
Entrée : 
    - df : dataframe contenant les points à visiter
    - rdv_lat : float : latitude du point de rendez-vous
    - rdv_long : float : longitude du point de rendez-vous
Sortie : 
    - dictionnaire : dictionnaire de dataframes, chacun contenant les points à visiter dans l'ordre optimal pour une équipe
Description :
'''
def route_toutes_equipes(df, rdv_lat, rdv_long):
    equipes = df["equipe"].unique()                 # renvoies les valeurs uniques 
    routes = {}                                     # initialisation du dictionnaire qui va contenir le resultat attendu 
    
    for equipe_id in equipes:
        df_equipe = df[df["equipe"] == equipe_id].copy()                        # One ne garde que ce qui est relatif a une equipe 
        df_equipe_ordonne = voisin_lePlus_proche_avec_rondeur(df_equipe, rdv_lat, rdv_long)  # itinéraire

        routes[equipe_id] = df_equipe_ordonne       # on remplit le dictionnaire

    return routes





'''
Entrée : 
    - df : dataframe contenant les points à visiter sous cette structure : latitude longitude intersection rue_1 rue_2 poi_proche distance_poi_km Equipe
    - start_lat : float : latitude du point de départ
    - start_long : float : longitude du point de départ
Sortie : 
    - df : dataframe contenant les points à visiter, avec une colonne supplémentaire "Ordre" indiquant la séquence de visite optimale
Description :
    Version optimisée au niveau de la recherche du minimum, au lieu d'appeller geodisc a chaque itération, on utilise des KdTree qui toruvent le minimum en une operation
    Toutefois la rondeur de la terre n'est pas prise en compte, ce n'est pas genant a l'echelle de quelque km carré comme garche mais ca le serait pour la france entière
'''
def voisin_lePlus_proche_opti_sans_rondeur(df, start_lat, start_long):

    intersections_restantes = df.copy()  # Crée une copie du dataframe pour éviter de modifier l'original
    intersections_visitées = []  # Liste pour stocker les intersections visitées dans l'ordre
    lat_actuelle, long_actuelle = start_lat, start_long  # Point de départ

    while not intersections_restantes.empty:
        #Construction du KDTree avec les coordonnées des intersections restantes 
        coords = intersections_restantes[["latitude", "longitude"]].values         #convertis les colones pandas en tableau numpy format attendu par KDTree
        tree = KDTree(coords)

        #Trouver l'intersection la plus proche de la position actuelle 
        dist, indice_local = tree.query([lat_actuelle, long_actuelle])      # indice_local est une position dans le tableau numpy

        #Reconversion en index pandas
        indice_proche = intersections_restantes.index[indice_local]
        intersection_proche = intersections_restantes.loc[indice_proche]

        #Enregistrer la visite et avancer : 
        intersections_visitées.append(indice_proche)

        lat_actuelle = intersection_proche['latitude']
        long_actuelle = intersection_proche['longitude']

        intersections_restantes = intersections_restantes.drop(indice_proche)

    #On reconstruit le dataFrame final : 
    df_ordonne = df.loc[intersections_visitées].copy()   # on copie le df et ordonnons les lignes grace aux indexes contenus dans la liste intersections visitées
    df_ordonne["ordre"] = range(1, len(df_ordonne) + 1)  # generer une suite de nombre croissante jusqu'au nombre de point et les stock dans la colonne ordre
    df_ordonne = df_ordonne.drop(columns=["distance_tempo"], errors="ignore") # suppression de la variable temporaire ( colone ) et ignore les erreures liées a si le dataset est vide


    return df_ordonne


# POSSIBILITE DE FAIRE QLQ CHOSE D'OPTI ET QUI PREND EN COMPTE LA RONDEUR DE LA TERRE, EN UTILISANT BallTree + Haversine


# 1. Charger le réseau PIÉTON (Ex: à l'échelle d'une ville ou d'un code postal)
# À faire une seule fois au chargement de ton application
# G = ox.graph_from_place("Garches, France", network_type="walk")

# 2. Ajouter les vitesses de marche estimées et les temps de trajet sur chaque tronçon
# G = ox.routing.add_edge_speeds(G, walk_speed=4.5) # 4.5 km/h en moyenne
# G = ox.routing.add_edge_travel_times(G)

def voisin_lePlus_proche_pieton(df, start_lat, start_long, G):
    """
    Calcule l'itinéraire optimal pour UNE équipe sur le réseau piéton réel.
    """
    intersections_restantes = df.copy()
    intersections_visitees = []
    
    # Trouver le nœud piéton le plus proche du point de départ
    noeud_actuel = ox.nearest_nodes(G, start_long, start_lat)
    
    # On associe chaque point du dataframe au nœud piéton OSM le plus proche
    intersections_restantes['osm_node'] = ox.nearest_nodes(
        G, intersections_restantes['longitude'].values, intersections_restantes['latitude'].values
    )

    while not intersections_restantes.empty:
        temps_trajet_réels = {}
        
        # 3. Calculer la distance (en temps) via le réseau pour tous les points restants
        for idx, row in intersections_restantes.iterrows():
            target_node = row['osm_node']
            try:
                # On cherche à minimiser le TEMPS de marche (travel_time) 
                # ou la distance ('length') selon la préférence
                temps = nx.shortest_path_length(G, source=noeud_actuel, target=target_node, weight='travel_time')
            except nx.NetworkXNoPath:
                # Au cas où un point est isolé (ex: copropriété fermée dans OSM)
                temps = float('inf') 
            temps_trajet_réels[idx] = temps
        
        # Trouver l'intersection la plus proche en temps de marche
        indice_proche = min(temps_trajet_réels, key=temps_trajet_réels.get)
        intersection_proche = intersections_restantes.loc[indice_proche]
        
        intersections_visitees.append(indice_proche)
        
        # Le point d'arrivée devient le nouveau point de départ
        noeud_actuel = intersection_proche['osm_node']
        intersections_restantes = intersections_restantes.drop(indice_proche)
        
    # Reconstruction du DataFrame final
    df_ordonne = df.loc[intersections_visitees].copy()
    df_ordonne["ordre"] = range(1, len(df_ordonne) + 1)
    
    return df_ordonne


# Due au probleme de ville en argument, j'opte pr avoir la carte en fonction des coordonnées gps extreme avec une securite de a peu pres 1 km et dmi soit 0.015 degres sur les coo

def route_toutes_equipes2(df, rdv_lat, rdv_long):
    """
    Détermine la zone géographique globale, télécharge la carte adéquate,
    et lance le calcul d'itinéraire pour chaque équipe.
    """
    
    # 1. On trouve les coordonnées minimales et maximales de TOUS les points + le RDV
    toutes_lats = pd.concat([df['latitude'], pd.Series([rdv_lat])])
    toutes_longs = pd.concat([df['longitude'], pd.Series([rdv_long])])
    
    # 2. On définit les limites géographiques (nord, sud, est, ouest)
    # On ajoute un petit "buffer" (ici ~0.015 degré, soit environ 1.5km) pour ne pas couper le réseau routier aux bords
    buffer = 0.015
    nord = toutes_lats.max() + buffer
    sud = toutes_lats.min() - buffer
    est = toutes_longs.max() + buffer
    ouest = toutes_longs.min() - buffer
    
    # 3. On télécharge la carte de cette zone exacte, peu importe les villes traversées !
    print("Téléchargement du réseau piéton pour la zone détectée . . .")
    G = ox.graph_from_bbox(bbox=(nord, sud, est, ouest), network_type="walk")

    # 4. Paramétrer la vitesse de marche (4.5 km/h) et calculer les temps de trajet
    G = ox.routing.add_edge_speeds(G, walk_speed=4.5)
    G = ox.routing.add_edge_travel_times(G)
    
    # 5. Dispatcher le calcul par équipe
    equipes = df["equipe"].unique()                 
    routes = {}                                     
    for equipe_id in equipes:
        df_equipe = df[df["equipe"] == equipe_id].copy()                        
        df_equipe_ordonne = voisin_lePlus_proche_pieton(df_equipe, rdv_lat, rdv_long, G)  
        routes[equipe_id] = df_equipe_ordonne       

    return routes