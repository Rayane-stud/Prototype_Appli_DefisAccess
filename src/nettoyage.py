import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Sources en ligne pour les intersections
# ---------------------------------------------------------------------------

_OSM_BASE = "https://osm13.openstreetmap.fr/~cquest/osm_poi/intersections-geojson"
_DATAGOUV_API = "https://www.data.gouv.fr/api/1/datasets/intersections-des-rues-et-routes-de-france/"


def _get_dep_code(ville: str) -> str:
    """
    Retourne le code département (ex: '92') pour une ville via geo.api.gouv.fr.
    Retourne None si la ville est introuvable.
    """
    try:
        resp = requests.get(
            "https://geo.api.gouv.fr/communes",
            params={"nom": ville, "fields": "codeDepartement", "limit": 5},
            timeout=10,
        )
        resp.raise_for_status()
        communes = resp.json()
        if not communes:
            return None
        # Préférer la correspondance exacte sur le nom
        ville_low = ville.lower()
        for c in communes:
            if c.get("nom", "").lower() == ville_low:
                return c.get("codeDepartement")
        # Sinon, prendre le premier résultat
        return communes[0].get("codeDepartement")
    except Exception as e:
        print(f"  [geo.api.gouv.fr] Erreur : {e}")
        return None


def _telecharger_geojson_osm(dep_code: str) -> dict:
    """
    Tente de télécharger le GeoJSON du département depuis le serveur OSM.
    Retourne le dict GeoJSON ou None en cas d'échec.
    """
    # Le serveur utilise le code à 2 chiffres : "92", "01", "2A"…
    dep = dep_code.zfill(2)
    url = f"{_OSM_BASE}/{dep}.geojson"
    try:
        print(f"  [OSM] {url}")
        resp = requests.get(url, timeout=120)
        if resp.status_code == 404:
            print(f"  [OSM] Fichier introuvable (404) pour le département {dep}")
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [OSM] Échec : {e}")
        return None


def _telecharger_geojson_datagouv(dep_code: str) -> dict:
    """
    Fallback : cherche la ressource du département dans le dataset data.gouv.fr
    et la télécharge. Retourne le dict GeoJSON ou None.
    """
    dep = dep_code.zfill(2)
    try:
        # 1. Récupérer la liste des ressources du dataset
        resp = requests.get(_DATAGOUV_API, timeout=15)
        resp.raise_for_status()
        dataset = resp.json()

        # 2. Chercher la ressource dont le titre contient le code département
        for resource in dataset.get("resources", []):
            titre = resource.get("title", "").lower()
            # Patterns courants : "92", "dep92", "dep-92", "intersections-92"
            if (
                f"-{dep}" in titre
                or f"_{dep}" in titre
                or titre.endswith(dep)
                or f"dep{dep}" in titre
            ):
                url = resource.get("url", "")
                if not url:
                    continue
                print(f"  [data.gouv.fr] {url}")
                r2 = requests.get(url, timeout=180)
                r2.raise_for_status()
                return r2.json()

        print(f"  [data.gouv.fr] Aucune ressource trouvée pour le département {dep}")
        return None

    except Exception as e:
        print(f"  [data.gouv.fr] Échec : {e}")
        return None


def _geojson_vers_dataframe(geojson: dict, ville: str) -> pd.DataFrame:
    """
    Convertit un GeoJSON FeatureCollection d'intersections en DataFrame,
    filtré sur la ville demandée.

    Colonnes retournées : latitude, longitude, intersection, Ville/Commune
    (compatible avec le reste du pipeline).
    """
    features = geojson.get("features", [])
    ville_low = ville.lower()
    lignes = []

    for feat in features:
        props = feat.get("properties", {})
        context = props.get("context", "")
        nom = props.get("name", "")

        # Le champ context contient le nom de la ville, ex: "Garches, Hauts-de-Seine"
        if ville_low not in context.lower():
            continue

        coords = feat.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            continue

        lignes.append({
            "longitude": float(coords[0]),
            "latitude": float(coords[1]),
            "intersection": nom,
            "Ville/Commune": context,
        })

    if not lignes:
        raise ValueError(
            f"Aucune intersection trouvée pour '{ville}' dans le GeoJSON téléchargé.\n"
            f"Vérifiez l'orthographe du nom de ville (doit correspondre au champ 'context')."
        )

    df = pd.DataFrame(lignes)
    df = df.drop_duplicates(subset=["longitude", "latitude"]).reset_index(drop=True)
    return df






"""fonction qui telcharge les intersections d'une ville depuis internet et retourne un DataFrame"""




def telecharger_intersections(ville: str) -> pd.DataFrame:
    """
    Télécharge les intersections d'une ville depuis internet et retourne un DataFrame.

    Sources essayées dans l'ordre :
      1. https://osm13.openstreetmap.fr/~cquest/osm_poi/intersections-geojson/{dep}.geojson
      2. https://www.data.gouv.fr/datasets/intersections-des-rues-et-routes-de-france

    Args:
        ville : Nom de la ville (ex: "Garches", "Levallois-Perret").

    Returns:
        DataFrame avec colonnes latitude, longitude, intersection, Ville/Commune.

    Raises:
        ValueError  : Ville introuvable ou aucune intersection dans le fichier.
        RuntimeError: Aucune source n'a pu être téléchargée.
    """
    print(f"Recherche du département pour '{ville}'...")
    dep_code = _get_dep_code(ville)
    if dep_code is None:
        raise ValueError(
            f"Ville '{ville}' introuvable via geo.api.gouv.fr.\n"
            f"Vérifiez l'orthographe (ex: 'Levallois-Perret', 'Boulogne-Billancourt')."
        )
    print(f"  → Département : {dep_code}")

    # Tentative 1 : serveur OSM
    geojson = _telecharger_geojson_osm(dep_code)

    # Tentative 2 : data.gouv.fr en fallback
    if geojson is None:
        print("  → Tentative sur data.gouv.fr...")
        geojson = _telecharger_geojson_datagouv(dep_code)

    if geojson is None:
        dep = dep_code.zfill(2)
        raise RuntimeError(
            f"Impossible de télécharger les intersections pour le département {dep_code}.\n"
            f"Sources essayées :\n"
            f"  - {_OSM_BASE}/{dep}.geojson\n"
            f"  - {_DATAGOUV_API} (ressource département {dep})"
        )

    print(f"  → GeoJSON téléchargé ({len(geojson.get('features', []))} features), filtrage sur '{ville}'...")
    return _geojson_vers_dataframe(geojson, ville)


# ---------------------------------------------------------------------------

def charger_intersections(path, ville):
    # charger le fichier CSV
    df = pd.read_csv(path).copy()
    #on recupere les lignes correspondantes à la ville saisie
    colonne= "properties/context"
    df_ville= df[df[colonne].str.contains(ville, case=False)]
    print(df.head())
    print("Nouveau")
    print(df_ville.head())
    #on remet au propre le tableau avec des colonnes disctinctes
    tableauFinal = df_ville.rename(columns={
        "geometry/coordinates/0": "longitude",
        "geometry/coordinates/1": "latitude",
        "properties/name": "intersection",
        "properties/context": "Ville/Commune",
        "properties/citycode": "Code Postale",
        "properties/depcode": "Code Département"
    })
    
    print(tableauFinal["Ville/Commune"].head())
    #on distinct les colonnes Ville et Département à partir de la colonne Ville/Commune
    tableauFinal = tableauFinal.drop(columns=["type", "geometry/type", "Code Postale", "Code Département"])
    tableauFinal = tableauFinal.reset_index(drop=True)
    
    
    #on corrige les fautes dù au texte encodé
    tableauFinal = correction_intersections(tableauFinal)
    tableauFinal = normailisation_intersections(tableauFinal)
    tableauFinal = doublons_intersections(tableauFinal)
    tableauFinal = filtrer_intersections(tableauFinal)

    return tableauFinal
    
 
def correction_intersections(tableauFinal):
    # Correction du texte encodé
    correction = tableauFinal.copy()
    correction["intersection"]= (correction["intersection"].str.replace('Ã©', 'é').
            str.replace('Ã¨', 'è').
            str.replace('Ã¢', 'â').
            str.replace('Ãª', 'ê').
            str.replace('Ã®', 'î').
            str.replace('Ã´', 'ô').
            str.replace('Ã»', 'û').
            str.replace('Ã§', 'ç').
            str.replace('Ã‰', 'É').
            str.replace('Ã€', 'À').
            str.replace('Ã‰', 'É').
            str.replace('Ãˆ', 'È').
            str.replace('ÃŒ', 'Ì').
            str.replace('Ã’', 'Ò').
            str.replace('Ã”', 'Ô').
            str.replace('Ã•', 'Õ').
            str.replace('Ãœ', 'Ü'))
    return correction

def normailisation_intersections(tableauFinal):
    # Normaliser les noms de colonnes
    col="intersection"
    df=tableauFinal.copy()
    
    remplacer = [
        # Déterminants
        ("de", "de "),
        ("de s", "des "),
        ("du", " du "),
        ("la", "la "),
        ("D", " D"),

        # Types de voies
        ("Rue", "Rue "),
        ("/", " / "),
        ("Avenue", "Avenue "),
        ("Boulevard", "Boulevard "),
        ("Rond-Point", "Rond-Point "),
        ("Allée", "Allée "),
        ("Passage", "Passage "),
        ("Voie", "Voie "),
        ("Réside nce", "Résidence "),
        ("Pla ce", "Place "),
        ("Square", "Square "),

        # Prénoms
        ("Victor", "Victor "),
        ("Amaury", "Amaury "),
        ("Abbé", "Abbé "),
        ("Jean", "Jean "),
        ("Benoît", "Benoît "),
        ("Gabriel", "Gabriel "),
        ("Albert", "Albert "),
        ("Maurice", "Maurice "),
        ("Charles", "Charles "),
        ("Georges", "Georges "),
        ("Baptiste", "Baptiste "),
        ("Henri", "Henri "),
        ("Léon", "Léon "),
        ("Louis", "Louis "),
        ("Léo", "Léo "),
        ("Romain", "Romain "),
        ("Pierre", "Pierre "),
        ("Paul", "Paul "),
        ("Jules", "Jules "),
        ("Alphonse", "Alphonse "),
        ("René", "René "),
        ("Aristi de", "Aristide "),
        ("Rolla nd", "Rolland"),
        ("Made leine", "Madeleine"),
        ("Ambroise", "Ambroise "),
        ("François", "François "),
        ("Gustave", "Gustave "),
        ("Hippolyte", "Hippolyte "),
        ("Marc", "Marc "),
        ("Marc el", "Marcel "),
        ("Rene", "Rene "),
        ("Laurent", "Laurent "),
        ("Abraham", "Abraham "),
        ("Salvador", "Salvador "),
        ("Etienne", "Etienne "),
        ("Clément", "Clément "),
        ("Félix", "Félix "),
        ("Estienne", "Estienne "),
        ("Esther", "Esther "),
        ("Léo n-Maurice", "Léon-Maurice "),
        ("Léo n ce", "Léonce "),
        ("Cla ude", "Claude "),
        ("Athime", "Athime "),
        ("Raymond", "Raymond "),
        ("André", "André "),
        ("Guilla ume", "Guillaume "),

        # Noms propres
        ("Holla nde", "Hollande"),
        ("Rabela is", "Rabelais"),
        ("Harde nberg", "Hardenberg "),
        ("Bla nchard", "Blanchard "),
        ("Garla nde", "Garlande "),
        ("Bas", "Bas "),
        ("Bla ins", "Blains "),
        ("Haj du", "Hajdu "),
        ("ÉtienneHajdu", "Étienne Hajdu "),
        ("ErnestRenan", "Ernest Renan "),
        ("Dumontd'Urville", "Dumont d'Urville "),
        ("AugusteBuisson", "Auguste Buisson "),
        ("SouvenirFrançais", "Souvenir Français "),
        ("ÉtienneMarcel", "Étienne Marcel "),

        # Noms communs
        ("Vailla nt", "Vaillant"),
        ("11", "11 "),
        ("Treize", "Treize "),
        ("Ormes", "Ormes "),
        ("Pla nes", "Planes "),
        ("Marin", "Marin "),
        ("Droits", "Droits "),
        ("Pont", "Pont "),
        ("Clos", "Clos "),
        ("Tram", "Tram "),
        ("Pla te", "Plate "),
        ("Maréchal", "Maréchal "),
        ("Docteur", "Docteur "),
        ("Colonel", "Colonel "),
        ("Général", "Général "),
        ("Division", "Division "),
        ("Parking", "Parking "),
        ("Espla nade", "Esplanade "),
        ("Pla isance", "Plaisance "),
        ("Pla ine", "Plaine "),
        ("Marquis", "Marquis "),
        ("Porte", "Porte "),
        ("Côte", "Côte "),
        ("Cours", "Cours "),

        # Arbres
        ("Bouleaux", "Bouleaux "),
        ("Érables", "Érables "),
        ("Erables", "Érables "),
        ("Féviers", "Féviers "),
        ("Frênes", "Frênes "),
        ("Marronniers", "Marronniers "),
        ("Noisetiers", "Noisetiers "),
        ("Prunier", "Prunier "),
        ("Ver du n", "Verdun"),
        ("Martyrs", "Martyrs "),
        ("Noyers", "Noyers "),
        ("Tulipiers", "Tulipiers "),
        ("Tilleuls", "Tilleuls "),
        ("Marcel in", "Marcelin "),
        ("Lilas", "Lilas "),
        ("Sente", "Sente "),
        ("Hautes", "Hautes "),
        ("Professeur", "Professeur "),
        ("Jardin", "Jardin "),

        # Spécificités locales
        ("Bourg-la -Reine", "Bourg-la-Reine"),
        ("LaCouléeVerte", "La Coulée Verte"),
        ("19Janvier", "19 janvier"),

        (" -", "-")
    ]

    for ancien, nouveau in remplacer:
        df[col] = df[col].str.replace(ancien,nouveau,regex=False)

    return df

def doublons_intersections(tableauFinal):
    # convertir en numérique
    doublons = tableauFinal.copy()
    doublons["longitude"] = pd.to_numeric(doublons["longitude"])
    doublons["latitude"] = pd.to_numeric(doublons["latitude"])

    # supprimer doublons géographiques
    doublons= doublons.drop_duplicates(subset=["longitude", "latitude"],keep="first")

    return doublons

def filtrer_intersections(tableauFinal):
    # Filtrer les intersections en fonction du type de voie
    typevoie = "Avenue|Esplanade|Boulevard"  # Ajouter d'autres types de voies si nécessaire
    df= tableauFinal[tableauFinal["intersection"].str.contains(typevoie, case=False)]

    return df
