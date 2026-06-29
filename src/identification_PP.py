"""
Ce fichier va nous permettre d'identifier le nombre de passage piéton par intersections 
en utilisant open street map ainsi que les bases de données récupéré sur les intersection en île de France.
il va donc parcourir ligne par ligne les fichier csv une fois qu'ils ont été nettoyé pour associer à chaque intersections
les passages piétons associés.
"""

import math
from pandas import DataFrame
import requests
import pandas as pd 
import numpy as np
import csv

from geopy.distance import geodesic 
from scipy.spatial import cKDTree     

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

DOSSIER_OUTPUT = "data/output"


"""
------------------------------------------------------------------------------------------
METHODE OSM:
"""

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


#faire la fusion des intersections proches


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
            
            valeur = intersections_brutes[index]["nb_passages_pietons"]
            intersections_brutes[index]["latitude_pp"+str(valeur)]=passage["lat"]
            intersections_brutes[index]["longitude_pp"+str(valeur)]=passage["lon"]


    return pd.DataFrame(intersections_brutes)
#_____________________________ test répartition___________________________________
def analyser_repartition_passages(nom_commune: str) -> None:
    """
    Charge le CSV d'une commune et affiche la répartition
    du nombre de passages piétons par intersection.
    """
    import os

    nom_fichier = f"{DOSSIER_OUTPUT}/intersections_{nom_commune.lower()}_passages.csv"

    # --- Vérification que le fichier existe ---
    if not os.path.exists(nom_fichier):
        print(f" Aucun fichier trouvé pour '{nom_commune}'. Lancez d'abord le pipeline.")
        return

    df = pd.read_csv(nom_fichier, encoding="utf-8-sig")

    if df.empty:
        print(" Le fichier est vide.")
        return

    total_intersections = len(df)
    total_passages      = df["nb_passages_pietons"].sum()

    # --- Répartition : combien d'intersections ont 0, 1, 2, 3... passages ---
    repartition = df["nb_passages_pietons"].value_counts().sort_index()

    print(f"\n=== Répartition des passages piétons — {nom_commune} ===\n")
    print(f"  Total intersections      : {total_intersections}")
    print(f"  Total passages piétons   : {int(total_passages)}")
    print(f"  Moyenne par intersection : {total_passages / total_intersections:.2f}\n")

    print(f"  {'Nb passages':<15} {'Nb intersections':<20} {'%'}")
    print(f"  {'-'*45}")

    for nb_passages, nb_intersections in repartition.items():
        pourcentage = nb_intersections / total_intersections * 100
        barre = "█" * int(pourcentage / 2)
        # barre visuelle proportionnelle au pourcentage
        print(f"  {nb_passages:<15} {nb_intersections:<20} {pourcentage:5.1f}%  {barre}")

#__________________________test de repartition sur le fichier xsls________________________

def analyser_repartition_xlsx(chemin_fichier: str) -> pd.DataFrame:
    """
    Charge le fichier Excel et affiche la répartition
    du nombre de traversées par intersection.
    """
    import os

    if not os.path.exists(chemin_fichier):
        print(f" Fichier introuvable : {chemin_fichier}")
        return pd.DataFrame()

    df = pd.read_excel(chemin_fichier)
    print(f" {len(df)} lignes chargées")

    # --- Regroupement par intersection (colonne "intersection") ---
    repartition_par_intersection = df.groupby("intersection")["traversee"].count().reset_index()
    repartition_par_intersection.columns = ["intersection", "nb_traversees"]
    repartition_par_intersection = repartition_par_intersection.sort_values("nb_traversees", ascending=False)

    # --- Affichage ---
    total_intersections = len(repartition_par_intersection)
    total_traversees    = repartition_par_intersection["nb_traversees"].sum()

    print(f"\n=== Répartition des traversées par intersection ===\n")
    print(f"  Total intersections      : {total_intersections}")
    print(f"  Total traversées         : {total_traversees}")
    print(f"  Moyenne par intersection : {total_traversees / total_intersections:.1f}\n")

    repartition = repartition_par_intersection["nb_traversees"].value_counts().sort_index()
    print(f"  {'Nb traversées':<16} {'Nb intersections':<20} {'%'}")
    print(f"  {'-'*50}")
    for nb, count in repartition.items():
        pct = count / total_intersections * 100
        barre = "█" * int(pct / 2)
        print(f"  {nb:<16} {count:<20} {pct:5.1f}%  {barre}")

    return repartition_par_intersection


"""
------------------------------------------------------------------------------------------
METHODE PP_ACCIDENTS:
"""

def charger_accidents(path, ville):
    # charger le fichier CSV
    df = pd.read_csv(path, sep=";").copy()

    #on trie celon le nom de la ville
    col="commune"
    df_ville = df[df[col].str.contains(ville, case=False, na=False)]
    df_ville = df_ville.reset_index(drop=True)

    #on garde les colonnes souhaitées
    garde=["geo_point_2d","commune","adresse"
           ,"usager1","loc_usa1"
           ,"usager2","loc_usa2"
           ,"usager3","loc_usa3"
           ,"usager4","loc_usa4"
           ,"usager5","loc_usa5"
           ,"usager6","loc_usa6"]
    df_ville=df_ville[garde]

    tableau = df_ville.rename(columns={"geo_point_2d": "coordonnees",})

    tableau=trier_accidents(tableau)
    tableau=coordonnees_accident(tableau)

    
    return tableau

def trier_accidents(df_ville):
    #Trier par contient "Sur le passage piéton"
    #dans les colonnes : "AZ"=loc_usa1 , "BI"=loc_usa2 , "BR"=loc_usa3 , "CA"=loc_usa4 etc
    #Attention, passage pieton peut etre dans l'un mais pas dans les autres, 
    # donc ne pas trier à la suite à causes des pertes de données
    df = df_ville.copy()
    colonne=["loc_usa1","loc_usa2","loc_usa3","loc_usa4","loc_usa5","loc_usa6"]
    trie= df[colonne].apply(lambda col: col.str.contains("Sur le passage piéton"
                        , case=False, na=False)).any(axis=1)
    df= df[trie]
    df = df.reset_index(drop=True)

    return df


def coordonnees_accident(tableau, rayon=5):
    #on separe la longitude et la latitude en 2 colonnes distinctes
    #on traitre les doublons
    #On regroupe les accidents a moins de 5m

    df=tableau.copy()
    df[["latitude", "longitude"]] = (df["coordonnees"].str.split(",", expand=True))
    df = df.drop(columns=["coordonnees"])

    df["longitude"] = pd.to_numeric(df["longitude"])
    df["latitude"] = pd.to_numeric(df["latitude"])
    df= df.drop_duplicates(subset=["longitude", "latitude"],keep="first")

    lignes = df.to_dict("records")

    i = 0
    while i < len(lignes):
        j = i + 1
        while j < len(lignes):
            dist= geodesic((lignes[i]["latitude"], lignes[i]["longitude"]),
                (lignes[j]["latitude"], lignes[j]["longitude"])).meters
            
            if dist <= rayon:
                lignes.pop(j)
            else:
                j += 1
        i += 1

    df_final= pd.DataFrame(lignes)
    df_final = df_final.reset_index(drop=True)
    return df_final


def comparer_coordonnees(passage_pieton, intersection_retenue, rayon=30):
    #on compare les coordonnées des intersections avec celles des passage piétons
    #a qq metres pres et on ajoute le nb de passage pietons à l'intersections
    pp=passage_pieton.copy().to_dict("records")
    inter=intersection_retenue.copy().to_dict("records")

    for i in inter:
        nb=0
        x=0
        for j in pp:
            dist= geodesic((i["latitude"], i["longitude"])
                    ,(j["latitude"], j["longitude"])).meters


            if dist<=rayon:
                nb+=1
                x+=1
                i["latitude_pp"+str(x)]=j["latitude"]
                i["longitude_pp"+str(x)]=j["longitude"]
        i["nb_pp"]=nb
    
    inter = pd.DataFrame(inter)
    inter= inter[inter["nb_pp"] != 0]

    colonnes = ["latitude", "longitude", "intersection", "Ville/Commune", "nb_pp"]
    for col in inter.columns:
        if col not in colonnes:
            colonnes.append(col)
    inter = inter[colonnes]

    return inter


"""
------------------------------------------------------------------------------------------
METHODE DE LIAISONS:
"""
#a rajouter la ou les fonctions qui trie les pp entre ppaccident et pp OSM

def trie_intersections(final_accident,df_resultat, rayon=20):
    #On trie ici seulement les intersections
    df_acc=final_accident.copy().to_dict("records")
    df_osm=df_resultat.copy().to_dict("records")
    final_pp = []

    for i in df_osm:
        trouve= False
        

        for j in df_acc:
            dist= geodesic((i["latitude"], i["longitude"])
                    ,(j["latitude"], j["longitude"])).meters

            if dist<=rayon:
                nb=comparer_passages(i,j)
                
                final_pp.append({
                "latitude": i["latitude"],
                "longitude": i["longitude"],
                "nb_pp": nb
                })
            
                j["fusionner"] = True
                trouve = True 
                break

        if not trouve:
            final_pp.append({
                "latitude": i["latitude"],
                "longitude": i["longitude"],
                "nb_pp": i["nb_passages_pietons"]
                })
    
    for j in df_acc:
        if not j.get("fusionner", False):
            final_pp.append({
                "latitude": j["latitude"],
                "longitude": j["longitude"],
                "nb_pp": j["nb_pp"]
            })
   
    return pd.DataFrame(final_pp)


def comparer_passages(inter_osm, inter_accident, rayon=5):

    passages_uniques = []

    # Ajout des passages OSM
    for i in range(1, inter_osm["nb_passages_pietons"] + 1):

        passages_uniques.append((
            inter_osm[f"latitude_pp{i}"],
            inter_osm[f"longitude_pp{i}"]
        ))

    # Comparaison avec les passages Accidents
    for i in range(1, inter_accident["nb_pp"] + 1):

        lat = inter_accident[f"latitude_pp{i}"]
        lon = inter_accident[f"longitude_pp{i}"]

        double = False

        for lat2, lon2 in passages_uniques:

            dist = geodesic((lat, lon), (lat2, lon2)).meters

            if dist <= rayon:
                double = True
                break

        if not double:
            passages_uniques.append((lat, lon))

    return len(passages_uniques)

# ──────────────────────────── Point d'entrée d'Exécution ────────────────────────


def main(Ville, intersections):
    
    # Exemple d'application sur une commune d'Île-de-France (ex: Nanterre ou Versailles)
    print(f"--- Démarrage du traitement pour la commune : {Ville} ---")
    
    """
    CODE PP_ACCIDENTS:
    """
    path="data/raw/source_pp/accidents-corporels-de-la-circulation-routiere fichier entier.csv"
    tableau_accident = charger_accidents(path, Ville)
    final_accident=comparer_coordonnees(tableau_accident, intersections)
    
    
    """
    CODE OSM :
    """
    # Étape 1 : Conversion Nom -> ID de Relation OSM (Surface)
    id_zone = get_osm_area_id(Ville)
    
    if id_zone:
        # Étape 2 : Extraction et calcul topologique des passages par carrefour
        df_resultat = telecharger_passages_par_zone(id_zone, rayon_metres=25)
        
        if not df_resultat.empty:
            # Étape 3 : Exportation des données nettoyées et calculées
            nom_fichier_sortie = f"{DOSSIER_OUTPUT}/intersections_{Ville.lower()}_passages.csv"
            df_resultat.to_csv(nom_fichier_sortie, index=False, encoding="utf-8-sig")
            
            
            print(f"\n Traitement terminé avec succès !")
            print(f" Fichier sauvegardé sous : {nom_fichier_sortie}")
            print("\nAperçu des premières lignes générées :")
            print(df_resultat.head(10).to_string(index=False))
            analyser_repartition_passages(Ville)
        else:
            print(" Échec de la génération du tableau de données.")
    else:
        print(" Impossible de poursuivre sans identifiant de zone valide.")
    
    df_xlsx = analyser_repartition_xlsx("data/raw/FINAL_Defi_Access_Garches_22_05_2026_nettoye╠ü.xlsx")

    """
    CODE DE LIAISON DES 2 METHODES:
    """
    df_final=trie_intersections(final_accident,df_resultat)

    return df_final


if __name__ == "__main__":
    main()


# concernant les test : 
print(get_osm_area_id("Garches"))  