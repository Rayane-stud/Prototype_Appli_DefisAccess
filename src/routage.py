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
    df_ordonne["Ordre"] = range(1, len(df_ordonne) + 1)  # generer une suite de nombre croissante jusqu'au nombre de point et les stock dans la colonne ordre
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
    equipes = df["Equipe"].unique()                 # renvoies les valeurs uniques 
    routes = {}                                     # initialisation du dictionnaire qui va contenir le resultat attendu 
    
    for equipe_id in equipes:
        df_equipe = df[df["Equipe"] == equipe_id].copy()                        # One ne garde que ce qui est relatif a une equipe 
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
    df_ordonne["Ordre"] = range(1, len(df_ordonne) + 1)  # generer une suite de nombre croissante jusqu'au nombre de point et les stock dans la colonne ordre
    df_ordonne = df_ordonne.drop(columns=["distance_temp"], errors="ignore") # suppression de la variable temporaire ( colone ) et ignore les erreures liées a si le dataset est vide


    return df_ordonne


# POSSIBILITE DE FAIRE QLQ CHOSE D'OPTI ET QUI PREND EN COMPTE LA RONDEUR DE LA TERRE, EN UTILISANT BallTree + Haversine


# ---- TESTS ------------------------------------------------------------------
if __name__ == "__main__":

    RDV_LAT  = 48.8390
    RDV_LONG = 2.1870

    df_test = pd.DataFrame({
        "Equipe":       [1, 1, 1, 2, 2],
        "latitude":     [48.8410, 48.8380, 48.8425, 48.8360, 48.8400],
        "longitude":    [2.1850,  2.1890,  2.1830,  2.1910,  2.1860],
        "Intersection": ["Rue A / Rue B", "Rue C / Rue D", "Rue E / Rue F",
                         "Rue G / Rue H", "Rue I / Rue J"],
    })

    print("=== TEST 1 : voisin_lePlus_proche (équipe 1) ===")
    df_eq1 = df_test[df_test["Equipe"] == 1].copy()
    df_ordonne = voisin_lePlus_proche_avec_rondeur(df_eq1, RDV_LAT, RDV_LONG)
    print(df_ordonne[["Intersection", "Ordre"]])

    print("\n=== TEST 2 : route_toutes_equipes ===")
    routes = route_toutes_equipes(df_test, RDV_LAT, RDV_LONG)
    for equipe_id, df_route in routes.items():
        print(f"\n  Équipe {equipe_id} :")
        print(df_route[["Intersection", "Ordre"]].to_string(index=False))

    print("\n✅ Tous les tests passent !")