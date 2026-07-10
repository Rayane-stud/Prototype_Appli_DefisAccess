"""
Fusion "mixte" du comptage de passages piétons par intersection : combine la
détection IA (YOLO, filtrée par confiance) et la méthode OSM+Accidents
(identification_PP.main), pour se rapprocher de la valeur réelle plutôt que
de systématiquement privilégier la méthode qui en détecte le plus.

Constat statistique à l'origine de ce module : l'IA a tendance à surestimer
le nombre de passages piétons détectés par intersection, alors qu'OSM+Accidents
a tendance à sous-estimer. Les deux comptages encadrent donc souvent la
valeur réelle depuis des directions opposées.
"""

import numpy as np
import IA_PP
import identification_PP
from geopy.distance import geodesic


def calculer_mixte(
    tab_croisement,
    ville: str,
    base_dir,
    conf_min: float = 0.27,
    rayon_m: float = 25,
    rayon_filtre_m: float = 25,
    dossier_images: str = None,
):
    """
    Calcule le nombre de passages piétons par intersection en combinant l'IA
    (détections filtrées par confiance >= conf_min et par distance géométrique
    à l'intersection ciblée) et OSM+Accidents.

    Args:
        tab_croisement : DataFrame des intersections (colonnes latitude/longitude).
        ville          : nom de la commune, transmis à identification_PP.main.
        base_dir       : dossier racine du projet (contenant data/raw, data/output).
        conf_min       : seuil de confiance minimal par détection YOLO (0 à 1).
        rayon_m        : rayon (mètres) de correspondance géographique entre les
                         intersections de tab_croisement et celles renvoyées par
                         identification_PP.main.
        rayon_filtre_m : rayon (mètres) du filtre géométrique IA (voir
                         IA_PP.analyser_intersection_filtre) — ignore les passages
                         piétons d'intersections voisines visibles dans le même cadrage.
        dossier_images : dossier de sauvegarde des images annotées par l'IA (optionnel).

    Returns:
        Copie de tab_croisement avec les colonnes ajoutées :
            nb_traversees             – comptage final (mixte).
            nb_traversees_ia          – comptage IA filtré par conf_min.
            nb_traversees_osm_accident – comptage OSM+Accidents.
    """
    # ── Méthode IA (filtrée par confiance et par distance géométrique) ──
    df_ia = IA_PP.analyser_toutes_intersections_filtre(
        tab_croisement, col_lat="latitude", col_lon="longitude",
        rayon_filtre_m=rayon_filtre_m, dossier_images=dossier_images, conf_min=conf_min,
    )

    # ── Méthode OSM+Accidents ────────────────────────────────────────────
    df_osm_acc = identification_PP.main(ville, tab_croisement, base_dir=base_dir)

    resultat = tab_croisement.copy()
    resultat["nb_traversees_ia"] = df_ia["nb_traversees"].to_numpy()

    if df_osm_acc is None or df_osm_acc.empty:
        print("\n Méthode OSM+Accidents indisponible pour cette commune — "
              "le comptage mixte retombe entièrement sur l'IA.")
        resultat["nb_traversees_osm_accident"] = 0
        resultat["nb_traversees"] = resultat["nb_traversees_ia"]
        return resultat

    # ── Correspondance géographique IA <-> OSM+Accidents ────────────────
    osm_acc_records = df_osm_acc.to_dict("records")
    nb_osm_acc_par_ligne = []
    for _, ligne in tab_croisement.iterrows():
        meilleur = 0
        for osm_acc in osm_acc_records:
            dist = geodesic(
                (ligne["latitude"], ligne["longitude"]),
                (osm_acc["latitude"], osm_acc["longitude"]),
            ).meters
            if dist <= rayon_m:
                meilleur = max(meilleur, osm_acc["nb_traversees"])
        nb_osm_acc_par_ligne.append(meilleur)
    resultat["nb_traversees_osm_accident"] = nb_osm_acc_par_ligne

    # ── Combinaison : compromis quand les deux méthodes détectent quelque
    # chose, sinon on garde la valeur de la méthode qui a des données (on ne
    # tire pas le résultat vers 0 juste parce qu'une méthode n'a rien trouvé
    # à cet endroit précis) ──────────────────────────────────────────────
    nb_ia = resultat["nb_traversees_ia"]
    nb_osm_acc = resultat["nb_traversees_osm_accident"]

    deux_positifs = (nb_ia > 0) & (nb_osm_acc > 0)
    compromis = ((nb_ia + nb_osm_acc) / 2).round().astype(int)
    resultat["nb_traversees"] = np.where(deux_positifs, compromis, nb_ia + nb_osm_acc)

    # ── Résumé diagnostic ────────────────────────────────────────────────
    nb_compromis = int(deux_positifs.sum())
    print(f"\n Fusion mixte IA (conf >= {conf_min}) / OSM+Accidents :")
    print(f"   Total passages détectés par l'IA filtrée   : {int(nb_ia.sum())} (moyenne {nb_ia.mean():.2f}/intersection)")
    print(f"   Total passages détectés par OSM+Accidents  : {int(nb_osm_acc.sum())} (moyenne {nb_osm_acc.mean():.2f}/intersection)")
    print(f"   Total passages retenus (mixte)             : {int(resultat['nb_traversees'].sum())} (moyenne {resultat['nb_traversees'].mean():.2f}/intersection)")
    print(f"   {nb_compromis} intersection(s) sur {len(resultat)} où les deux méthodes détectent quelque chose (moyenne appliquée).")

    return resultat
