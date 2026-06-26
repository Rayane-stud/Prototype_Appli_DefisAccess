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
    2. Téléchargement du fichier intersections-{dept}.geojson.gz depuis osm13.openstreetmap.fr
        ↓
    3. Filtrage des intersections par code INSEE (citycode) en priorité,
       sinon par nom de ville normalisé (tirets = espaces, minuscules)
        ↓
    4. Sauvegarde dans intersections/{ville}_{dept}.geojson

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
              depuis le serveur OpenStreetMap
    # ARGUMENTS : "code_dept" de type str (ex: "94", "2A", "971")
    # REPONSE : dict (GeoJSON complet) ou None si fichier introuvable

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
    # ARGUMENTS : "features" list, "nom_ville" str, "code_dept" str
    # REPONSE : str (chemin du fichier créé)

- telecharger_intersections_ville() :
    # ROLE : Fonction principale qui orchestre toutes les étapes
              (recherche département → téléchargement → filtrage → sauvegarde)
    # ARGUMENTS : "nom_ville" de type str
    # REPONSE : None (affichage console + fichier créé)
"""

import requests
import gzip
import json
import os

# URL du fichier GeoJSON compressé par département sur le serveur OpenStreetMap
# {dept} sera remplacé par le numéro de département (ex: 94, 75, 2A, 971...)
# Tous les fichiers sont au format .geojson.gz (GeoJSON compressé avec gzip)
BASE_URL = "https://osm13.openstreetmap.fr/~cquest/osm_poi/intersections-geojson/intersections-{dept}.geojson.gz"

# URL de l'API officielle geo.api.gouv.fr (INSEE/IGN)
# Même API que dans identification_PM.py : 100% officielle, toutes les communes
# françaises y sont référencées, et elle est conçue pour être interrogée automatiquement
GEO_API_URL = "https://geo.api.gouv.fr/communes"

# Dossier local où seront sauvegardés les fichiers GeoJSON téléchargés
# Il sera créé automatiquement s'il n'existe pas (voir sauvegarder())
DOSSIER_SORTIE = "intersections"


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


# ETAPE 2 — Télécharger le fichier GeoJSON d'un département ---------------------------------------


def telecharger_intersections_dept(code_dept):
    """
    Télécharge depuis le serveur OpenStreetMap le fichier GeoJSON compressé
    contenant toutes les intersections d'un département, puis le décompresse.

    POURQUOI LES FICHIERS SONT PAR DÉPARTEMENT :
    Le dataset couvre la France entière (plus de 2 millions d'intersections).
    Un seul fichier national serait trop volumineux à télécharger.
    Christian Quest a découpé les données par département pour permettre
    de ne télécharger que la zone qui nous intéresse.

    FORMAT DES FICHIERS :
    Les fichiers sont au format GeoJSON compressé avec gzip (.geojson.gz).
    On les décompresse en mémoire avec le module gzip de Python, sans
    écrire de fichier temporaire sur le disque.
    """

    url = BASE_URL.format(dept=code_dept)
    # on construit l'URL complète en remplaçant {dept} par le numéro réel
    # ex: "https://osm13.openstreetmap.fr/.../intersections-94.geojson.gz"

    print(f"  Téléchargement depuis : {url}")
    reponse = requests.get(url, stream=True, timeout=60)
    # stream=True : télécharge le fichier par morceaux pour économiser la RAM
    # timeout=60  : abandonne si pas de réponse en 60 secondes
    #               (les fichiers peuvent peser jusqu'à ~1.7 Mo compressés)

    if reponse.status_code == 404:
        print(f"  Fichier introuvable pour le département {code_dept}.")
        return None
        # 404 = ce département n'existe pas dans le dataset
        # (cas possible pour certains territoires ultramarins non couverts)

    reponse.raise_for_status()
    # vérifie que le téléchargement s'est bien passé (autre que 200 ou 404 = erreur)

    contenu_gz = reponse.content
    # récupère l'intégralité du fichier téléchargé sous forme d'octets (bytes)

    contenu_json = gzip.decompress(contenu_gz)
    # décompresse le fichier gzip en mémoire → on obtient du texte JSON brut

    return json.loads(contenu_json)
    # convertit le texte JSON en dictionnaire Python (format GeoJSON)
    # structure : {"type": "FeatureCollection", "features": [...]}


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


def sauvegarder(features, code_dept):
    """
    Écrit les intersections filtrées dans un fichier GeoJSON dans le dossier
    "intersections/" du projet.

    FORMAT DU NOM DE FICHIER :
    intersections_{code_dept}.geojson  (ex: intersections_94.geojson)
    """

    os.makedirs(DOSSIER_SORTIE, exist_ok=True)
    # crée le dossier "intersections/" s'il n'existe pas encore
    # exist_ok=True évite une erreur si le dossier existe déjà

    nom_fichier = f"intersections_{code_dept}.geojson"
    # construction du nom de fichier : format standard avec le numéro de département
    # ex: département 94 → "intersections_94.geojson"

    chemin = os.path.join(DOSSIER_SORTIE, nom_fichier)
    # chemin complet : "intersections/fontenay_sous_bois_94.geojson"

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


def telecharger_intersections_ville(nom_ville):
    """
    Fonction principale qui orchestre tout le pipeline de téléchargement :
    1. Trouve le département et le code INSEE de la ville
    2. Demande à l'utilisateur de choisir si plusieurs départements correspondent
    3. Télécharge le fichier GeoJSON du département
    4. Filtre les intersections de la ville
    5. Sauvegarde le résultat

    Si le filtrage ne trouve aucune intersection pour la ville (par exemple
    si les champs du GeoJSON ne correspondent pas à ce qu'on attend), la fonction
    affiche un exemple de propriétés pour aider au diagnostic, et propose de
    sauvegarder toutes les intersections du département à la place.
    """

    print(f"\nRecherche de '{nom_ville}' dans l'API géographique...")
    departements = trouver_departements(nom_ville)
    # récupère la liste des (code_dept, nom_commune, code_insee) correspondant à la ville

    if not departements:
        return
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
            return
            # si l'utilisateur a tapé quelque chose qui n'est pas un numéro valide

    fichiers_crees = []
    # liste des chemins des fichiers créés, pour l'affichage final

    for code_dept, nom_commune, code_insee in departements:
        print(f"\nTraitement du département {code_dept} ({nom_commune}, INSEE: {code_insee})...")
        # on affiche le code INSEE pour que l'utilisateur puisse vérifier que c'est le bon

        # VÉRIFICATION DOUBLON : si le fichier existe déjà, inutile de retélécharger
        nom_fichier_attendu = f"intersections_{code_dept}.geojson"
        chemin_existant = os.path.join(DOSSIER_SORTIE, nom_fichier_attendu)
        if os.path.exists(chemin_existant):
            print(f"  Fichier déjà présent : {chemin_existant}")
            print(f"  Téléchargement ignoré (supprimez le fichier pour forcer le re-téléchargement).")
            fichiers_crees.append(chemin_existant)
            continue
            # on ajoute quand même le fichier existant à la liste pour l'affichage final

        geojson = telecharger_intersections_dept(code_dept)
        # télécharge et décompresse le fichier GeoJSON du département

        if geojson is None:
            continue
            # si le fichier n'existe pas pour ce département, on passe au suivant

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

        chemin = sauvegarder(features, code_dept)
        fichiers_crees.append(chemin)

    if fichiers_crees:
        print(f"\nTerminé. Fichiers créés dans le dossier '{DOSSIER_SORTIE}/' :")
        for f in fichiers_crees:
            print(f"  - {f}")
    else:
        print("\nAucun fichier créé.")


# TESTS --------------------------------------------------------------------------------------------
if __name__ == "__main__":

    ville = input("Entrez le nom de la ville : ").strip()
    # .strip() supprime les espaces accidentels en début et fin de saisie

    if ville:
        telecharger_intersections_ville(ville)
    else:
        print("Nom de ville vide.")
