"""
FICHIER : identifier_PM_hybride.py
 
# BUT : automatiquement les Points de Mesure (PM) d'une ville
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

import math
import time
import json
import datetime
import requests
import pandas as pd

import os
from pathlib import Path

# URL de l'API officielle geo.api.gouv.fr (INSEE/IGN)
URL_GEO_API = "https://geo.api.gouv.fr/communes"

# URL de l'API SNCF (Opendatasoft v2.1) pour la liste officielle des gares
URL_SNCF_GARES_API = "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/liste-des-gares/records"

# Carte de visite obligatoire pour utiliser Nominatim (contr la surchage du site)
HEADERS_NOMINATIM = {
    "User-Agent": "DefiaccessPM/1.0 (association accessibilite)"
}

# TOUTES LES CATEGORIES OSM DISPONIBLES (avec leur label d'affichage)
CATEGORIES_OSM_DISPONIBLES = [
    {"type": "gare",             "osm_filters": '["railway"="station"]',            "label": "Gares"},
    {"type": "gendarmerie",      "osm_filters": '["amenity"="police"]',             "label": "Gendarmeries (OSM)"},
    {"type": "lieu de culte",    "osm_filters": '["amenity"="place_of_worship"]',  "label": "Lieux de culte (églises, mosquées, synagogues…)"},
    {"type": "poste",            "osm_filters": '["amenity"="post_office"]',       "label": "Bureaux de poste"},
    {"type": "pharmacie",        "osm_filters": '["amenity"="pharmacy"]',          "label": "Pharmacies"},
    {"type": "centre sportif",   "osm_filters": '["leisure"="sports_centre"]',     "label": "Centres sportifs"},
    {"type": "centre culturel",  "osm_filters": '["amenity"="community_centre"]',  "label": "Centres culturels / associatifs"},
    {"type": "supermarché",      "osm_filters": '["shop"="supermarket"]',           "label": "Supermarchés"},
]

# Catégories OSM utilisées uniquement si FINESS est indisponible (fallback)
CATEGORIES_OSM_SANTE_FALLBACK = [
    {"type": "hôpital",  "osm_filters": '["amenity"="hospital"]'},
    {"type": "clinique", "osm_filters": '["amenity"="clinic"]'},
]

# ──────────────────────────────────────────────
# CONFIGURATION FINESS
# ──────────────────────────────────────────────

# ID du jeu de données FINESS sur data.gouv.fr
FINESS_DATASET_ID = "53699569a3a729239d2046eb"




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


# ETAPE 2 — Récupérer les écoles via data.education.gouv.fr (source officielle) --------------------


# URL de l'API du Ministère de l'Éducation Nationale (plateforme Opendatasoft)
# Ce jeu de données recense tous les établissements du 1er et 2nd degré
# (maternelles, élémentaires, collèges, lycées), publics et privés, en France
URL_ECOLES_API = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/fr-en-adresse-et-geolocalisation-etablissements-premier-et-second-degre/records"


def get_ecoles_gouv(code_insee: str) -> list[dict]:
    """
    Interroge l'API officielle data.education.gouv.fr pour récupérer
    toutes les écoles d'une commune via son code INSEE.
    Source exhaustive : toutes les écoles françaises y sont référencées,
    qu'elles soient publiques ou privées.

    Contrairement a get_code_insee_api() et get_osm_area_id() qui retournent
    un seul resultat (str ou int), cette fonction retourne une LISTE de
    dictionnaires car une commune contient generalement plusieurs ecoles.
    """

    params = {
        "where":  f'code_commune="{code_insee}"',
        # CORRIGE : le vrai nom de la colonne est "code_commune", pas "code_commune_insee"
        # (decouvert via le script de diagnostic qui liste les colonnes brutes)
        # "where" est le mot-cle Opendatasoft pour filtrer les resultats
        "limit":  100,
        # on recupere jusqu'a 100 ecoles, largement suffisant pour une commune
        "select": "appellation_officielle,nature_uai_libe,latitude,longitude"
        # CORRIGE : "appellation_officielle" (pas "nom_etablissement")
        # et "nature_uai_libe" (pas "type_etablissement"), vrais noms de colonnes
    }
    # initialisation des parametres, meme logique que pour les etapes precedentes

    resultats = []
    # liste vide qui va accumuler une ecole par ligne sous forme de dictionnaire

    try:
        print("   Interrogation de data.education.gouv.fr...")
        reponse = requests.get(URL_ECOLES_API, params=params, timeout=15)
        # timeout=15 (un peu plus long que les autres) car cette API peut etre
        # plus lente, elle traite potentiellement plusieurs dizaines de resultats

        reponse.raise_for_status()
        # verification que tout va bien (200 = ok, autre = erreur)

        data = reponse.json()
        # convertit la reponse texte en dictionnaire Python lisible

        for record in data.get("results", []):
            # contrairement a geo.api.gouv.fr et Nominatim qui retournent
            # directement une liste, l'API Opendatasoft range ses resultats
            # dans une cle "results" a l'interieur du dictionnaire principal
            # .get("results", []) evite une erreur si cette cle est absente

            lat = record.get("latitude")
            lon = record.get("longitude")
            # on recupere les coordonnees GPS directement fournies par l'API
            # PAS BESOIN DE GEOCODAGE : elles sont deja presentes dans le fichier officiel

            if lat is None or lon is None:
                continue
                # si une ecole n'a pas de coordonnees on la saute plutot que
                # de planter ou de l'inclure avec des valeurs manquantes

            resultats.append({
                "nom":       record.get("appellation_officielle", "École sans nom"),
                # CORRIGE : "appellation_officielle" est le vrai nom de la colonne
                "type":      record.get("nature_uai_libe", "école"),
                # CORRIGE : "nature_uai_libe" contient par exemple
                # "ECOLE DE NIVEAU ELEMENTAIRE", "COLLEGE", "LYCEE D'ENSEIGNEMENT GENERAL..."
                "source":    "data.education.gouv.fr",
                # utile pour la dedoublonnage de l'etape 4 (priorite aux sources gouvernementales)
                "latitude":  float(lat),
                "longitude": float(lon)
            })
            # on construit un dictionnaire par ecole, avec les memes cles
            # que ce qu'on utilisera pour les autres sources (etapes 3 et 4)
            # ca permettra de fusionner facilement tous les resultats plus tard

        print(f"   {len(resultats)} ecole(s) trouvee(s) pour le code INSEE {code_insee}")
        return resultats
        # on retourne la liste, meme vide si aucune ecole n'a ete trouvee
        # (une liste vide n'est pas une erreur, certaines petites communes
        # n'ont parfois aucune ecole sur leur territoire)

    except Exception as e:
        if "ConnectionError" in str(type(e)):
            print(f"Pas de connexion internet, impossible d'interroger data.education.gouv.fr.")
        elif "Timeout" in str(type(e)):
            print(f" data.education.gouv.fr ne répond pas, réessayez dans quelques instants.")
        else:
            print(f" Erreur inattendue lors de l'appel à data.education.gouv.fr : {e}")
        return []
        # IMPORTANT : ici on retourne une liste vide [] et non None
        # car le reste du pipeline (etape 4) s'attend a pouvoir faire
        # .extend() sur le resultat de cette fonction, ce qui plante si c'est None
        # une liste vide permet au programme de continuer sans planter,
        # simplement avec 0 ecole pour cette commune


# ETAPE 3 — Récupérer les mairies via l'API Annuaire de l'Administration -----------------------------------------------------------------------------------------


# URL de l'API officielle Annuaire de l'Administration (service-public.fr / DILA)
# Contrairement a la BPE (Base Permanente des Equipements) de l'INSEE qui n'existe
# qu'en gros fichier national a telecharger, cette API est une vraie API interrogeable
# directement par commune, comme data.education.gouv.fr
# Elle recense plus de 86 000 guichets publics locaux (mairies, CCAS, PMI, SAMU...)
URL_ANNUAIRE_API = "https://api-lannuaire.service-public.fr/api/explore/v2.1/catalog/datasets/api-lannuaire-administration/records"

# URL de l'API Adresse du gouvernement (BAN - Base Adresse Nationale)
# Gratuite, sans clé, specialement concue pour geocoder des adresses françaises
# avec precision. On l'utilise pour corriger les coordonnees peu fiables
# retournees par l'API Annuaire de l'Administration (voir explication ci-dessous)
URL_API_ADRESSE = "https://api-adresse.data.gouv.fr/search/"


def geocoder_adresse(adresse_texte: str) -> dict | None:
    """
    Interroge l'API Adresse du gouvernement (BAN) pour transformer une adresse
    texte (ex: "Place Roland-Nungesser 94130 Nogent-sur-Marne") en coordonnees
    GPS precises.

    POURQUOI CETTE FONCTION EXISTE :
    En testant get_equipements_gouv() on a decouvert que les coordonnees fournies
    directement par l'API Annuaire de l'Administration sont parfois fausses, alors
    que l'adresse texte associee est toujours correcte. Exemple verifie :
        Mairie de Nogent-sur-Marne
        Adresse texte (juste)   : "Place Roland-Nungesser, 94130 Nogent-sur-Marne"
        Coordonnees fournies (fausses) : pointent vers "8 Rue Edmond Vitry" (~600m d'ecart)
    On ignore donc le champ latitude/longitude de cette API et on regeocode
    nous-memes l'adresse texte avec la BAN, qui est specialisee et fiable.
    """

    params = {
        "q":     adresse_texte,
        # la question posee a la BAN : l'adresse texte complete a localiser
        "limit": 1
        # on ne veut que le meilleur resultat
    }

    try:
        reponse = requests.get(URL_API_ADRESSE, params=params, timeout=10)
        reponse.raise_for_status()
        # verification que tout va bien (200 = ok, autre = erreur)

        data = reponse.json()
        # convertit la reponse texte en dictionnaire Python lisible
        # la BAN repond au format GeoJSON : une liste de "features"

        features = data.get("features", [])
        if not features:
            return None
            # si la BAN ne trouve pas l'adresse on ne peut rien retourner

        coords = features[0]["geometry"]["coordinates"]
        # en GeoJSON les coordonnees sont rangees [longitude, latitude]
        # c'est l'ordre INVERSE de ce qu'on utilise partout ailleurs dans
        # notre code (latitude, longitude) -- attention a ne pas les inverser

        return {
            "latitude":  coords[1],
            "longitude": coords[0]
        }

    except Exception:
        return None
        # si le geocodage echoue on retourne None, la mairie sera simplement
        # ignoree dans get_equipements_gouv() plutot que de planter le programme


def get_equipements_gouv(code_insee: str) -> list[dict]:
    """
    Interroge l'API officielle Annuaire de l'Administration pour récupérer
    la mairie d'une commune via son code INSEE, puis regeocode son adresse
    avec l'API Adresse (BAN) pour obtenir des coordonnees fiables.

    IMPORTANT : cette API ne propose pas de filtre direct par type de service
    (mairie, hôpital...) dans la requête "where" -- seul le champ code_insee_commune
    est filtrable directement. On récupère donc TOUS les services publics de la
    commune (en général moins d'une dizaine), puis on filtre nous-mêmes en Python
    pour ne garder que ceux dont le type est "mairie".

    Les hôpitaux et pharmacies ne sont volontairement PAS cherchés ici : cette API
    recense des guichets administratifs (mairie, CCAS, PMI...), pas des établissements
    de santé. Ils seront récupérés via OpenStreetMap à l'étape 4 (get_PM_osm).
    """

    params = {
        "where": f'code_insee_commune="{code_insee}"',
        # seul filtre fiable confirmé par nos tests : le code INSEE de la commune
        # contrairement a data.education.gouv.fr, on ne peut PAS combiner avec
        # un filtre sur le type de service directement dans la requete
        "limit": 50
        # une commune compte rarement plus d'une dizaine de services repertories ici,
        # 50 est largement suffisant comme marge de securite
    }

    resultats = []
    # liste vide qui va accumuler les mairies trouvees (generalement 1 seule par commune)

    try:
        print("   Interrogation de l'Annuaire de l'Administration...")
        reponse = requests.get(URL_ANNUAIRE_API, params=params, timeout=15)

        reponse.raise_for_status()
        # verification que tout va bien (200 = ok, autre = erreur)

        data = reponse.json()
        # convertit la reponse texte en dictionnaire Python lisible

        for record in data.get("results", []):
            # comme pour data.education.gouv.fr, les resultats sont ranges
            # dans une cle "results" a l'interieur du dictionnaire principal

            pivot = record.get("pivot", [])
            # "pivot" est retourne par l'API comme du TEXTE contenant du JSON
            # (ex: '[{"type_service_local": "mairie", "code_insee_commune": ["92033"]}]')
            # et non comme une vraie liste/dictionnaire Python directement utilisable
            # il faut donc le decoder avec json.loads() avant de pouvoir l'explorer

            if isinstance(pivot, str):
                try:
                    pivot = json.loads(pivot)
                except (json.JSONDecodeError, TypeError):
                    continue
                    # si le texte n'est pas du JSON valide on ne peut rien en faire, on saute
            # si pivot est deja une liste (parfois l'API renvoie directement l'objet
            # decode selon le contexte), on ne touche a rien

            if not pivot:
                continue
                # si pivot est vide on ne peut pas savoir le type de service, on saute

            type_service = pivot[0].get("type_service_local", "")
            # on plonge dans le premier element de la liste pivot pour recuperer le type

            if type_service != "mairie":
                continue
                # FILTRAGE COTE PYTHON : on ne garde que les mairies
                # on saute le CCAS, la PMI, le SAMU, la mission locale, etc.
                # qu'on a vus apparaitre dans les resultats lors de nos tests

            adresse = record.get("adresse", [])
            # meme probleme que pour "pivot" : l'API retourne du texte JSON,
            # pas directement une liste Python

            if isinstance(adresse, str):
                try:
                    adresse = json.loads(adresse)
                except (json.JSONDecodeError, TypeError):
                    continue
                    # si le texte n'est pas du JSON valide on saute cette mairie

            if not adresse:
                continue
                # si pas d'adresse on ne peut pas reconstruire l'adresse texte, on saute

            premiere_adresse = adresse[0]
            # CORRIGE : on n'utilise plus latitude/longitude de cette API (peu fiables,
            # voir la documentation de geocoder_adresse() ci-dessus pour la preuve)
            # On reconstruit a la place l'adresse texte complete, qui elle est fiable

            numero_voie = premiere_adresse.get("numero_voie", "")
            code_postal = premiere_adresse.get("code_postal", "")
            nom_commune = premiere_adresse.get("nom_commune", "")
            adresse_texte = f"{numero_voie} {code_postal} {nom_commune}".strip()
            # on assemble les morceaux de l'adresse en une seule chaine de texte
            # ex: "Place Roland-Nungesser 94130 Nogent-sur-Marne"

            if not adresse_texte:
                continue
                # si on n'a meme pas reussi a construire une adresse, on saute

            coords = geocoder_adresse(adresse_texte)
            # on envoie cette adresse texte fiable a la BAN pour obtenir
            # des coordonnees GPS precises, calculees independamment de
            # ce que l'Annuaire de l'Administration avait fourni

            if coords is None:
                print(f"  Geocodage impossible pour : {adresse_texte}")
                continue
                # si la BAN ne trouve pas l'adresse on saute cette mairie
                # plutot que d'utiliser une coordonnee dont on sait qu'elle peut etre fausse

            resultats.append({
                "nom":       record.get("nom", "Mairie sans nom"),
                "type":      "mairie",
                "source":    "api-lannuaire.service-public.fr + geocodage BAN",
                "latitude":  coords["latitude"],
                "longitude": coords["longitude"]
            })
            # on utilise les coordonnees regeocodees par la BAN, pas celles
            # de l'API Annuaire de l'Administration

            time.sleep(0.1)
            # petite pause pour ne pas surcharger l'API Adresse si plusieurs
            # mairies devaient etre geocodees dans la meme commune (rare mais possible)

        print(f"   {len(resultats)} mairie(s) trouvee(s) pour le code INSEE {code_insee}")
        return resultats
        # on retourne la liste, generalement avec une seule mairie par commune

    except Exception as e:
        if "ConnectionError" in str(type(e)):
            print(f"Pas de connexion internet, impossible d'interroger l'Annuaire de l'Administration.")
        elif "Timeout" in str(type(e)):
            print(f"L'Annuaire de l'Administration ne répond pas, réessayez dans quelques instants.")
        else:
            print(f"Erreur inattendue lors de l'appel à l'Annuaire de l'Administration : {e}")
        return []
        # IMPORTANT : comme pour get_ecoles_gouv(), on retourne une liste vide []
        # et non None, pour ne pas casser le .extend() de l'etape 4








# ETAPE 3b — Récupérer les commissariats via l'Annuaire de l'Administration -------------------------


def get_commissariats_service_public(code_insee: str) -> list[dict]:
    """
    Interroge la même API Annuaire de l'Administration que get_equipements_gouv()
    mais filtre sur type_service_local == "commissariat_police".
    Géocode chaque adresse avec la BAN pour des coordonnées fiables.
    """

    params = {
        "where": f'code_insee_commune="{code_insee}"',
        "limit": 50
    }
    resultats = []

    try:
        print("   Interrogation de l'Annuaire de l'Administration (commissariats)...")
        reponse = requests.get(URL_ANNUAIRE_API, params=params, timeout=15)
        reponse.raise_for_status()
        data = reponse.json()

        for record in data.get("results", []):
            pivot = record.get("pivot", [])
            if isinstance(pivot, str):
                try:
                    pivot = json.loads(pivot)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not pivot:
                continue

            if pivot[0].get("type_service_local", "") != "commissariat_police":
                continue

            adresse = record.get("adresse", [])
            if isinstance(adresse, str):
                try:
                    adresse = json.loads(adresse)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not adresse:
                continue

            premiere_adresse = adresse[0]
            numero_voie = premiere_adresse.get("numero_voie", "")
            code_postal = premiere_adresse.get("code_postal", "")
            nom_commune = premiere_adresse.get("nom_commune", "")
            adresse_texte = f"{numero_voie} {code_postal} {nom_commune}".strip()

            if not adresse_texte:
                continue

            coords = geocoder_adresse(adresse_texte)
            if coords is None:
                print(f"  Géocodage impossible pour : {adresse_texte}")
                continue

            resultats.append({
                "nom":       record.get("nom", "Commissariat sans nom"),
                "type":      "commissariat",
                "source":    "lannuaire.service-public.fr + géocodage BAN",
                "latitude":  coords["latitude"],
                "longitude": coords["longitude"]
            })
            time.sleep(0.1)

        print(f"   {len(resultats)} commissariat(s) trouvé(s) pour le code INSEE {code_insee}")
        return resultats

    except Exception as e:
        if "ConnectionError" in str(type(e)):
            print("Pas de connexion internet, impossible d'interroger l'Annuaire de l'Administration.")
        elif "Timeout" in str(type(e)):
            print("L'Annuaire de l'Administration ne répond pas, réessayez dans quelques instants.")
        else:
            print(f"Erreur inattendue lors de l'appel à l'Annuaire de l'Administration : {e}")
        return []


# ETAPE 3c — Récupérer les gares via l'API SNCF (source prioritaire) --------------------------------


def get_gares_sncf(ville: str) -> list[dict]:
    """
    Interroge l'API officielle SNCF (data.sncf.com / liste-des-gares)
    pour récupérer les gares d'une commune.
    Source utilisée EN PREMIER, avant OSM, pour les gares.
    Les éventuels doublons avec OSM sont ensuite supprimés par coordonnées.
    """
    params = {
        "where":  f'commune like "{ville}"',
        "limit":  50,
        "select": "libelle,commune,coordonnees_geographiques"
    }

    resultats = []

    try:
        print("   Interrogation de l'API SNCF (liste-des-gares)...")
        reponse = requests.get(URL_SNCF_GARES_API, params=params, timeout=15)
        reponse.raise_for_status()

        data = reponse.json()

        for record in data.get("results", []):
            coords = record.get("coordonnees_geographiques")
            if not coords:
                continue
            lat = coords.get("lat")
            lon = coords.get("lon")
            if lat is None or lon is None:
                continue

            resultats.append({
                "nom":       record.get("libelle", "Gare sans nom"),
                "type":      "gare",
                "source":    "SNCF (data.sncf.com)",
                "latitude":  float(lat),
                "longitude": float(lon)
            })

        print(f"   {len(resultats)} gare(s) SNCF trouvée(s) pour '{ville}'")
        return resultats

    except Exception as e:
        if "ConnectionError" in str(type(e)):
            print("   Pas de connexion internet, impossible d'interroger l'API SNCF.")
        elif "Timeout" in str(type(e)):
            print("   L'API SNCF ne répond pas, réessayez dans quelques instants.")
        else:
            print(f"   Erreur inattendue lors de l'appel à l'API SNCF : {e}")
        return []


# ETAPE 4a — Récupérer les établissements de santé via FINESS (registre officiel) ------------------


def _telecharger_finess(chemin_cache: Path, nb_essais: int = 3) -> bool:
    """
    Télécharge le CSV FINESS géolocalisé et le sauvegarde.
    Retente jusqu'à nb_essais fois en cas d'échec. Retourne True si succès.
    """
    # Récupération de l'URL une seule fois (pas besoin de la re-chercher à chaque essai)
    try:
        print("   Recherche du fichier FINESS sur data.gouv.fr...")
        meta = requests.get(
            f"https://www.data.gouv.fr/api/1/datasets/{FINESS_DATASET_ID}/",
            timeout=30
        ).json()

        csv_url = None
        for resource in meta.get("resources", []):
            taille = resource.get("filesize") or 0
            if str(resource.get("format", "")).upper() == "CSV" and taille > 40_000_000:
                csv_url = resource.get("url")
                break

        if not csv_url:
            print("   URL du CSV FINESS géolocalisé introuvable.")
            return False

    except Exception as e:
        print(f"   Impossible de contacter data.gouv.fr : {e}")
        return False

    # Téléchargement avec retry
    for essai in range(1, nb_essais + 1):
        try:
            print(f"   Téléchargement FINESS (~47 Mo) — essai {essai}/{nb_essais}...")
            reponse = requests.get(csv_url, timeout=300, stream=True)
            reponse.raise_for_status()

            chemin_cache.parent.mkdir(parents=True, exist_ok=True)
            with open(chemin_cache, "wb") as f:
                for chunk in reponse.iter_content(chunk_size=65536):
                    f.write(chunk)

            print(f"   FINESS mis en cache : {chemin_cache.name}")
            return True

        except Exception as e:
            print(f"   Essai {essai} échoué : {e}")
            if essai < nb_essais:
                pause = 10 * essai  # 10s, puis 20s
                print(f"   Nouvelle tentative dans {pause} secondes...")
                time.sleep(pause)

    print("   Téléchargement FINESS abandonné après 3 essais.")
    return False


def get_etablissements_finess(code_insee: str, base_dir: Path) -> list[dict]:
    """
    Récupère les établissements de santé d'une commune depuis le registre FINESS.

    Le CSV FINESS (format etalab, sans en-tête) contient deux types de lignes :
      - 'structureet' : infos établissement — [1]=nofinesset, [3]=nom, [12]=code commune
        3 chiffres, [13]=département 2 chiffres, [18]=code catégorie, [19]=libellé catégorie
      - 'geolocalisation' : [1]=nofinesset, [2]=X Lambert-93, [3]=Y Lambert-93

    INSEE reconstitué = col[13].zfill(2) + col[12].zfill(3)
    """
    import csv as csv_module

    chemin_cache = base_dir / "data" / "raw" / "finess_etablissements.csv"

    if chemin_cache.exists():
        age_jours = (datetime.datetime.now() - datetime.datetime.fromtimestamp(
            chemin_cache.stat().st_mtime
        )).days
        if age_jours < 30:
            print(f"   FINESS : cache local ({age_jours}j).")
        else:
            print("   Cache FINESS expiré (> 30 jours), re-téléchargement...")
            if not _telecharger_finess(chemin_cache):
                return []
    else:
        if not _telecharger_finess(chemin_cache):
            return []

    MOTS_CLES_SANTE = ("hospitalier", "clinique", "de santé", "de soins", "médical")

    geolocalisations = {}  # nofinesset → (x_l93, y_l93)
    etablissements   = []  # (nofinesset, nom, type_pm)

    try:
        with open(chemin_cache, encoding="utf-8", errors="replace", newline="") as f:
            reader = csv_module.reader(f, delimiter=";")
            for row in reader:
                if not row:
                    continue
                type_ligne = row[0]

                if type_ligne == "structureet" and len(row) >= 20:
                    dept        = row[13].strip().zfill(2)
                    commune_suf = row[12].strip().zfill(3)
                    if dept + commune_suf != code_insee.strip():
                        continue

                    libelle = row[19].strip().lower()
                    if not any(mc in libelle for mc in MOTS_CLES_SANTE):
                        continue

                    nofinesset = row[1].strip()
                    nom        = row[3].strip() or row[4].strip() or "Établissement sans nom"
                    etablissements.append((nofinesset, nom, row[19].strip()))

                elif type_ligne == "geolocalisation" and len(row) >= 4:
                    try:
                        x = float(row[2].replace(",", "."))
                        y = float(row[3].replace(",", "."))
                        geolocalisations[row[1].strip()] = (x, y)
                    except ValueError:
                        pass

    except Exception as e:
        print(f"   Erreur lecture FINESS : {e}")
        return []

    if not etablissements:
        print(f"   Aucun établissement de santé FINESS pour {code_insee}.")
        return []

    from pyproj import Transformer
    transformer = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)

    resultats = []
    noms_vus  = set()

    for nofinesset, nom, type_pm in etablissements:
        coords_l93 = geolocalisations.get(nofinesset)
        if not coords_l93:
            continue

        lon, lat = transformer.transform(coords_l93[0], coords_l93[1])

        if not (41 < lat < 52 and -6 < lon < 10):
            continue

        cle = f"{nom}_{round(lat, 4)}_{round(lon, 4)}"
        if cle in noms_vus:
            continue
        noms_vus.add(cle)

        resultats.append({
            "nom":       nom,
            "type":      type_pm,
            "source":    "FINESS",
            "latitude":  lat,
            "longitude": lon
        })

    print(f"   {len(resultats)} établissement(s) de santé FINESS trouvé(s) pour {code_insee} :")
    for r in resultats:
        print(f"      • {r['nom']} ({r['type']})")
    return resultats


# ETAPE 4b — Récupérer les lieux complémentaires via OpenStreetMap (Overpass) ----------------------


def get_PM_osm(osm_area_id: int, categories: list = None, categories_supplementaires: list = None) -> list[dict]:
    """
    Interroge l'API Overpass pour récupérer les lieux complémentaires
    (hôpital, clinique, pharmacie, poste, commissariat, lieu de culte,
    centre sportif, gare, supermarché...) dans les frontières exactes
    de la commune, en utilisant l'osm_area_id calculé à l'étape 1b.

    CORRIGE (3) : meme avec des pauses plus longues, certaines categories
    echouent encore au hasard a cause des limites d'Overpass (429).
    On ajoute donc une DEUXIEME PASSE automatique en fin de fonction :
    on retient quelles categories ont echoue lors du premier passage,
    on attend un peu, puis on les reessaie une seule fois chacune.
    """

    url = "https://overpass-api.de/api/interpreter"
    headers = {
        "User-Agent": "DefiaccessPM/1.0 (association accessibilite)",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    resultats = []
    noms_vus = set()
    categories_echouees = []
    # NOUVEAU : liste qui va retenir les categories qui ont echoue
    # au premier passage, pour les retenter ensuite

    def interroger_categorie(categorie):
        """
        Sous-fonction qui interroge UNE SEULE categorie aupres d'Overpass.
        Retourne True si ca a reussi, False si ca a echoue.
        On la met a part pour pouvoir l'appeler deux fois (1ere et 2eme passe)
        sans dupliquer tout le code.
        """
        type_pm     = categorie["type"]
        osm_filters = categorie["osm_filters"]

        query = f"""
[out:json][timeout:25];
area({osm_area_id})->.zone;
(
  node{osm_filters}(area.zone);
  way{osm_filters}(area.zone);
);
out center;
"""

        try:
            print(f"   Recherche OSM : {type_pm}...")
            reponse = requests.post(url, data={"data": query}, headers=headers, timeout=30)

            if reponse.status_code == 429:
                print(f"      Limite atteinte, pause de 10 secondes...")
                time.sleep(10)
                reponse = requests.post(url, data={"data": query}, headers=headers, timeout=30)

            reponse.raise_for_status()

            elements = reponse.json().get("elements", [])

            for el in elements:
                if el["type"] == "node":
                    lat = el.get("lat")
                    lon = el.get("lon")
                elif el["type"] == "way":
                    center = el.get("center", {})
                    lat = center.get("lat")
                    lon = center.get("lon")
                else:
                    continue

                if lat is None or lon is None:
                    continue

                tags = el.get("tags", {})
                nom = tags.get("name", tags.get("operator", f"{type_pm} sans nom"))

                cle_unicite = f"{nom}_{round(lat, 5)}_{round(lon, 5)}"
                if cle_unicite in noms_vus:
                    continue
                noms_vus.add(cle_unicite)

                resultats.append({
                    "nom":       nom,
                    "type":      type_pm,
                    "source":    "OpenStreetMap",
                    "latitude":  lat,
                    "longitude": lon
                })

            print(f"      → {len(elements)} {type_pm}(s) trouve(s)")
            return True
            # on signale que cette categorie a reussi

        except Exception as e:
            print(f"    Erreur OSM pour '{type_pm}' : {e}")
            return False
            # on signale que cette categorie a echoue

    # ---- PREMIERE PASSE : on essaie toutes les categories une fois ----
    toutes_categories = (categories if categories is not None else CATEGORIES_OSM_DISPONIBLES) + (categories_supplementaires or [])
    for categorie in toutes_categories:
        succes = interroger_categorie(categorie)
        if not succes:
            categories_echouees.append(categorie)
            # on note cette categorie pour la retenter plus tard

        time.sleep(5)
        # pause de 5 secondes entre chaque categorie

    # ---- DEUXIEME PASSE : on retente uniquement celles qui ont echoue ----
    categories_echouees_2 = []
    if categories_echouees:
        print(f"\n    Deuxieme passe pour {len(categories_echouees)} categorie(s) en echec...")
        time.sleep(10)
        # pause supplementaire avant de recommencer, pour laisser
        # Overpass se "reposer" et reinitialiser sa limite de frequence

        for categorie in categories_echouees:
            succes = interroger_categorie(categorie)
            if not succes:
                categories_echouees_2.append(categorie)
            time.sleep(5)

    # ---- TROISIEME PASSE : derniere tentative pour celles qui ont encore echoue ----
    if categories_echouees_2:
        print(f"\n    Troisieme passe pour {len(categories_echouees_2)} categorie(s) en echec...")
        time.sleep(15)
        # pause plus longue avant la 3e tentative

        for categorie in categories_echouees_2:
            interroger_categorie(categorie)
            # si ca echoue encore, on abandonne definitivement cette categorie
            time.sleep(5)

    print(f"\n   {len(resultats)} lieu(x) OSM trouve(s) au total")
    return resultats






# Dédoublonnage géographique inter-sources --------------------------------------------------------


def _distance_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance approximative en mètres entre deux points GPS (formule haversine)."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def dedoublonner_par_coordonnees(pm_list: list[dict], seuil_metres: int = 30) -> list[dict]:
    """
    Supprime les doublons géographiques ENTRE SOURCES DIFFÉRENTES uniquement.
    Deux PM de la même source (ex. deux entrées FINESS) sont toujours conservés
    même s'ils sont proches (bâtiments distincts d'un même campus hospitalier).
    En cas de doublon inter-sources, on garde celui de la source la plus fiable.

    Ordre de priorité (0 = meilleur) :
        SNCF > gouvernemental (education / annuaire / FINESS) > OSM
    """
    PRIORITE_SOURCE = {
        "SNCF (data.sncf.com)":                                      0,
        "data.education.gouv.fr":                                     1,
        "api-lannuaire.service-public.fr + geocodage BAN":            1,
        "lannuaire.service-public.fr + géocodage BAN":                1,
        "FINESS":                                                      1,
        "OpenStreetMap":                                               2,
    }

    gardes = []

    for pm in pm_list:
        lat, lon = pm["latitude"], pm["longitude"]
        doublon_trouve = False

        for i, garde in enumerate(gardes):
            # On ne considère le doublon que si les deux PM viennent de sources différentes
            if pm["source"] == garde["source"]:
                continue
            if _distance_metres(lat, lon, garde["latitude"], garde["longitude"]) <= seuil_metres:
                prio_nouveau  = PRIORITE_SOURCE.get(pm["source"],    99)
                prio_existant = PRIORITE_SOURCE.get(garde["source"], 99)
                if prio_nouveau < prio_existant:
                    gardes[i] = pm  # on remplace par la source plus fiable
                doublon_trouve = True
                break

        if not doublon_trouve:
            gardes.append(pm)

    nb_supprimes = len(pm_list) - len(gardes)
    if nb_supprimes > 0:
        print(f"   Dédoublonnage inter-sources : {nb_supprimes} doublon(s) supprimé(s) sur {len(pm_list)} PM")

    return gardes


# ETAPE 5 — Orchestrer toutes les sources et exporter en Excel ------------------------------------


def _choisir_categories_osm() -> list[dict]:
    """
    Affiche les catégories OSM disponibles et demande à l'utilisateur
    lesquelles inclure dans la recherche de PM (comme le choix des types de voies).
    """
    print("\n" + "=" * 62)
    print("   SÉLECTION DES CATÉGORIES DE POINTS DE MESURE (PM) OSM")
    print("=" * 62)
    print("\n  Attention : certaines communes ont beaucoup de PM.")
    print("  Les écoles, mairies et établissements de santé sont")
    print("  toujours inclus. Choisissez les catégories OSM à ajouter :\n")

    for i, cat in enumerate(CATEGORIES_OSM_DISPONIBLES, 1):
        print(f"   {i:2d}. {cat['label']}")

    print("\n  Entrez les numéros séparés par des virgules  (ex: 1,4,7)")
    print("  ou appuyez sur Entrée pour toutes les inclure.")
    #choix = input("\n  Votre sélection : ").strip()

    '''ATTENTION CHANGEMENT PROVISOIR PCQ FLEMME DE TOUT CHANGER'''
    choix = None

    if not choix:
        print("  → Toutes les catégories OSM seront incluses.\n")
        return [{"type": c["type"], "osm_filters": c["osm_filters"]} for c in CATEGORIES_OSM_DISPONIBLES]

    categories_choisies = []
    for segment in choix.split(","):
        try:
            idx = int(segment.strip()) - 1
            if 0 <= idx < len(CATEGORIES_OSM_DISPONIBLES):
                cat = CATEGORIES_OSM_DISPONIBLES[idx]
                categories_choisies.append({"type": cat["type"], "osm_filters": cat["osm_filters"]})
                print(f"   ✓ {cat['label']}")
        except ValueError:
            pass

    if not categories_choisies:
        print("  → Aucune sélection valide, toutes les catégories incluses par défaut.\n")
        return [{"type": c["type"], "osm_filters": c["osm_filters"]} for c in CATEGORIES_OSM_DISPONIBLES]

    print(f"\n  → {len(categories_choisies)} catégorie(s) sélectionnée(s).\n")
    return categories_choisies


def construire_dataframe_PM(ville: str) -> pd.DataFrame:
    """
    Fonction principale qui orchestre tout le pipeline d'identification des PM :
    1. Recupere le code INSEE et l'osm_area_id de la commune
    2. Recupere les ecoles (source gouvernementale)
    3. Recupere la mairie (source gouvernementale + geocodage BAN)
    4. Recupere les lieux complementaires (OSM)
    5. Fusionne tout dans un seul DataFrame
    6. Exporte le resultat en fichier Excel

    NOTE : le dedoublonnage geographique entre sources n'est pas encore
    implemente -- a ajouter dans une prochaine etape une fois qu'on aura
    verifie sur des cas reels si des doublons apparaissent vraiment.
    """

    print(f"\n=== Construction du DataFrame PM pour '{ville}' ===\n")

    # ETAPE 1 : identifiants de la commune
    code_insee = get_code_insee_api(ville)
    if code_insee is None:
        print(" Impossible de continuer sans code INSEE valide.")
        return pd.DataFrame()
        # on retourne un DataFrame vide plutot que None, pour que le code
        # appelant puisse toujours faire .empty ou len() sans planter

    osm_area_id = get_osm_area_id(ville)
    if osm_area_id is None:
        print("  osm_area_id non trouve, la recherche OSM sera ignoree.")

    # ETAPE 2 : on accumule tous les PM dans une seule liste
    tous_les_pm = []

    ecoles = get_ecoles_gouv(code_insee)
    tous_les_pm.extend(ecoles)
    # .extend() ajoute chaque element de la liste ecoles a tous_les_pm
    # (contrairement a .append() qui ajouterait la liste entiere comme un seul bloc)

    mairies = get_equipements_gouv(code_insee)
    tous_les_pm.extend(mairies)

    commissariats = get_commissariats_service_public(code_insee)
    tous_les_pm.extend(commissariats)

    # Gares via l'API SNCF (source prioritaire) — OSM complète si nécessaire
    gares_sncf = get_gares_sncf(ville)
    tous_les_pm.extend(gares_sncf)

    # Établissements de santé via FINESS (hôpitaux, cliniques, centres de soins)
    base_dir_finess = Path(__file__).parent.parent
    etablissements_sante = get_etablissements_finess(code_insee, base_dir_finess)
    tous_les_pm.extend(etablissements_sante)

    if osm_area_id:
        categories_choisies = _choisir_categories_osm()
        # Si FINESS n'a rien retourné, on utilise OSM comme filet de sécurité
        if not etablissements_sante:
            print("   FINESS indisponible — recherche hôpitaux/cliniques via OSM (fallback)...")
            lieux_osm = get_PM_osm(osm_area_id, categories=categories_choisies,
                                   categories_supplementaires=CATEGORIES_OSM_SANTE_FALLBACK)
        else:
            lieux_osm = get_PM_osm(osm_area_id, categories=categories_choisies)
        tous_les_pm.extend(lieux_osm)

    # Dédoublonnage géographique (SNCF + OSM pour les gares, et inter-sources en général)
    tous_les_pm = dedoublonner_par_coordonnees(tous_les_pm)

    # ETAPE 3 : construction du DataFrame a partir de la liste de dictionnaires
    df = pd.DataFrame(tous_les_pm, columns=["nom", "type", "source", "latitude", "longitude"])
    # columns= force l'ordre des colonnes meme si certains dictionnaires
    # avaient leurs cles dans un ordre different

    if df.empty:
        print(" Aucun PM trouve pour cette commune.")
        return df

    df["coordonnees"] = df["latitude"].astype(str) + ", " + df["longitude"].astype(str)
    # on ajoute une colonne texte combinee, au meme format que dans
    # le reste du projet (ex: "48.843436, 2.187209")

    df = df.sort_values(["type", "nom"]).reset_index(drop=True)
    # on trie par type puis par nom pour que le fichier Excel soit lisible

    print(f"\n {len(df)} PM au total pour {ville}")

    return df



def exporter_PM_excel(df: pd.DataFrame, nom_fichier: str = "PM_export.xlsx", dossier_sortie: str = ".") -> str | None:
 
    if df is None or df.empty:
        print(" DataFrame vide : aucun fichier Excel genere.")
        return None
 
    # index=False : on n'ecrit pas la colonne d'index du DataFrame
    # les titres de colonnes (header) sont ecrits automatiquement par to_excel
    dossier_export = os.path.join(dossier_sortie, "PM")
    os.makedirs(dossier_export, exist_ok=True)
    chemin_fichier = os.path.join(dossier_export, nom_fichier)
    df.to_excel(chemin_fichier, index=False)
 
    print(f" Fichier Excel exporte : {nom_fichier}  ({len(df)} PM)")
    return chemin_fichier



#TESTES : ---------------------------------------------------------------------------------------------------------
if __name__ == "__main__":

    ville = input("Entrez le nom de la commune : ").strip()

    df_pm = construire_dataframe_PM(ville)

    if not df_pm.empty:
        print("\n=== Apercu du DataFrame final ===")
        print(df_pm.to_string(index=False))






def construire_dataframe_PM_sans_input(ville: str, categories_osm: list[dict] | None = None) -> pd.DataFrame:
    """
    Identique à construire_dataframe_PM(), mais sans aucun appel à input().
    categories_osm : liste de catégories OSM déjà choisies via l'interface graphique
                      (ex: cases cochées en Streamlit), au format
                      [{"type": "gare", "osm_filters": '["railway"="station"]'}, ...].
                      None ou [] = toutes les catégories de CATEGORIES_OSM_DISPONIBLES.
    """
    print(f"\n=== Construction du DataFrame PM pour '{ville}' (mode interface) ===\n")

    code_insee = get_code_insee_api(ville)
    if code_insee is None:
        print(" Impossible de continuer sans code INSEE valide.")
        return pd.DataFrame()

    osm_area_id = get_osm_area_id(ville)
    if osm_area_id is None:
        print("  osm_area_id non trouvé, la recherche OSM sera ignorée.")

    tous_les_pm = []

    tous_les_pm.extend(get_ecoles_gouv(code_insee))
    tous_les_pm.extend(get_equipements_gouv(code_insee))
    tous_les_pm.extend(get_commissariats_service_public(code_insee))
    tous_les_pm.extend(get_gares_sncf(ville))

    base_dir_finess = Path(__file__).parent.parent
    etablissements_sante = get_etablissements_finess(code_insee, base_dir_finess)
    tous_les_pm.extend(etablissements_sante)

    if osm_area_id:
        # Pas d'input ici : on utilise directement ce qui a été coché dans l'interface
        categories_choisies = categories_osm if categories_osm else [
            {"type": c["type"], "osm_filters": c["osm_filters"]} for c in CATEGORIES_OSM_DISPONIBLES
        ]
        if not etablissements_sante:
            print("   FINESS indisponible — recherche hôpitaux/cliniques via OSM (fallback)...")
            lieux_osm = get_PM_osm(osm_area_id, categories=categories_choisies,
                                   categories_supplementaires=CATEGORIES_OSM_SANTE_FALLBACK)
        else:
            lieux_osm = get_PM_osm(osm_area_id, categories=categories_choisies)
        tous_les_pm.extend(lieux_osm)

    tous_les_pm = dedoublonner_par_coordonnees(tous_les_pm)

    df = pd.DataFrame(tous_les_pm, columns=["nom", "type", "source", "latitude", "longitude"])
    if df.empty:
        print(" Aucun PM trouvé pour cette commune.")
        return df

    df["coordonnees"] = df["latitude"].astype(str) + ", " + df["longitude"].astype(str)
    df = df.sort_values(["type", "nom"]).reset_index(drop=True)

    print(f"\n {len(df)} PM au total pour {ville}")
    return df


def construire_dataframe_PM2(ville_cible, categories_filtrees=None):
    """
    Version 2 de la génération des Points d'Intérêt (PM) avec filtrage
    thématique à la source et nettoyage des colonnes pour le pipeline terrain.
    
    :param ville_cible: Nom de la commune (ex: "Garches")
    :param categories_filtrees: Liste des catégories sélectionnées dans l'interface.
                                Si None ou vide, toutes les catégories sont conservées.
    """
    import pandas as pd
    print(f"[PM2] Lancement de la génération filtrée pour : {ville_cible}")
    
    # 1. On appelle ta fonction d'origine pour récupérer le gros DataFrame brut unifié
    df_global = construire_dataframe_PM(ville_cible)
    
    if df_global.empty:
        print("[PM2] Attention : Le DataFrame brut renvoyé est vide.")
        return df_global

    # 2. Normalisation ou création d'une colonne de catégorie claire
    # Si ton script d'origine n'a pas de colonne 'categorie', on la déduit de la 'source' ou du 'type'
    if 'categorie' not in df_global.columns:
        if 'source' in df_global.columns:
            df_global['categorie'] = df_global['source']
        elif 'type' in df_global.columns:
            df_global['categorie'] = df_global['type']
        else:
            # Fallback si aucune colonne de type n'est trouvée
            df_global['categorie'] = "Autre POI"

    # 3. Application du filtre si l'utilisateur a fait un choix dans Streamlit
    if categories_filtrees:
        print(f"[PM2] Application du filtre. Catégories demandées : {categories_filtrees}")
        # On ne garde que les lignes dont la catégorie est dans la liste
        df_global = df_global[df_global['categorie'].isin(categories_filtrees)].reset_index(drop=True)
    else:
        print("[PM2] Aucun filtre spécifié, conservation de l'intégralité des lieux.")

    # 4. Nettoyage de sécurité pour le pipeline de routage (lat/lon valides et colonnes requises)
    colonnes_majeures = ['lieu', 'latitude', 'longitude', 'categorie']
    for col in colonnes_majeures:
        if col == 'lieu' and 'lieu' not in df_global.columns:
            # Si 'lieu' n'existe pas, on prend le nom de l'établissement ou de la rue
            for nom_col in ['nom', 'name', 'etablissement', 'intersection']:
                if nom_col in df_global.columns:
                    df_global['lieu'] = df_global[nom_col]
                    break
            else:
                df_global['lieu'] = "Lieu sans nom"

    # On s'assure que la latitude et la longitude sont bien au format numérique (float)
    df_global['latitude'] = pd.to_numeric(df_global['latitude'], errors='coerce')
    df_global['longitude'] = pd.to_numeric(df_global['longitude'], errors='coerce')
    df_global = df_global.dropna(subset=['latitude', 'longitude']).reset_index(drop=True)

    print(f"[PM2] Fin du filtrage. {len(df_global)} lieux conservés.")
    return df_global