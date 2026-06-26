"""
FICHIER : telecharger_intersections.py

# BUT : Télécharger automatiquement les intersections de rues d'une ville française
      depuis le dataset officiel data.gouv.fr :
      "Intersections des rues et routes de France"
      (source : OpenStreetMap, mis en forme par Christian Quest)

      Les données sont organisées par département sous forme de fichiers
      GeoJSON compressés (.geojson.gz). On identifie d'abord le département
      de la ville saisie, on télécharge le fichier correspondant, puis on
      filtre uniquement les intersections de la ville demandée.

LOGIQUE GLOBALE :
    Ville saisie par l'utilisateur
        ↓
    1. Recherche du département + code INSEE via geo.api.gouv.fr (API officielle IGN/INSEE)
        ↓
    2a. Téléchargement du fichier intersections-{dept}.geojson.gz depuis osm13.openstreetmap.fr
    2b. Si échec → fallback sur data.gouv.fr (même dataset, source de secours)
        ↓
    3. Filtrage des intersections par code INSEE (citycode) en priorité,
       sinon par nom de ville normalisé (tirets = espaces, minuscules)
        ↓
    4. Sauvegarde dans intersections/intersections_{dept}.geojson
        ↓
    5. Chargement en DataFrame + normalisation des noms de rues
        ↓
    6. Filtrage interactif par type de voie (Avenue, Boulevard, Route, etc.)

LISTE DES FONCTIONS :

- normaliser() :
    # ROLE : Normaliser un nom de ville pour la comparaison de texte
              (minuscules, tirets remplacés par des espaces)
    # ARGUMENTS : "texte" de type str
    # REPONSE : str normalisé

- trouver_departements() :
    # ROLE : Interroger geo.api.gouv.fr pour trouver le département
              et le code INSEE d'une ville
    # ARGUMENTS : "nom_ville" de type str
    # REPONSE : list[ (code_dept, nom_commune, code_insee) ]

- telecharger_intersections_dept() :
    # ROLE : Télécharger et décompresser le fichier GeoJSON d'un département
              depuis le serveur OpenStreetMap, avec fallback sur data.gouv.fr
    # ARGUMENTS : "code_dept" de type str (ex: "94", "2A", "971")
    # REPONSE : dict (GeoJSON complet) ou None si toutes les sources échouent

- telecharger_depuis_datagouv() :
    # ROLE : Source de secours si OSM échoue — cherche la ressource du département
              dans le dataset data.gouv.fr et la télécharge
    # ARGUMENTS : "code_dept" de type str
    # REPONSE : dict (GeoJSON complet) ou None si introuvable

- filtrer_par_ville() :
    # ROLE : Filtrer les intersections d'un GeoJSON pour ne garder
              que celles de la ville demandée
    # ARGUMENTS : "geojson" dict, "nom_ville" str, "code_insee" str (optionnel)
    # REPONSE : list[dict] des features GeoJSON correspondant à la ville

- afficher_exemple_proprietes() :
    # ROLE : Afficher les propriétés du premier élément du GeoJSON
              pour diagnostiquer un problème de filtrage
    # ARGUMENTS : "geojson" dict
    # REPONSE : None (affichage console uniquement)

- sauvegarder() :
    # ROLE : Écrire les intersections filtrées dans un fichier .geojson
              dans le dossier "intersections/"
    # ARGUMENTS : "features" list, "code_dept" str
    # REPONSE : str (chemin du fichier créé)

- telecharger_intersections_ville() :
    # ROLE : Fonction principale qui orchestre toutes les étapes
              (recherche département → téléchargement → filtrage → sauvegarde)
    # ARGUMENTS : "nom_ville" de type str
    # REPONSE : list[str] (chemins des fichiers créés)

- normaliser_nom_intersection() :
    # ROLE : Normaliser les noms d'intersections (espaces, tirets, casse)
              pour qu'ils soient lisibles et cohérents
    # ARGUMENTS : "nom" de type str
    # REPONSE : str normalisé

- choisir_types_voies() :
    # ROLE : Afficher un menu interactif pour que l'utilisateur choisisse
              les types de voies à garder (Avenue, Boulevard, Route, etc.)
    # ARGUMENTS : aucun
    # REPONSE : list[str] des types choisis, ou [] pour tout garder

- charger_en_dataframe() :
    # ROLE : Lire le fichier GeoJSON local, le convertir en DataFrame,
              normaliser les noms et filtrer par type de voie
    # ARGUMENTS : "chemin_geojson" str
    # REPONSE : pd.DataFrame avec colonnes latitude | longitude | intersection | Ville/Commune
"""

import requests
import gzip
import json
import os
import pandas as pd

# URL du fichier GeoJSON compressé par département sur le serveur OpenStreetMap
# {dept} sera remplacé par le numéro de département (ex: 94, 75, 2A, 971...)
# Tous les fichiers sont au format .geojson.gz (GeoJSON compressé avec gzip)
BASE_URL_OSM = "https://osm13.openstreetmap.fr/~cquest/osm_poi/intersections-geojson/intersections-{dept}.geojson.gz"

# URL de l'API data.gouv.fr pour le dataset des intersections
# Utilisée comme source de secours si le serveur OSM est indisponible
BASE_URL_DATAGOUV = "https://www.data.gouv.fr/api/1/datasets/intersections-des-rues-et-routes-de-france/"

# URL de l'API officielle geo.api.gouv.fr (INSEE/IGN)
# Même API que dans identification_PM.py : 100% officielle, toutes les communes
# françaises y sont référencées, et elle est conçue pour être interrogée automatiquement
GEO_API_URL = "https://geo.api.gouv.fr/communes"

# Dossier local où seront sauvegardés les fichiers GeoJSON téléchargés
# Il sera créé automatiquement s'il n'existe pas (voir sauvegarder())
DOSSIER_SORTIE = "intersections"

# Types de voies disponibles pour le filtrage interactif
# L'utilisateur pourra choisir lesquels conserver dans le DataFrame final
TYPES_VOIES = [
    "Avenue",
    "Boulevard",
    "Route",
    "Esplanade",
    "Rue",
    "Allée",
    "Place",
    "Square",
    "Passage",
    "Impasse",
    "Voie",
    "Chemin",
    "Résidence",
    "Rond-Point",
]


# ETAPE 0 — Normalisation des noms de villes pour la comparaison -----------------------------------


def normaliser(texte):
    """
    Convertit un nom de ville en forme normalisée pour la comparaison :
    tout en minuscules, tirets remplacés par des espaces, espaces multiples supprimés.

    POURQUOI CETTE FONCTION EXISTE :
    Les noms de villes dans le GeoJSON utilisent des tirets (ex: "Fontenay-sous-Bois")
    alors que l'utilisateur tape souvent avec des espaces (ex: "Fontenay sous bois").
    Sans normalisation, la comparaison de chaînes échoue même si c'est la même ville.
    """

    return texte.lower().replace("-", " ").replace("  ", " ").strip()
    # .lower()           : tout en minuscules pour ignorer les différences de casse
    # .replace("-", " ") : tiret → espace (Fontenay-sous-Bois → Fontenay sous Bois)
    # .replace("  ", " "): au cas où deux espaces se retrouvent côte à côte
    # .strip()           : supprime les espaces en début et fin de chaîne


# ETAPE 1 — Trouver le département et le code INSEE via geo.api.gouv.fr ---------------------------


def trouver_departements(nom_ville):
    """
    Interroge l'API officielle geo.api.gouv.fr (INSEE/IGN) pour trouver
    le département et le code INSEE d'une ville.

    POURQUOI geo.api.gouv.fr :
    C'est la même API utilisée dans identification_PM.py. Elle est officielle,
    sans clé d'accès, et retourne directement le code INSEE et le code département
    dont on a besoin pour construire l'URL de téléchargement du fichier GeoJSON.

    GESTION DES HOMONYMES :
    Plusieurs villes peuvent porter le même nom dans des départements différents
    (ex: "Saint-Martin" existe dans de nombreux départements). La fonction
    retourne TOUTES les correspondances ; c'est telecharger_intersections_ville()
    qui demandera à l'utilisateur de choisir si nécessaire.
    """

    reponse = requests.get(GEO_API_URL, params={
        "nom":    nom_ville,
        # le nom de la ville tapé par l'utilisateur
        "fields": "code,nom,codeDepartement",
        # on demande uniquement le code INSEE, le nom et le numéro de département
        # pour ne pas surcharger la réponse avec des infos inutiles
        "boost":  "population",
        # si plusieurs communes portent le même nom, on priorise la plus peuplée
        # (ex: "Lyon" → la vraie Lyon avant les petites communes homonymes)
        "limit":  10
        # on accepte jusqu'à 10 résultats pour couvrir les homonymes
    })
    reponse.raise_for_status()
    # vérifie que l'API a répondu correctement (200 = ok, autre = erreur)

    communes = reponse.json()
    # convertit la réponse texte en liste Python de dictionnaires

    if not communes:
        print(f"Aucune commune trouvée pour '{nom_ville}'.")
        return []
        # si l'API ne trouve rien, on retourne une liste vide
        # (la fonction appelante vérifiera si la liste est vide)

    # Dédoublonnage par département : si deux communes du même département
    # correspondent (ex: une grande et une petite "Metz"), on ne garde que la première
    resultats = {}
    for c in communes:
        dept = c.get("codeDepartement", "")
        # le numéro de département (ex: "94", "75", "2A", "971")
        if dept and dept not in resultats:
            resultats[dept] = (c["nom"], c.get("code", ""))
            # on retient : nom officiel de la commune + son code INSEE (ex: "94033")

    return [(dept, nom, code) for dept, (nom, code) in resultats.items()]
    # format de sortie : liste de tuples (code_dept, nom_commune, code_insee)
    # ex: [("94", "Fontenay-sous-Bois", "94033")]


# ETAPE 2a — Télécharger le fichier GeoJSON depuis OSM --------------------------------------------


def telecharger_intersections_dept(code_dept):
    """
    Télécharge le fichier GeoJSON d'un département en essayant d'abord
    data.gouv.fr (source officielle), puis OSM en fallback si data.gouv.fr échoue.

    POURQUOI data.gouv.fr EN PREMIER :
    data.gouv.fr est la plateforme officielle de l'État français, avec une
    meilleure disponibilité que le serveur OSM (osm13.openstreetmap.fr) qui
    est une machine personnelle de Christian Quest pouvant être indisponible.

    FORMAT DES FICHIERS :
    Les fichiers sont au format GeoJSON compressé avec gzip (.geojson.gz).
    On les décompresse en mémoire avec le module gzip de Python, sans
    écrire de fichier temporaire sur le disque.
    """

    # TENTATIVE 1 : data.gouv.fr (source officielle, prioritaire)
    print(f"  → Tentative 1 sur data.gouv.fr...")
    geojson = telecharger_depuis_datagouv(code_dept)
    if geojson is not None:
        return geojson
        # si data.gouv.fr a répondu, on retourne directement le résultat

    # TENTATIVE 2 : data.gouv.fr une deuxième fois (le serveur peut avoir eu un pic de charge)
    print(f"  → Tentative 2 sur data.gouv.fr...")
    geojson = telecharger_depuis_datagouv(code_dept)
    if geojson is not None:
        return geojson

    # TENTATIVE 3 : OSM en fallback si les deux tentatives data.gouv.fr ont échoué
    url = BASE_URL_OSM.format(dept=code_dept)
    # on construit l'URL complète en remplaçant {dept} par le numéro réel
    # ex: "https://osm13.openstreetmap.fr/.../intersections-94.geojson.gz"

    print(f"  [OSM] Fallback : téléchargement depuis : {url}")
    try:
        reponse = requests.get(url, stream=True, timeout=60)
        # stream=True : télécharge le fichier par morceaux pour économiser la RAM
        # timeout=60  : abandonne si pas de réponse en 60 secondes

        if reponse.status_code == 404:
            print(f"  [OSM] Fichier introuvable (404) pour le département {code_dept}.")
            return None
            # les deux sources ont échoué, on abandonne

        reponse.raise_for_status()
        # vérifie que le téléchargement s'est bien passé (autre que 200 ou 404 = erreur)

        contenu_gz = reponse.content
        # récupère l'intégralité du fichier téléchargé sous forme d'octets (bytes)

        contenu_json = gzip.decompress(contenu_gz)
        # décompresse le fichier gzip en mémoire → on obtient du texte JSON brut

        return json.loads(contenu_json)
        # convertit le texte JSON en dictionnaire Python (format GeoJSON)

    except Exception as e:
        print(f"  [OSM] Échec : {e}")
        return None
        # les deux sources ont échoué


# ETAPE 2b — Source principale data.gouv.fr (OSM = fallback) ------------------------------------


def telecharger_depuis_datagouv(code_dept):
    """
    Source principale : cherche la ressource du département dans le dataset
    data.gouv.fr et la télécharge.

    COMMENT ÇA MARCHE :
    On interroge l'API data.gouv.fr pour lister toutes les ressources du dataset,
    puis on cherche celle dont le titre contient le numéro de département.
    Si introuvable, telecharger_intersections_dept() basculera sur OSM.
    """

    dept = code_dept.zfill(2)
    # on force le code département sur 2 chiffres (ex: "1" → "01", "94" reste "94")

    try:
        print(f"  [data.gouv.fr] Récupération de la liste des ressources...")
        reponse = requests.get(BASE_URL_DATAGOUV, timeout=15)
        reponse.raise_for_status()
        dataset = reponse.json()
        # récupère les métadonnées du dataset, dont la liste de toutes ses ressources

        for resource in dataset.get("resources", []):
            # on parcourt chaque ressource du dataset pour trouver celle du bon département
            titre = resource.get("title", "").lower()
            # le titre de la ressource, en minuscules pour la comparaison

            if (f"-{dept}" in titre or f"_{dept}" in titre or
                    titre.endswith(dept) or f"dep{dept}" in titre):
                # on cherche le numéro de département dans le titre
                # ex: "intersections-94", "dep94", "export_94"...

                url = resource.get("url", "")
                if not url:
                    continue

                print(f"  [data.gouv.fr] Téléchargement depuis : {url}")
                r2 = requests.get(url, timeout=120)
                r2.raise_for_status()

                if url.endswith(".gz"):
                    return json.loads(gzip.decompress(r2.content))
                    # si le fichier est compressé, on le décompresse comme pour OSM
                return r2.json()
                # sinon on le lit directement comme du JSON

        print(f"  [data.gouv.fr] Aucune ressource trouvée pour le département {dept}.")
        return None

    except Exception as e:
        print(f"  [data.gouv.fr] Échec : {e}")
        return None
        # si data.gouv.fr aussi échoue, on retourne None
        # la fonction appelante affichera un message d'erreur


# ETAPE 3 — Filtrer les intersections pour la ville demandée -------------------------------------


def filtrer_par_ville(geojson, nom_ville, code_insee=None):
    """
    Parcourt toutes les intersections d'un département et ne garde que celles
    qui appartiennent à la ville demandée.

    DEUX MÉTHODES DE FILTRAGE (dans l'ordre de priorité) :
    1. Par code INSEE (champ "citycode" dans le GeoJSON) → méthode la plus fiable
       car le code INSEE est unique pour chaque commune, sans ambiguïté de graphie
    2. Par nom de ville normalisé (si le code INSEE ne matche pas) → méthode de
       secours qui gère les différences tirets/espaces grâce à normaliser()

    POURQUOI LE CODE INSEE EN PRIORITÉ :
    Le nom d'une ville peut avoir plusieurs orthographes ("Saint Martin" vs
    "Saint-Martin"). Le code INSEE est lui toujours identique, quelle que
    soit la source. C'est donc le critère le plus fiable pour filtrer.
    """

    nom_normalise = normaliser(nom_ville)
    # version normalisée du nom tapé par l'utilisateur, pour la comparaison de texte

    features_filtrees = []
    # liste vide qui va accumuler les intersections correspondant à la ville

    for feature in geojson.get("features", []):
        # on parcourt chaque intersection du département
        # .get("features", []) évite une erreur si la clé "features" est absente

        props = feature.get("properties", {})
        # les propriétés de cette intersection (nom, citycode, depcode...)

        # MÉTHODE 1 : filtrage par code INSEE (le plus fiable)
        if code_insee and props.get("citycode") == code_insee:
            features_filtrees.append(feature)
            continue
            # si le citycode correspond, on ajoute cette intersection et on passe à la suivante
            # "continue" évite de tester aussi la méthode 2 pour le même élément

        # MÉTHODE 2 : filtrage par nom normalisé (secours si pas de citycode)
        ville_feature = normaliser(
            props.get("city", "") or
            props.get("commune", "") or
            ""
            # on essaie les deux noms de champs possibles pour la ville
            # "or" passe au suivant si le champ est vide ou absent
        )

        if ville_feature and (nom_normalise in ville_feature or ville_feature in nom_normalise):
            features_filtrees.append(feature)
            # on accepte si l'un des deux noms contient l'autre
            # (gère les cas où le nom tapé est partiel ou légèrement différent)

    return features_filtrees
    # retourne la liste des intersections filtrées, possiblement vide


# ETAPE 3b — Diagnostic si aucune intersection trouvée -------------------------------------------


def afficher_exemple_proprietes(geojson):
    """
    Affiche les propriétés du premier élément du GeoJSON pour aider à
    comprendre pourquoi le filtrage n'a trouvé aucune intersection.

    POURQUOI CETTE FONCTION EXISTE :
    Si filtrer_par_ville() ne trouve rien, c'est souvent parce que le champ
    qui contient le nom de la ville s'appelle différemment de ce qu'on attend.
    En affichant les propriétés brutes du premier élément, on peut voir
    directement les vrais noms de champs disponibles dans le GeoJSON.
    """

    features = geojson.get("features", [])
    if features:
        print(f"  Exemple de propriétés dans ce fichier :")
        for k, v in features[0].get("properties", {}).items():
            print(f"    {k}: {v}")
            # on affiche chaque clé et sa valeur pour le premier élément


# ETAPE 4 — Sauvegarder les intersections filtrées -----------------------------------------------


def sauvegarder(features, code_insee):
    """
    Écrit les intersections filtrées dans un fichier GeoJSON dans le dossier
    "intersections/" du projet.

    FORMAT DU NOM DE FICHIER :
    intersections_{code_insee}.geojson  (ex: intersections_94052.geojson)
    Le code INSEE est unique par commune, ce qui évite de mélanger deux villes
    du même département (ex: Vincennes et Nogent-sur-Marne, toutes deux en 94).
    """

    os.makedirs(DOSSIER_SORTIE, exist_ok=True)
    # crée le dossier "intersections/" s'il n'existe pas encore
    # exist_ok=True évite une erreur si le dossier existe déjà

    nom_fichier = f"intersections_{code_insee}.geojson"
    # code INSEE unique par commune → pas de collision entre villes du même département

    chemin = os.path.join(DOSSIER_SORTIE, nom_fichier)
    # chemin complet : "intersections/intersections_94.geojson"

    geojson_sortie = {
        "type": "FeatureCollection",
        "features": features
        # on reconstruit un GeoJSON valide avec uniquement les intersections filtrées
        # même format que le fichier source, compatible avec tous les outils GIS
    }

    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(geojson_sortie, f, ensure_ascii=False, indent=2)
        # ensure_ascii=False : préserve les accents (é, è, à...) en clair
        # indent=2 : indentation pour que le fichier soit lisible dans un éditeur

    print(f"  Sauvegardé : {chemin} ({len(features)} intersections)")
    return chemin
    # on retourne le chemin pour que la fonction appelante puisse l'afficher


# ETAPE 5 — Orchestrer toutes les étapes ---------------------------------------------------------


def telecharger_intersections_ville(nom_ville, departements_preresolus=None):
    """
    Fonction principale qui orchestre tout le pipeline de téléchargement :
    1. Trouve le département et le code INSEE de la ville
    2. Demande à l'utilisateur de choisir si plusieurs départements correspondent
    3. Télécharge le fichier GeoJSON du département (OSM + fallback data.gouv.fr)
    4. Filtre les intersections de la ville
    5. Sauvegarde le résultat

    Si le filtrage ne trouve aucune intersection pour la ville (par exemple
    si les champs du GeoJSON ne correspondent pas à ce qu'on attend), la fonction
    affiche un exemple de propriétés pour aider au diagnostic, et propose de
    sauvegarder toutes les intersections du département à la place.

    departements_preresolus : liste de tuples (code_dept, nom_commune, code_insee) déjà
    résolus et choisis par l'utilisateur — permet d'éviter une double question de choix.
    """

    if departements_preresolus is not None:
        departements = departements_preresolus
    else:
        print(f"\nRecherche de '{nom_ville}' dans l'API géographique...")
        departements = trouver_departements(nom_ville)
        # récupère la liste des (code_dept, nom_commune, code_insee) correspondant à la ville

        if not departements:
            return []
            # si aucune commune trouvée, on arrête là (trouver_departements() a déjà affiché le message)

        if len(departements) > 1:
            # plusieurs départements ont une commune de ce nom → on demande à l'utilisateur de choisir
            print(f"\nPlusieurs départements trouvés pour '{nom_ville}' :")
            for i, (dept, commune, _) in enumerate(departements):
                print(f"  [{i}] {commune} (département {dept})")
                # on affiche chaque option avec son numéro, son nom officiel et son département

            choix = input("Entrez le numéro de votre choix : ").strip()
            try:
                departements = [departements[int(choix)]]
                # on ne garde que le département choisi par l'utilisateur
            except (ValueError, IndexError):
                print("Choix invalide.")
                return []
                # si l'utilisateur a tapé quelque chose qui n'est pas un numéro valide

    fichiers_crees = []
    # liste des chemins des fichiers créés, pour l'affichage final

    for code_dept, nom_commune, code_insee in departements:
        print(f"\nTraitement du département {code_dept} ({nom_commune}, INSEE: {code_insee})...")
        # on affiche le code INSEE pour que l'utilisateur puisse vérifier que c'est le bon

        # VÉRIFICATION DOUBLON : si le fichier existe déjà, inutile de retélécharger
        nom_fichier_attendu = f"intersections_{code_insee}.geojson"
        chemin_existant = os.path.join(DOSSIER_SORTIE, nom_fichier_attendu)
        if os.path.exists(chemin_existant):
            print(f"  Fichier déjà présent : {chemin_existant}")
            print(f"  Téléchargement ignoré (supprimez le fichier pour forcer le re-téléchargement).")
            fichiers_crees.append(chemin_existant)
            continue
            # on ajoute quand même le fichier existant à la liste pour l'affichage final

        geojson = telecharger_intersections_dept(code_dept)
        # télécharge et décompresse le fichier GeoJSON du département (OSM + fallback)

        if geojson is None:
            print(f"  Toutes les sources ont échoué pour le département {code_dept}.")
            continue
            # si même le fallback data.gouv.fr a échoué, on passe au département suivant

        total = len(geojson.get("features", []))
        print(f"  {total} intersections dans le département.")
        # information utile : si le filtrage donne 0 résultat sur 20 000 intersections,
        # le problème vient du filtrage, pas du téléchargement

        features = filtrer_par_ville(geojson, nom_ville, code_insee)
        # filtre les intersections pour ne garder que celles de la ville demandée

        if not features:
            # aucune intersection trouvée malgré le téléchargement réussi
            print(f"  Aucune intersection trouvée pour '{nom_ville}'.")
            afficher_exemple_proprietes(geojson)
            # on affiche les propriétés brutes pour aider à comprendre le problème

            reponse = input("  Sauvegarder toutes les intersections du département ? (o/n) : ").strip().lower()
            if reponse == "o":
                features = geojson.get("features", [])
                # on sauvegarde tout le département si l'utilisateur le souhaite
            else:
                continue
                # sinon on passe au département suivant sans créer de fichier

        chemin = sauvegarder(features, code_insee)
        fichiers_crees.append(chemin)

    if fichiers_crees:
        print(f"\nTerminé. Fichiers créés dans le dossier '{DOSSIER_SORTIE}/' :")
        for f in fichiers_crees:
            print(f"  - {f}")
    else:
        print("\nAucun fichier créé.")

    return fichiers_crees
    # on retourne la liste des chemins pour que main.py puisse les utiliser directement


# ETAPE 6a — Normalisation des noms d'intersections ----------------------------------------------


def normaliser_nom_intersection(nom):
    """
    Normalise un nom d'intersection pour le rendre lisible et cohérent :
    espaces autour du séparateur "/", suppression des espaces multiples.

    POURQUOI CETTE FONCTION EXISTE :
    Les noms dans le GeoJSON peuvent contenir des irrégularités d'espacement
    (ex: "Rue X/Rue Y" sans espace autour du "/", ou "Rue  X" avec double espace).
    Cette fonction uniformise le format pour faciliter la lecture.
    """

    if not nom:
        return nom

    nom = nom.strip()
    # supprime les espaces en début et fin de chaîne

    nom = nom.replace("/", " / ")
    # ajoute un espace de chaque côté du séparateur d'intersection

    while "  " in nom:
        nom = nom.replace("  ", " ")
    # supprime les espaces doubles créés par la substitution précédente

    return nom


# ETAPE 6b — Choix interactif des types de voies -------------------------------------------------


def choisir_types_voies():
    """
    Affiche un menu interactif pour que l'utilisateur choisisse
    les types de voies à conserver dans le DataFrame final.

    L'utilisateur saisit les numéros des types souhaités séparés par des virgules.
    S'il appuie sur Entrée sans rien saisir, tous les types sont conservés.

    EXEMPLES DE SAISIE :
        "1,2,5"    → Avenue, Boulevard, Rue
        "1"        → Avenue uniquement
        ""         → tous les types (pas de filtre)
    """

    print("\nTypes de voies disponibles :")
    for i, type_voie in enumerate(TYPES_VOIES):
        print(f"  [{i + 1}] {type_voie}")
        # on affiche chaque type avec son numéro pour que l'utilisateur puisse le choisir

    print("\nEntrez les numéros des types à garder séparés par des virgules.")
    saisie = input("(Appuyez sur Entrée sans rien écrire pour tout garder) : ").strip()
    # .strip() supprime les espaces accidentels en début et fin

    if not saisie:
        print("  Tous les types de voies seront conservés.")
        return []
        # liste vide = pas de filtre, on garde tout

    types_choisis = []
    for partie in saisie.split(","):
        # on découpe la saisie par virgule pour récupérer chaque numéro
        try:
            index = int(partie.strip()) - 1
            # -1 car l'affichage commence à 1 mais les indices Python commencent à 0
            if 0 <= index < len(TYPES_VOIES):
                types_choisis.append(TYPES_VOIES[index])
                # on ajoute le type correspondant à la liste des choix
        except ValueError:
            pass
            # si l'utilisateur a tapé un caractère non numérique, on l'ignore

    if not types_choisis:
        print("  Aucun choix valide reconnu. Tous les types seront conservés.")
        return []
        # si aucun numéro valide n'a été saisi, on ne filtre pas

    print(f"  Types retenus : {', '.join(types_choisis)}")
    return types_choisis


# ETAPE 6c — Lire le fichier GeoJSON local et le convertir en DataFrame --------------------------


def charger_en_dataframe(chemin_geojson: str) -> pd.DataFrame:
    """
    Lit le fichier GeoJSON local (sauvegardé par telecharger_intersections_ville())
    et le convertit en DataFrame compatible avec le pipeline de main.py.

    ÉTAPES APPLIQUÉES :
    1. Lecture du fichier GeoJSON local
    2. Conversion en DataFrame avec colonnes latitude | longitude | intersection | Ville/Commune
    3. Suppression des doublons géographiques
    4. Normalisation des noms d'intersections
    5. Filtrage interactif par type de voie (l'utilisateur choisit)

    COLONNES PRODUITES : latitude | longitude | intersection | Ville/Commune
    Ces colonnes sont identiques à celles produites par nettoyage.charger_intersections()
    pour assurer la compatibilité avec proximite.py et le reste du pipeline.
    """

    with open(chemin_geojson, encoding="utf-8") as f:
        geojson = json.load(f)
        # on ouvre et décode le fichier GeoJSON local en dictionnaire Python

    lignes = []
    # liste vide qui va accumuler une intersection par ligne

    for feat in geojson.get("features", []):
        # on parcourt chaque intersection du fichier GeoJSON
        props = feat.get("properties", {})
        # propriétés de l'intersection : name, context, citycode, depcode
        coords = feat.get("geometry", {}).get("coordinates", [])
        # coordonnées GPS : [longitude, latitude] (ordre GeoJSON standard)
        if len(coords) < 2:
            continue
            # si les coordonnées sont incomplètes on saute cette intersection

        lignes.append({
            "longitude":     float(coords[0]),
            # coords[0] = longitude (premier élément en GeoJSON)
            "latitude":      float(coords[1]),
            # coords[1] = latitude (deuxième élément en GeoJSON)
            "intersection":  props.get("name", ""),
            # "name" contient le nom des deux rues qui se croisent (ex: "Rue X / Rue Y")
            "Ville/Commune": props.get("context", ""),
            # "context" contient la ville et le département (ex: "Fontenay-sous-Bois, Val-de-Marne")
        })

    df = pd.DataFrame(lignes)
    # convertit la liste de dictionnaires en DataFrame pandas

    if df.empty:
        print(f"  Aucune intersection chargée depuis {chemin_geojson}.")
        return df

    # ÉTAPE : suppression des doublons géographiques
    df = df.drop_duplicates(subset=["longitude", "latitude"]).reset_index(drop=True)
    # supprime les lignes avec exactement les mêmes coordonnées GPS

    # ÉTAPE : normalisation des noms d'intersections
    df["intersection"] = df["intersection"].apply(normaliser_nom_intersection)
    # applique la normalisation sur chaque nom d'intersection du DataFrame

    print(f"  {len(df)} intersections chargées depuis {chemin_geojson}.")

    # ÉTAPE : filtrage interactif par type de voie
    types_voies = choisir_types_voies()
    # demande à l'utilisateur quels types de voies il veut garder

    if types_voies:
        pattern = "|".join(types_voies)
        # construit une expression de recherche : "Avenue|Boulevard|Route"
        df = df[df["intersection"].str.contains(pattern, case=False, na=False)]
        # filtre les lignes dont le nom d'intersection contient au moins un des types choisis
        # case=False : insensible à la casse (Avenue = avenue)
        # na=False : les valeurs manquantes ne passent pas le filtre
        df = df.reset_index(drop=True)
        # remet les index à zéro après le filtrage
        print(f"  {len(df)} intersections après filtrage par type de voie.")

    return df


# TESTS --------------------------------------------------------------------------------------------
if __name__ == "__main__":

    ville = input("Entrez le nom de la ville : ").strip()
    # .strip() supprime les espaces accidentels en début et fin de saisie

    if ville:
        fichiers = telecharger_intersections_ville(ville)
        if fichiers:
            df = charger_en_dataframe(fichiers[0])
            print(f"\nAperçu du DataFrame :")
            print(df.head())
    else:
        print("Nom de ville vide.")
