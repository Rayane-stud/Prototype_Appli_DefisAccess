"""
Ce fichier va nous permettre d'identifier le nombre de passage piéton par intersections 
en utilisant open street map ainsi que les bases de données récupéré sur les intersection en île de France.
il va donc parcourir ligne par ligne les fichier csv une fois qu'ils ont été nettoyé pour associer à chaque intersections
les passages piétons associés.
"""

import math
import requests
import pandas as pd
from pathlib import Path
from scipy.spatial import cKDTree   
import numpy as np      

# Carte de visite obligatoire exigée par la charte d'utilisation de l'API Nominatim (évite le blocage HTTP 403)
HEADERS_NOMINATIM = {
    "User-Agent": "ProjetSecuriteRoutiere_AnalyseIntersections/1.0 (contact: ton_email@exemple.com)"
}

# Trouver les passages piétons sur OSM
CATEGORIES_PASSAGES_PIETONS = [
    {"type": "passage_pieton_general", "osm_filters": '["highway"="crossing"]'}
]


def get_osm_area_id(ville: str):
    """
    Interroge Nominatim (OpenStreetMap) pour récupérer l'osm_area_id
    de la commune. Cet identifiant sert uniquement à délimiter les
    frontières exactes de la commune dans les requêtes Overpass (étape 4).

    Pourquoi pas geo.api.gouv.fr ici aussi ?
    Parce que geo.api.gouv.fr connaît le code INSEE (système français)
    mais ne connaît pas l'osm_area_id (système propre à OpenStreetMap,
    valable dans le monde entier). Seul Nominatim peut faire la conversion
    nom de commune → identifiant OpenStreetMap.
    """

    url = "https://nominatim.openstreetmap.org/search"
    # adresse du service Nominatim sur internet

    params = {
        "q":      f"{ville}, France",
        # la question posée à Nominatim : le nom de la commune + le pays
        # pour éviter les confusions avec des communes homonymes à l'étranger
        "format": "json",
        # oblige la réponse à être en JSON pour que Python puisse la lire
        "limit":  1
        # on ne veut que le meilleur résultat, pas une liste de possibilités
    }
    # on n'a plus besoin de "extratags" ici car on ne cherche plus le code INSEE
    # (c'est désormais geo.api.gouv.fr qui s'en charge dans l'étape 1a)

    try:
        reponse = requests.get(url, params=params, headers=HEADERS_NOMINATIM, timeout=10)
        # on envoie la question à Nominatim
        # headers=HEADERS_NOMINATIM : carte de visite obligatoire (sinon 403 Forbidden)
        # timeout=10 : si pas de réponse en 10 secondes on abandonne

        reponse.raise_for_status()
        # verification que tout va bien (200 = ok, autre = erreur)

        data = reponse.json()
        # convertit la réponse texte en liste Python lisible

        if not data:
            print(f" Commune '{ville}' non trouvée sur Nominatim.")
            return None
            # si Nominatim ne trouve aucune commune correspondante on arrête

        result = data[0]
        # on prend le premier (et unique, grâce à limit=1) résultat
        # c'est un dictionnaire qui contient toutes les infos retournées par Nominatim

        osm_type = result.get("osm_type", "")
        # le type d'objet OpenStreetMap retourné
        # pour une commune ce sera toujours "relation"
        # le "" est la valeur par défaut si la clé n'existe pas (gestion d'erreur)

        osm_id = int(result.get("osm_id", 0))
        # l'identifiant OSM brut de la commune (propre à OpenStreetMap)
        # int() convertit la valeur en nombre entier
        # le 0 est la valeur par défaut si la clé n'existe pas (gestion d'erreur)

        osm_area_id = osm_id + 3_600_000_000 if osm_type == "relation" else osm_id
        # Overpass utilise un identifiant différent de celui de Nominatim
        # pour les "relation" (= communes), la règle fixe d'OpenStreetMap est :
        #     area_id = osm_id + 3 600 000 000
        # c'est une conversion entre deux "repères" internes à OpenStreetMap
        # si jamais ce n'était pas une "relation" (cas très rare pour une commune)
        # on garde l'osm_id tel quel, par sécurité

        print(f"   OSM area_id trouvé via Nominatim : {osm_area_id}")
        return osm_area_id
        # on retourne l'identifiant prêt à être utilisé par Overpass (étape 4)

    except Exception as e:
        if "ConnectionError" in str(type(e)):
            print(f" Pas de connexion internet, impossible d'interroger Nominatim.")
        elif "Timeout" in str(type(e)):
            print(f" Nominatim ne répond pas, réessayez dans quelques instants.")
        else:
            print(f" Erreur inattendue lors de l'appel à Nominatim : {e}")
        return None
        # si quelque chose s'est mal passé (pas internet, serveur en panne...)
        # un seul except, bien aligné avec le try du dessus


def calculer_distance_haversine(lat1: float, lon1: float, lat2: float, lon2: float):
    """
    Calcule la distance en mètres entre deux points géographiques GPS.
    """
    R = 6371000  # Rayon moyen de la Terre en mètres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlon / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def telecharger_passages_par_zone(id_zone_commune: int, rayon_metres: int = 20):
    """
    Interroge l'API Overpass pour extraire toutes les intersections topologiques 
    d'une commune et compte les passages piétons présents dans un rayon donné.
    """
    # Construction du filtre dynamique basé sur tes catégories déclarées plus haut
    filtre_osm = CATEGORIES_PASSAGES_PIETONS[0]["osm_filters"]

    # Requête Overpass compilée :
    # 1. Filtre sur la zone géospatiale de la commune.
    # 2. Extrait les axes routiers (ways).
    # 3. Repère les intersections (noeuds partagés par au moins 2 routes : way_cnt:2-).
    # 4. Extrait les passages piétons dans le rayon autour de ces intersections.
    requete_overpass = f"""
    [out:json][timeout:180];
    area({id_zone_commune})->.zone_commune;
    way["highway"~"primary|secondary|tertiary|residential|unclassified"]["access"!="private"](area.zone_commune)->.routes_pertinentes;
    node(way_cnt.routes_pertinentes:2-)->.toutes_les_intersections;
    (
      node{filtre_osm}(around.toutes_les_intersections:{rayon_metres});
      way{filtre_osm}(around.toutes_les_intersections:{rayon_metres});
    )->.passages_pietons;
    (.toutes_les_intersections; .passages_pietons;);
    out body center;
    """

    url_api = "https://overpass-api.de/api/interpreter"
    print(" Envoi de la requête à l'API Overpass (cela peut prendre un moment)...")
    
    try:
        reponse = requests.post(
            url_api,
            data={"data": requete_overpass},
            timeout=190,
            headers={
                "User-Agent": "ProjetSecuriteRoutiere_AnalyseIntersections/1.0 (contact: ton_email@exemple.com)",
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )
        reponse.raise_for_status()
        donnees = reponse.json()
    except Exception as e:
        print(f" Erreur lors de l'extraction Overpass : {e}")
        return pd.DataFrame()

    elements = donnees.get("elements", [])
    
    intersections_brutes = []
    passages_pietons_extraits = []

    # Tri des données reçues entre carrefours physiques et passages piétons
    for el in elements:
        tags = el.get("tags", {})
        # Si le noeud ou la ligne possède une propriété d'aménagement piéton
        if "highway" in tags and tags["highway"] == "crossing":
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")
            if lat and lon:
                passages_pietons_extraits.append({"lat": lat, "lon": lon})
        else:
            # C'est un point d'intersection de structure routière
            if el["type"] == "node":
                intersections_brutes.append({
                    "intersection_id_osm": el["id"], 
                    "latitude": el["lat"], 
                    "longitude": el["lon"], 
                    "nb_passages_pietons": 0
                })

    if not intersections_brutes:
        print(" Aucune intersection structurelle trouvée dans cette zone.")
        return pd.DataFrame()

    print(f" Analyse de {len(passages_pietons_extraits)} passages piétons face à {len(intersections_brutes)} intersections...")

    # Algorithme de déduplication : on attribue le passage piéton à l'intersection la plus proche uniquement
    # --- Construction de l'index spatial KDTree ---
    # On convertit les coordonnées GPS en radians pour que la distance
    # soit calculable en mètres via la formule haversine approximée
    coords_intersections = np.array([
        [math.radians(i["latitude"]), math.radians(i["longitude"])]
        for i in intersections_brutes
    ])
    arbre = cKDTree(coords_intersections)
    # cKDTree est un index spatial : il organise les intersections dans
    # une structure en arbre qui permet de trouver les voisins proches
    # en O(log n) au lieu de O(n) — beaucoup plus rapide

    # Conversion du rayon en radians (la KDTree travaille en radians)
    # 6371000 = rayon moyen de la Terre en mètres
    rayon_radians = rayon_metres / 6371000

    # --- Attribution de chaque passage piéton à son intersection la plus proche ---
    for passage in passages_pietons_extraits:
        point = [math.radians(passage["lat"]), math.radians(passage["lon"])]
        # on convertit ce passage piéton en radians aussi, pour être
        # dans le même "langage" que l'arbre

        distance, index = arbre.query(point, k=1, distance_upper_bound=rayon_radians)
        # arbre.query() cherche le voisin le plus proche (k=1) du passage piéton
        # distance_upper_bound=rayon_radians : on ne regarde que dans le rayon défini
        # retourne (distance, index) : l'index de l'intersection la plus proche
        # si rien trouvé dans le rayon, index vaut len(intersections_brutes)

        if index < len(intersections_brutes):
            intersections_brutes[index]["nb_passages_pietons"] += 1
            # on incrémente le compteur de l'intersection la plus proche
            # la condition évite le cas "rien trouvé" où index serait hors limites

    # Conversion finale au format DataFrame tabulaire Pandas
    return pd.DataFrame(intersections_brutes)


# ──────────────────────────── Point d'entrée d'Exécution ────────────────────────

def main():
    # Exemple d'application sur une commune d'Île-de-France (ex: Nanterre ou Versailles)
    nom_commune = "Garches"  # à remplacer par la commune souhaitée
    print(f"--- Démarrage du traitement pour la commune : {nom_commune} ---")
    
    # Étape 1 : Conversion Nom -> ID de Relation OSM (Surface)
    id_zone = get_osm_area_id(nom_commune)
    
    if id_zone:
        # Étape 2 : Extraction et calcul topologique des passages par carrefour
        df_resultat = telecharger_passages_par_zone(id_zone, rayon_metres=25)
        
        if not df_resultat.empty:
            # Étape 3 : Exportation des données nettoyées et calculées
            nom_fichier_sortie = f"intersections_{nom_commune.lower()}_passages.csv"
            df_resultat.to_csv(nom_fichier_sortie, index=False, encoding="utf-8-sig")
            
            print(f"\n Traitement terminé avec succès !")
            print(f" Fichier sauvegardé sous : {nom_fichier_sortie}")
            print("\nAperçu des premières lignes générées :")
            print(df_resultat.head(10).to_string(index=False))
        else:
            print(" Échec de la génération du tableau de données.")
    else:
        print(" Impossible de poursuivre sans identifiant de zone valide.")


if __name__ == "__main__":
    main()


# concernant les test : 
print(get_osm_area_id("Garches"))