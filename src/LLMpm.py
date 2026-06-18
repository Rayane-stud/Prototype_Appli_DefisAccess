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
    1a. Récupération du code INSEE via le COG (fichier officiel INSEE) 
    1b. Récupération de l'osm_area_id via Nominatim (OpenStreetMap)
        ↓
    2. Sources gouvernementales → écoles, mairies, hôpitaux, pharmacies
        ↓
    3. OpenStreetMap → supermarchés, marchés, parcs, lieux de culte...
        ↓
    4. Fusion + dédoublonnage + export Excel
 
LISTE DES FONCTIONS :
 
- get_code_insee_cog() :
    # ROLE : Récupérer le code INSEE d'une commune via le fichier COG
              (Code Officiel Géographique) publié par l'INSEE
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
 
# URL du fichier COG publié par l'INSEE
# Ce fichier contient toutes les communes françaises avec leur code INSEE
URL_COG = "https://www.insee.fr/fr/statistiques/fichier/7766585/v_commune_2024.csv"
 
# Carte de visite obligatoire pour utiliser Nominatim (contr la surchage du site)
    HEADERS_NOMINATIM = {
    "User-Agent": "DefiaccessPM/1.0 (association accessibilite)"
}
 
# CATEGORIES OSM (uniquement ce qui n'a pas de source gouvernementale)
    # demander celle qui ne sont pas necessaire 
CATEGORIES_OSM = [
    {"type": "supermarché",    "osm_filters": '["shop"="supermarket"]'},
    {"type": "épicerie",       "osm_filters": '["shop"="convenience"]'},
    {"type": "marché",         "osm_filters": '["amenity"="marketplace"]'},
    {"type": "lieu de culte",  "osm_filters": '["amenity"="place_of_worship"]'},
    {"type": "médiathèque",    "osm_filters": '["amenity"="library"]'},
    {"type": "poste",          "osm_filters": '["amenity"="post_office"]'},
    {"type": "centre sportif", "osm_filters": '["leisure"="sports_centre"]'},
    {"type": "parc",           "osm_filters": '["leisure"="park"]'},
]
 
 
# ETAPE 1a — Récupérer le code INSEE via le COG (source officielle INSEE) -------------------------
 
 
def get_code_insee_cog(ville: str) -> str | None:
    """
    Télécharge le fichier COG (Code Officiel Géographique) de l'INSEE
    et cherche le code INSEE de la commune demandée.
    Source 100% officielle : toutes les communes françaises y sont référencées.
    """
 
    try:
        print("   Téléchargement du fichier COG (INSEE)...")
        reponse = requests.get(URL_COG, timeout=30)
        # on va chercher le fichier COG sur le site de l'INSEE
        # timeout=30 car le fichier est plus volumineux que Nominatim
 
        reponse.raise_for_status()
        # verification que tout va bien (200 = ok, autre = erreur)
 
        lignes = reponse.text.splitlines()
        # on découpe le fichier CSV ligne par ligne
        # splitlines() transforme le gros texte en liste de lignes
 
        entetes = lignes[0].split(",")
        # la première ligne contient les noms des colonnes
        # on la découpe selon les virgules pour obtenir la liste des colonnes

        # traduction pour que python puisse lire les fichiers
 
        for ligne in lignes[1:]:
            # on parcourt toutes les lignes sauf la première (entetes)
 
            champs = ligne.split(",")
            # on découpe chaque ligne selon les virgules
 
            if len(champs) < len(entetes):
                continue
                # si la ligne est incomplète on la saute (gestion d'erreur)
 
            row = dict(zip(entetes, champs))
            # on recrée un dictionnaire {colonne: valeur} pour cette ligne
            # zip() associe chaque entete à sa valeur correspondante
 
            nom_commune = row.get("LIBELLE", "").strip().lower()
            # on récupère le nom de la commune dans le fichier COG
            # .strip() supprime les espaces en trop
            # .lower() met en minuscules pour comparer sans tenir compte des majuscules
 
            if nom_commune == ville.strip().lower():
                # si le nom de la commune correspond à ce que l'utilisateur a tapé
 
                code_insee = row.get("COM", "")
                # on récupère le code INSEE dans la colonne "COM" du fichier COG
 
                if code_insee:
                    print(f"   Code INSEE trouvé via COG : {code_insee}")
                    return code_insee
                    # on retourne le code INSEE dès qu'on le trouve
 
        print(f" la commune '{ville}' n'a pas été trouvée dans le fichier COG.")
        return None
        # si on a parcouru tout le fichier sans trouver la commune
 
    except Exception as e:
            except Exception as e:
        if "ConnectionError" in str(type(e)):
            print(f" Pas de connexion internet, impossible de télécharger le fichier COG.")
         elif "Timeout" in str(type(e)):
            print(f" Le site de l'INSEE ne répond pas, réessayez dans quelques instants.")
        else:
            print(f"Erreur inattendue lors du téléchargement du fichier COG : {e}")
        return None
        # si quelque chose s'est mal passé (pas internet, fichier indisponible...)
 