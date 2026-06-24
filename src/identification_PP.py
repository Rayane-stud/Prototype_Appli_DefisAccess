"""
Ce fichier va nous permettre d'identifier le nombre de passage piéton par intersections 
en utilisant open street map ainsi que les bases de données récupéré sur les intersection en île de France.
il va donc parcourir ligne par ligne les fichier csv une fois qu'ils ont été nettoyé pour associer à chaque intersections
les passages piétons associés.
"""

import math
import requests
import pandas as pd
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

SERVEURS_OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
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

def envoyer_requete_overpass(requete: str, headers: dict) -> dict:
    """
    Essaie chaque serveur Overpass dans l'ordre jusqu'à en trouver un qui répond.
    """
    for url in SERVEURS_OVERPASS:
        try:
            print(f"   Tentative sur {url}...")
            reponse = requests.post(url, data={"data": requete}, timeout=130, headers=headers)
            reponse.raise_for_status()
            return reponse.json()
        except Exception as e:
            print(f"   Échec ({e}) → serveur suivant...")
            continue

    print(" Tous les serveurs Overpass sont indisponibles.")
    return {}

def telecharger_passages_par_zone(id_zone_commune: int, rayon_metres: int = 20):

    filtre_osm = CATEGORIES_PASSAGES_PIETONS[0]["osm_filters"]
    headers = {
        "User-Agent": "ProjetSecuriteRoutiere_AnalyseIntersections/1.0 (contact: ton_email@exemple.com)",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    # --- REQUÊTE 1 : uniquement les intersections ---
    requete_intersections = f"""
[out:json][timeout:120];
area({id_zone_commune})->.zone_commune;
way["highway"~"primary|secondary|tertiary|residential|unclassified"]["access"!="private"](area.zone_commune)->.routes_pertinentes;
node(way_cnt.routes_pertinentes:2-)->.toutes_les_intersections;
.toutes_les_intersections out body;
"""

    print(" Étape 1/2 — Récupération des intersections...")
    donnees = envoyer_requete_overpass(requete_intersections, headers)
    if not donnees:
        return pd.DataFrame()
    intersections_brutes = [
        {
            "intersection_id_osm": el["id"],
            "latitude": el["lat"],
            "longitude": el["lon"],
            "nb_passages_pietons": 0
        }
        for el in donnees.get("elements", [])
        if el["type"] == "node"
    ]

    if not intersections_brutes:
        print(" Aucune intersection trouvée.")
        return pd.DataFrame()

    print(f" {len(intersections_brutes)} intersections trouvées.")

    # --- REQUÊTE 2 : uniquement les passages piétons ---
    requete_passages = f"""
        [out:json][timeout:120];
        area({id_zone_commune})->.zone_commune;
            (node{filtre_osm}(area.zone_commune);way{filtre_osm}(area.zone_commune);)->.passages_pietons;.passages_pietons out body center;
        """

    print(" Étape 2/2 — Récupération des passages piétons...")
    donnees = envoyer_requete_overpass(requete_passages, headers)
    if not donnees:
        return pd.DataFrame()
    passages_pietons_extraits = []
    for el in donnees.get("elements", []):
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat and lon:
            passages_pietons_extraits.append({"lat": lat, "lon": lon})

    print(f" {len(passages_pietons_extraits)} passages piétons trouvés.")

    # --- ATTRIBUTION KDTree (inchangé) ---
    print(f" Analyse de {len(passages_pietons_extraits)} passages piétons face à {len(intersections_brutes)} intersections...")

    coords_intersections = np.array([
        [math.radians(i["latitude"]), math.radians(i["longitude"])]
        for i in intersections_brutes
    ])
    arbre = cKDTree(coords_intersections)
    rayon_radians = rayon_metres / 6371000

    for passage in passages_pietons_extraits:
        point = [math.radians(passage["lat"]), math.radians(passage["lon"])]
        distance, index = arbre.query(point, k=1, distance_upper_bound=rayon_radians)
        if index < len(intersections_brutes):
            intersections_brutes[index]["nb_passages_pietons"] += 1

    return pd.DataFrame(intersections_brutes)

# ──────────────────────────── Point d'entrée d'Exécution ────────────────────────

def main():
    # Exemple d'application sur une commune d'Île-de-France (ex: Nanterre ou Versailles)
    nom_commune = "garches"  # à remplacer par la commune souhaitée
    print(f"--- Démarrage du traitement pour la commune : {nom_commune} ---")
    
    # Étape 1 : Conversion Nom -> ID de Relation OSM (Surface)
    id_zone = get_osm_area_id(nom_commune)
    
    if id_zone:
        # Étape 2 : Extraction et calcul topologique des passages par carrefour
        df_resultat = telecharger_passages_par_zone(id_zone, rayon_metres=25)
        
        if not df_resultat.empty:
            # Étape 3 : Exportation des données nettoyées et calculées
            nom_fichier_sortie = f"data/output/intersections_{nom_commune.lower()}_passages.csv"
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