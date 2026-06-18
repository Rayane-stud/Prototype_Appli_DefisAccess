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
    1. Récupération du code INSEE de la commune (Nominatim)
        ↓
    2. Sources gouvernementales → écoles, mairies, hôpitaux, pharmacies
        ↓
    3. OpenStreetMap → supermarchés, marchés, parcs, lieux de culte...
        ↓
    4. Fusion + dédoublonnage + export Excel
 
LISTE DES FONCTIONS :
- get_code_insee() :
    # ROLE : Récupérer le code INSEE et l'area_id OSM d'une commune
              via l'API Nominatim (OpenStreetMap)
    # ARGUMENTS : "ville" de type str
    # REPONSE : dict {"code_insee": str, "osm_area_id": int}
                ou None si la commune n'est pas trouvée
 
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


#  ETAPE 1 — Récupérer le code INSEE et l'area_id OSM de la ville  ------------------------------------------------------------------------------------------------

 
def get_code_insee(ville: str) -> dict | None:
    """
    Interroge Nominatim pour obtenir :
    - Le code INSEE de la commune (utilisé pour les APIs gouvernementales)
    - L'OSM area_id (utilisé pour les requêtes Overpass dans les frontières exactes)
    """
 
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q":              f"{ville}, France",
        "format":         "json",   #oblige le fichier a etre en JSON pour pyhton
        "limit":          1,        # on ne veut que le meilleur resultat
        "extratags":      1
    }
            # initialisation des parametres
 
    try:
        reponse = requests.get(url, params=params, headers=HEADERS_NOMINATIM, timeout=10)   #va chercher dans le site Nominatim l'insee et l'area le stock dans reponse
        reponse.raise_for_status() #verification que tout va bien (si 200 = ok si autre que 200 pas ok )
        data = reponse.json() #converti en dictionnaire python 
 
        if not data:
            print(f"Commune de '{ville}' non trouvée.") #gestion d'erreur
            return None
 
        result      = data[0]
        osm_type    = result.get("osm_type", "")
        osm_id      = int(result.get("osm_id", 0))
        extratags   = result.get("extratags", {})
        code_insee  = extratags.get("ref:INSEE", "")
        #attribution des valeurs cherhcer sur le sites au variables
 
        # Overpass area_id = osm_id + 3 600 000 000 pour les relations
        osm_area_id = osm_id + 3_600_000_000 if osm_type == "relation" else osm_id
            # le osm_area_id = osm_id + 3_600_000_000 correspond a un changement de repere

        if not code_insee:
            print(f" Code INSEE non trouvé pour '{ville}', certaines sources gouvernementales seront ignorées.")
 
        return {
            "code_insee":  code_insee,
            "osm_area_id": osm_area_id
        }
 
    except Exception as e:
        print(f" Erreur Nominatim : {e}")
        return None
 
