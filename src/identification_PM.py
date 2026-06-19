"""
FICHIER : identifier_PM_hybride.py
 
# BUT : Identifier automatiquement les Points de Mesure (PM) d'une ville
      en combinant deux sources de données gratuites :
        1. Sources gouvernementales officielles (data.gouv.fr, data.education.gouv.fr)
           pour les lieux les plus importants (écoles, mairies, hôpitaux, pharmacies)
        2. OpenStreetMap via l'API Overpass
           pour les lieux sans source gouvernementale (supermarchés, parcs, marchés...)
 
      Les frontières exactes de la commune sont utilisées comme decoupe pour la zone de recherche des pm
      via le niveau administratif OSM (open source maps)
 
LOGIQUE GLOBALE :
    Commune saisie
        ↓
    1a. Récupération du code INSEE via geo.api.gouv.fr (API officielle INSEE/IGN)
    1b. Récupération de l'osm_area_id via Nominatim (OpenStreetMap)
        ↓
    2. Sources gouvernementales → écoles, mairies, hôpitaux, pharmacies
        ↓
    3. OpenStreetMap → supermarchés, marchés, parcs, lieux de culte...
        ↓
    4. Fusion + dédoublonnage + export Excel
 
LISTE DES FONCTIONS :
 
- get_code_insee_api() :
    # ROLE : Récupérer le code INSEE d'une commune via l'API officielle
              geo.api.gouv.fr (INSEE/IGN)
              Source 100% officielle et fiable, toutes les communes françaises y sont
    # ARGUMENTS : "ville" de type str
    # REPONSE : str (code INSEE) ou None si la commune n'est pas trouvée
 
- get_osm_area_id() :
    # ROLE : Récupérer l'osm_area_id d'une commune via Nominatim
              Cet identifiant est nécessaire pour délimiter les frontières
              exactes de la commune dans les requêtes Overpass
    # ARGUMENTS : "ville" de type str
    # REPONSE : int (osm_area_id) ou None si la commune n'est pas trouvée
 
- get_ecoles_gouv() :
    # ROLE : Récupérer toutes les écoles d'une commune
              via l'API data.education.gouv.fr (source officielle exhaustive)
    # ARGUMENTS : "code_insee" de type str
    # REPONSE : list[dict] avec les clés nom | type | latitude | longitude
 
- get_equipements_gouv() :
    # ROLE : Récupérer les équipements publics (mairies, hôpitaux, pharmacies)
              via l'API data.gouv.fr / Base Permanente des Équipements (BPE)
    # ARGUMENTS : "code_insee" de type str
    # REPONSE : list[dict] avec les clés nom | type | latitude | longitude
 
- get_PM_osm() :
    # ROLE : Récupérer les lieux complémentaires (supermarchés, marchés, parcs...)
              via l'API Overpass dans les frontières exactes de la commune
    # ARGUMENTS : "osm_area_id" de type int
    # REPONSE : list[dict] avec les clés nom | type | latitude | longitude
 
- construire_dataframe_PM() :
    # ROLE : Orchestrer toutes les sources, fusionner les résultats,
              supprimer les doublons géographiques et exporter en Excel
    # ARGUMENTS : "ville" de type str
    # REPONSE : pd.DataFrame avec les colonnes :
                nom | type | source | latitude | longitude | coordonnees
"""

import time
import requests
import pandas as pd
from geopy.distance import geodesic

# URL de l'API officielle geo.api.gouv.fr (INSEE/IGN)
# Contrairement au fichier CSV brut de l'INSEE, c'est une vraie API
# conçue pour être interrogée automatiquement (pas de blocage 403)
URL_GEO_API = "https://geo.api.gouv.fr/communes"

# Carte de visite obligatoire pour utiliser Nominatim (contr la surchage du site)
HEADERS_NOMINATIM = {
    "User-Agent": "DefiaccessPM/1.0 (association accessibilite)"
}

# CATEGORIES OSM (uniquement ce qui n'a pas de source gouvernementale)
    # demander celle qui ne sont pas necessaire 
CATEGORIES_OSM = [
    {"type": "supermarché",    "osm_filters": '["shop"="supermarket"]'},
    {"type": "marché",         "osm_filters": '["amenity"="marketplace"]'},
    {"type": "lieu de culte",  "osm_filters": '["amenity"="place_of_worship"]'},
    {"type": "médiathèque",    "osm_filters": '["amenity"="library"]'},
    {"type": "poste",          "osm_filters": '["amenity"="post_office"]'},
    {"type": "centre sportif", "osm_filters": '["leisure"="sports_centre"]'},
    
]


# ETAPE 1a — Récupérer le code INSEE via geo.api.gouv.fr (source officielle) -----------------------


def get_code_insee_api(ville: str) -> str | None:
    """
    Interroge l'API officielle geo.api.gouv.fr (INSEE/IGN) pour récupérer
    le code INSEE de la commune demandée.
    Source 100% officielle : toutes les communes françaises y sont référencées.

    NOUVEAU : on n'utilise plus le fichier CSV brut de l'INSEE
    (https://www.insee.fr/.../v_commune_2024.csv) car ce fichier est pensé
    pour un téléchargement manuel depuis un navigateur. Quand un programme
    essaie de le télécharger automatiquement, l'INSEE bloque la requête
    avec une erreur 403 Forbidden, même avec un User-Agent renseigné.

    geo.api.gouv.fr est au contraire une vraie API : on lui pose une question
    précise ("le code INSEE de Garches") et elle répond uniquement avec cette
    commune, sans bloquer ni renvoyer les 35 000 communes de France.
    """

    params = {
        "nom":    ville,
        # le nom de la commune tapé par l'utilisateur
        "fields": "nom,code",
        # on ne demande que le nom et le code INSEE, pas toutes les infos
        "boost":  "population",
        # en cas de plusieurs communes au même nom, on priorise la plus peuplée
        "limit":  1
        # on ne veut que le meilleur résultat
    }
    # initialisation des paramètres de la requête, même logique que pour Nominatim

    try:
        print("   Interrogation de geo.api.gouv.fr...")
        reponse = requests.get(URL_GEO_API, params=params, timeout=10)
        # on envoie la question à l'API officielle
        # timeout=10 : si pas de réponse en 10 secondes on abandonne

        reponse.raise_for_status()
        # verification que tout va bien (200 = ok, autre = erreur)

        data = reponse.json()
        # convertit la réponse texte en liste Python lisible

        if not data:
            print(f" la commune '{ville}' n'a pas été trouvée sur geo.api.gouv.fr.")
            return None
            # si l'API ne trouve aucune commune correspondante on arrête

        code_insee = data[0].get("code", "")
        # on prend le premier résultat (le plus pertinent grâce à "boost")
        # et on récupère son code INSEE dans la clé "code"

        if code_insee:
            print(f"   Code INSEE trouvé via geo.api.gouv.fr : {code_insee}")
            return code_insee
            # on retourne le code INSEE trouvé

        print(f" Code INSEE manquant dans la réponse pour '{ville}'.")
        return None

    except Exception as e:
        if "ConnectionError" in str(type(e)):
            print(f" Pas de connexion internet, impossible d'interroger geo.api.gouv.fr.")
        elif "Timeout" in str(type(e)):
            print(f" geo.api.gouv.fr ne répond pas, réessayez dans quelques instants.")
        else:
            print(f"Erreur inattendue lors de l'appel à geo.api.gouv.fr : {e}")
        return None
        # si quelque chose s'est mal passé (pas internet, API indisponible...)
        # un seul except, bien aligné avec le try du dessus




#TESTES : ---------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    villes_test = ["Garches", "Montrouge", "VilleQuiNExistePas123"]

    for ville in villes_test:
        print(f"\n--- Test pour '{ville}' ---")
        resultat = get_code_insee_api(ville)
        print(f"Résultat : {resultat}")




# ETAPE 1b — Récupérer l'osm_area_id via Nominatim (OpenStreetMap) ---------------------------------
 
 
def get_osm_area_id(ville: str) -> int | None:
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
 
 
#TESTES : ---------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    villes_test = ["Garches", "Montrouge", "VilleQuiNExistePas123"]
 
    for ville in villes_test:
        print(f"\n--- Test pour '{ville}' ---")
 
        code_insee = get_code_insee_api(ville)
        print(f"Code INSEE  : {code_insee}")
 
        osm_area_id = get_osm_area_id(ville)
        print(f"OSM area_id : {osm_area_id}")