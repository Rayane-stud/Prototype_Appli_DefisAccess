"""
Détection automatique de passages piétons dans des images aériennes.

Source d'images : IGN Géoportail WMS (gratuit, France entière, sans clé).
Méthode       : vision par ordinateur classique (OpenCV).
Utilisation   : 100 images par exécution, ~0.5 s de délai entre requêtes.
"""

import math
import os
import time

import numpy as np
import requests
from PIL import Image
from io import BytesIO

try:
    import cv2
    _CV2_DISPONIBLE = True
except ImportError:
    _CV2_DISPONIBLE = False

try:
    from ultralytics import YOLO as _YOLO
    _YOLO_DISPONIBLE = True
except ImportError:
    _YOLO_DISPONIBLE = False

_CHEMIN_MODELE = os.path.join(os.path.dirname(__file__), "..", "models", "best.pt")
_MODELE_YOLO = None


def _charger_modele():
    # ETAPE 1 : on utilise une variable globale pour ne charger le modèle qu'une seule fois
    # sans ça, YOLO rechargerait best.pt à chaque intersection ce qui prendrait plusieurs secondes
    global _MODELE_YOLO
    if _MODELE_YOLO is None:
        # ETAPE 2 : on vérifie que la bibliothèque ultralytics est bien installée dans le venv
        if not _YOLO_DISPONIBLE:
            raise ImportError("ultralytics est requis : pip install ultralytics")
        # ETAPE 3 : on vérifie que le fichier best.pt existe avant de tenter de le charger
        if not os.path.exists(_CHEMIN_MODELE):
            raise FileNotFoundError(f"Modèle introuvable : {_CHEMIN_MODELE}")
        # ETAPE 4 : on charge le modèle et on le garde en mémoire pour les prochains appels
        _MODELE_YOLO = _YOLO(_CHEMIN_MODELE)
    return _MODELE_YOLO


# ---------------------------------------------------------------------------
# Configuration IGN
# ---------------------------------------------------------------------------

_IGN_WMS_URL = "https://data.geopf.fr/wms-r/wms"
_IGN_LAYER = "ORTHOIMAGERY.ORTHOPHOTOS"


# ---------------------------------------------------------------------------
# Étape 1 — Récupération de l'image aérienne
# ---------------------------------------------------------------------------

def get_image_ign(
    lat: float,
    lon: float,
    emprise_m: float = 80,
    taille_px: int = 512,
) -> np.ndarray:
    """
    Télécharge une orthophoto IGN Géoportail centrée sur (lat, lon).

    Args:
        lat       : Latitude WGS84 en degrés décimaux.
        lon       : Longitude WGS84 en degrés décimaux.
        emprise_m : Largeur de la zone capturée en mètres (image carrée).
        taille_px : Taille de l'image retournée en pixels.

    Returns:
        Image numpy array RGB de forme (taille_px, taille_px, 3).

    Raises:
        requests.HTTPError : Erreur HTTP du serveur IGN.
        ValueError         : L'IGN a renvoyé une exception WMS au lieu d'une image.
    """
    # ETAPE 1 : on calcule les décalages en degrés autour du point central
    # 111 000 m = longueur approximative d'un degré de latitude sur Terre
    # le cosinus corrige la longitude qui "rétrécit" en s'éloignant de l'équateur
    delta_lat = (emprise_m / 2.0) / 111_000.0
    delta_lon = (emprise_m / 2.0) / (111_000.0 * math.cos(math.radians(lat)))

    # ETAPE 2 : on construit la bounding box au format "lat_min,lon_min,lat_max,lon_max"
    # attendu par le service WMS de l'IGN en projection EPSG:4326
    bbox = f"{lat - delta_lat},{lon - delta_lon},{lat + delta_lat},{lon + delta_lon}"

    # ETAPE 3 : on prépare les paramètres de la requête WMS
    # ORTHOIMAGERY.ORTHOPHOTOS = couche des photos aériennes IGN (gratuite, France entière)
    params = {
        "SERVICE": "WMS",
        "REQUEST": "GetMap",
        "VERSION": "1.3.0",
        "LAYERS": _IGN_LAYER,
        "STYLES": "",
        "CRS": "EPSG:4326",
        "BBOX": bbox,
        "WIDTH": taille_px,
        "HEIGHT": taille_px,
        "FORMAT": "image/jpeg",
    }

    # ETAPE 4 : on envoie la requête et on vérifie qu'on reçoit bien une image
    # raise_for_status() lève une erreur si le serveur répond avec un code HTTP d'erreur (4xx, 5xx)
    reponse = requests.get(_IGN_WMS_URL, params=params, timeout=15)
    reponse.raise_for_status()

    # ETAPE 5 : on vérifie que l'IGN n'a pas renvoyé une erreur XML déguisée en réponse 200
    content_type = reponse.headers.get("Content-Type", "")
    if "xml" in content_type or b"ServiceException" in reponse.content[:300]:
        raise ValueError(f"Erreur WMS IGN : {reponse.text[:400]}")

    # ETAPE 6 : on convertit les bytes de la réponse en tableau numpy RGB utilisable par YOLO et OpenCV
    image_pil = Image.open(BytesIO(reponse.content)).convert("RGB")
    return np.array(image_pil)


# ---------------------------------------------------------------------------
# Étape 2a — Détection par YOLO (modèle entraîné)
# ---------------------------------------------------------------------------

def detect_passages_pietons_yolo(image: np.ndarray, chemin_sauvegarde: str = None) -> dict:
    """
    Détecte les passages piétons avec le modèle YOLOv8 entraîné (best.pt).

    Args:
        image             : Tableau numpy RGB.
        chemin_sauvegarde : Chemin fichier pour sauvegarder l'image annotée (optionnel).

    Returns:
        dict avec les clés :
            detecte (bool)       – True si au moins un passage piéton détecté.
            nb_traversee (int)   – Nombre de passages piétons détectés.
            confiance (float)    – Confiance moyenne des détections (0 à 1).
    """
    # ETAPE 1 : on charge le modèle YOLO (mis en cache après le premier appel)
    model = _charger_modele()
    # ETAPE 2 : on lance la détection sur l'image — verbose=False désactive les logs YOLO dans le terminal
    results = model(image, verbose=False)
    # ETAPE 3 : on récupère les bounding boxes détectées et on compte les passages piétons trouvés
    boxes = results[0].boxes
    nb = len(boxes)
    # ETAPE 4 : on calcule la confiance moyenne (0 si aucune détection pour éviter une division par zéro)
    confiance = float(boxes.conf.mean()) if nb > 0 else 0.0

    # ETAPE optionnelle : si un chemin est fourni, on sauvegarde l'image annotée
    # results[0].plot() demande à YOLO de dessiner les bounding boxes directement sur l'image
    # Image.fromarray() convertit le tableau numpy en image PIL pour pouvoir l'enregistrer
    if chemin_sauvegarde:
        Image.fromarray(results[0].plot()).save(chemin_sauvegarde)

    return {
        "detecte": nb > 0,
        "nb_traversee": nb,
        "confiance": round(confiance, 2),
    }


# ---------------------------------------------------------------------------
# Étape 2b — Détection par vision par ordinateur (OpenCV, fallback)
# ---------------------------------------------------------------------------

def _masque_routes(image: np.ndarray) -> np.ndarray:
    """
    Masque binaire des zones de chaussée (bitume + marquages).

    Adaptatif : ne repose pas sur une valeur absolue de gris (qui varie selon
    la ville, la saison, l'heure).  Deux critères combinés :
      - Faible saturation (s < 50) : le bitume est neutre/gris dans toutes
        les villes, contrairement aux tuiles rouges, végétation verte, etc.
      - Relativement sombre par rapport à son voisinage (< 90 % du flou
        sur 5 m) : distingue la chaussée sombre des façades claires voisines,
        quelle que soit la luminosité globale de l'image.
    Une petite dilatation (~0.8 m) inclut ensuite les bandes blanches
    directement posées sur le bitume (passages piétons, lignes).
    """
    gris = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32)
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    s = hsv[:, :, 1]

    # Luminosité locale de fond (fenêtre ~5 m)
    taille_fenetre = max(21, (image.shape[0] // 20) | 1)  # impair, min 21 px
    fond = cv2.blur(gris, (taille_fenetre, taille_fenetre))

    neutre = (s < 50)                                  # gris neutre
    sombre = (gris < fond * 0.90) & (gris > 20)       # plus sombre que le fond
    core = (neutre & sombre).astype(np.uint8) * 255

    noyau = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 10))
    return cv2.dilate(core, noyau)


def _espacements_reguliers(paralleles: list, angle_deg: float) -> bool:
    """
    Vérifie qu'il existe un cluster LOCAL de bandes parallèles régulièrement
    espacées, signature d'un passage piéton.

    Principe : un passage piéton occupe une zone de ~2–8 m. On fait glisser
    une fenêtre de 120 px sur les projections triées des centres de segments
    et on vérifie si, dans cette fenêtre, les intervalles sont réguliers
    (coeff. de variation < 0.5) avec au moins 4 bandes.

    Chercher la régularité sur l'image entière était faux : plusieurs routes
    au même angle produisent des segments éparpillés sans régularité globale.
    """
    if len(paralleles) < 4:
        return False
    perp = math.radians(angle_deg + 90)
    px, py = math.cos(perp), math.sin(perp)
    projections = sorted(
        (s["coords"][0] + s["coords"][2]) / 2 * px
        + (s["coords"][1] + s["coords"][3]) / 2 * py
        for s in paralleles
    )
    # Fenêtre glissante : largeur max d'un passage piéton en pixels (~120 px ≈ 9 m)
    for ref in projections:
        fenetre = [p for p in projections if abs(p - ref) <= 120]
        if len(fenetre) < 4:
            continue
        intervalles = np.diff(fenetre)
        if len(intervalles) < 3:
            continue
        cv = float(np.std(intervalles) / (np.mean(intervalles) + 1e-6))
        if cv < 0.5:
            return True
    return False


def detect_passages_pietons_cv(
    image: np.ndarray,
    emprise_m: float = 80,
) -> dict:
    """
    Détecte les passages piétons dans une image aérienne.

    Principe : les passages piétons = bandes blanches parallèles et régulières
    sur bitume sombre. L'algorithme isole les pixels clairs, détecte les
    segments rectilignes (transformée de Hough) et vérifie leur parallélisme.

    Args:
        image     : Tableau numpy RGB (taille_px × taille_px × 3).
        emprise_m : Emprise au sol de l'image (pour calibrer les filtres en mètres).

    Returns:
        dict avec les clés :
            detecte (bool)         – True si un passage piéton est détecté.
            confiance (float)      – Score 0 à 1 (1 = très certain).
            nb_bandes (int)        – Nombre de bandes parallèles détectées.
            angle_dominant (float) – Orientation des bandes en degrés (0–180).
            segments (list)        – Liste [[x1,y1,x2,y2], ...] des segments retenus.

    Raises:
        ImportError : Si opencv-python n'est pas installé.
    """
    if not _CV2_DISPONIBLE:
        raise ImportError(
            "opencv-python est requis : pip install opencv-python"
        )

    taille_px = image.shape[0]
    m_par_px = emprise_m / taille_px

    # Longueurs réalistes d'une bande de passage piéton (1.2 m – 7 m)
    long_min_px = max(4, int(1.2 / m_par_px))
    long_max_px = int(7.0 / m_par_px)

    # --- Masque route : seul le bitume nous intéresse ---
    masque_route = _masque_routes(image)

    # --- Marquages blancs restreints à la chaussée ---
    gris = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    _, binaire = cv2.threshold(gris, 200, 255, cv2.THRESH_BINARY)
    noyau = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    binaire = cv2.morphologyEx(binaire, cv2.MORPH_OPEN, noyau)
    binaire = cv2.bitwise_and(binaire, masque_route)

    # --- Détection des segments rectilignes ---
    lignes = cv2.HoughLinesP(
        binaire,
        rho=1,
        theta=np.pi / 180,
        threshold=20,
        minLineLength=long_min_px,
        maxLineGap=4,
    )

    resultat_vide = {
        "detecte": False,
        "confiance": 0.0,
        "nb_bandes": 0,
        "angle_dominant": None,
        "segments": [],
    }

    if lignes is None or len(lignes) < 3:
        return resultat_vide

    # --- Filtrage par longueur ---
    infos = []
    for seg in lignes:
        x1, y1, x2, y2 = seg[0]
        longueur = math.hypot(x2 - x1, y2 - y1)
        if long_min_px <= longueur <= long_max_px * 2:
            angle = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
            infos.append({"coords": seg[0].tolist(), "angle": angle})

    if len(infos) < 4:
        return resultat_vide

    # --- Test de tous les angles : pas d'hypothèse sur l'orientation de la route ---
    # Chaque ville a des routes à des orientations différentes.  On cherche
    # si UN angle quelconque produit un cluster local de bandes régulières.
    def ecart_angulaire(a, ref):
        d = abs(a - ref)
        return min(d, 180.0 - d)

    meilleur_angle = None
    meilleurs_paralleles = []

    for angle_ref in np.arange(0, 180, 5):
        paralleles = [s for s in infos if ecart_angulaire(s["angle"], float(angle_ref)) < 15]
        if len(paralleles) < 4:
            continue
        if _espacements_reguliers(paralleles, float(angle_ref)):
            # On garde l'angle qui regroupe le plus de bandes valides
            if len(paralleles) > len(meilleurs_paralleles):
                meilleur_angle = float(angle_ref)
                meilleurs_paralleles = paralleles

    if not meilleurs_paralleles:
        return resultat_vide

    nb_bandes = len(meilleurs_paralleles)
    confiance = round(min(nb_bandes / 6.0, 1.0), 2)
    detecte = nb_bandes >= 4

    return {
        "detecte": detecte,
        "confiance": confiance,
        "nb_bandes": nb_bandes,
        "angle_dominant": round(meilleur_angle, 1),
        "segments": [s["coords"] for s in meilleurs_paralleles],
    }


# ---------------------------------------------------------------------------
# Étape 3 — Analyse d'une intersection
# ---------------------------------------------------------------------------

def analyser_intersection(
    lat: float,
    lon: float,
    emprise_m: float = 80,
    taille_px: int = 512,
    sauvegarder_image: str = None,
    sauvegarder_image_annotee: str = None,
) -> dict:
    """
    Télécharge l'image IGN d'une intersection et détecte les passages piétons.

    Args:
        lat              : Latitude WGS84.
        lon              : Longitude WGS84.
        emprise_m        : Zone couverte en mètres.
        taille_px        : Résolution de l'image.
        sauvegarder_image: Chemin fichier pour sauvegarder l'image (optionnel).

    Returns:
        dict avec les clés :
            lat, lon, image_ok (bool), pp_detecte (bool),
            pp_confiance (float), pp_nb_bandes (int), erreur (str|None).
    """
    # ETAPE 1 : on prépare le dictionnaire de résultat avec des valeurs par défaut
    # image_ok=False et pp_detecte=False seront mis à jour si tout se passe bien
    resultat = {
        "lat": lat,
        "lon": lon,
        "image_ok": False,
        "pp_detecte": False,
        "pp_confiance": 0.0,
        "nb_traversee": 0,
        "erreur": None,
    }

    try:
        # ETAPE 2 : on télécharge l'orthophoto IGN centrée sur les coordonnées de l'intersection
        image = get_image_ign(lat, lon, emprise_m=emprise_m, taille_px=taille_px)
        resultat["image_ok"] = True

        # ETAPE optionnelle : si un chemin est fourni, on sauvegarde l'image brute (sans annotations)
        if sauvegarder_image:
            Image.fromarray(image).save(sauvegarder_image)

        # ETAPE 3 : on choisit la méthode de détection selon ce qui est disponible
        # YOLO en priorité car plus précis — OpenCV en fallback si best.pt est absent
        if _YOLO_DISPONIBLE and os.path.exists(_CHEMIN_MODELE):
            detection = detect_passages_pietons_yolo(image, chemin_sauvegarde=sauvegarder_image_annotee)
            resultat["pp_detecte"] = detection["detecte"]
            resultat["pp_confiance"] = detection["confiance"]
            resultat["nb_traversee"] = detection["nb_traversee"]
        else:
            # fallback OpenCV : détection par bandes blanches parallèles (moins précis)
            detection = detect_passages_pietons_cv(image, emprise_m=emprise_m)
            resultat["pp_detecte"] = detection["detecte"]
            resultat["pp_confiance"] = detection["confiance"]
            resultat["nb_traversee"] = detection["nb_bandes"]

    # ETAPE 4 : on capture les erreurs sans interrompre l'analyse des autres intersections
    except ImportError as e:
        resultat["erreur"] = f"Dépendance manquante : {e}"
    except requests.RequestException as e:
        resultat["erreur"] = f"Erreur réseau IGN : {e}"
    except Exception as e:
        resultat["erreur"] = f"Erreur : {e}"

    return resultat


# ---------------------------------------------------------------------------
# Étape 4 — Analyse en lot d'un DataFrame d'intersections
# ---------------------------------------------------------------------------

def analyser_toutes_intersections(
    df,
    col_lat: str = "lat",
    col_lon: str = "lon",
    emprise_m: float = 80,
    taille_px: int = 512,
    delai_s: float = 0.5,
    dossier_images: str = None, # Dossier de stockage de l'image annotée
):
    """
    Analyse toutes les intersections d'un DataFrame pandas.

    Compatible avec la sortie de nettoyage.py (mêmes noms de colonnes par défaut).

    Args:
        df       : DataFrame avec colonnes de coordonnées.
        col_lat  : Nom de la colonne latitude.
        col_lon  : Nom de la colonne longitude.
        emprise_m: Emprise au sol par image en mètres.
        taille_px: Résolution des images téléchargées.
        delai_s  : Pause entre requêtes IGN (évite la surcharge serveur).

    Returns:
        Copie du DataFrame avec les colonnes ajoutées :
            pp_detecte, pp_confiance, pp_nb_bandes, pp_image_ok, pp_erreur.
    """
    # ETAPE 1 : si un dossier de sauvegarde est demandé, on le crée maintenant
    # exist_ok=True évite une erreur si le dossier existe déjà (ex : double exécution)
    if dossier_images:
        os.makedirs(dossier_images, exist_ok=True)

    resultats = []
    total = len(df)

    for i, (_, ligne) in enumerate(df.iterrows(), 1):
        lat_i = float(ligne[col_lat])
        lon_i = float(ligne[col_lon])
        print(f"[{i}/{total}] ({lat_i:.5f}, {lon_i:.5f}) ...", end=" ", flush=True)

        # ETAPE 2 : on construit le chemin de l'image annotée pour cette intersection
        # le nom inclut le numéro d'ordre (4 chiffres) et les coordonnées pour retrouver facilement l'image
        # si pas de dossier demandé, chemin_img vaut None et aucune image n'est sauvegardée
        chemin_img = (
            os.path.join(dossier_images, f"{i:04d}_{lat_i:.5f}_{lon_i:.5f}.jpg")
            if dossier_images else None
        )
        # ETAPE 3 : on analyse l'intersection et on passe le chemin image pour la sauvegarde annotée
        res = analyser_intersection(lat_i, lon_i, emprise_m=emprise_m, taille_px=taille_px,
                                    sauvegarder_image_annotee=chemin_img)

        # ETAPE 4 : on affiche le résultat dans le terminal pour suivre la progression
        if res["erreur"]:
            print(f"ERREUR : {res['erreur']}")
        else:
            statut = "PP détecté" if res["pp_detecte"] else "aucun PP"
            print(f"{statut}  (confiance={res['pp_confiance']}, nb_traversee={res['nb_traversee']})")

        resultats.append(res)
        # ETAPE 5 : on attend entre chaque requête pour ne pas surcharger le serveur IGN
        if i < total:
            time.sleep(delai_s)

    # ETAPE 6 : on ajoute les colonnes de résultats au DataFrame original
    # df.copy() évite de modifier le tableau d'origine passé en argument
    df_sortie = df.copy()
    df_sortie["pp_detecte"]   = [r["pp_detecte"]   for r in resultats]
    df_sortie["pp_confiance"] = [r["pp_confiance"]  for r in resultats]
    df_sortie["nb_traversees"] = [r["nb_traversee"]  for r in resultats]
    df_sortie["pp_image_ok"]  = [r["image_ok"]      for r in resultats]
    df_sortie["pp_erreur"]    = [r["erreur"]         for r in resultats]

    return df_sortie
