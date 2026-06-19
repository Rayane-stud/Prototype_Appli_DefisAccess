"""
FICHIER : main.py   MAIN FAIS PAS CLAUDE POUR TESTER L'IDENTIFICATION DES PM
BUT : Orchestrer l'ensemble du pipeline DefiAccess, de la saisie du nom
      de la commune jusqu'a la generation des feuilles terrain XLSX.
 
ETAT ACTUEL DU PIPELINE :
    1. Identification des PM (identification_PM.py)   -> BRANCHE (etapes 1a et 1b)
    2. Nettoyage des intersections (nettoyage.py)      -> PAS ENCORE BRANCHE
    3. Filtrage/regroupement (proximite.py)            -> PAS ENCORE BRANCHE
    4. Calcul d'itineraires (routage.py)                -> PAS ENCORE BRANCHE
    5. Export feuilles terrain (export.py)              -> PAS ENCORE BRANCHE
 
Pour l'instant ce fichier ne fait tourner QUE l'etape 1 (identification des PM)
car c'est la seule partie terminee et testee a ce stade. Le reste du pipeline
est laisse en commentaire, a debrancher au fur et a mesure que chaque etape
sera prete.
"""
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from identification_PM import get_code_insee_api, get_osm_area_id
 
from identification_PM import get_code_insee_api, get_osm_area_id
 
# Imports du reste du pipeline, pas encore utilises mais prepares pour la suite
# from nettoyage import charger_intersections
# from proximite import charger_points, filtre_distance, fusion_croisement, assigner_equipes
# from routage import route_toutes_equipes
# from export import export_final_equipes
"""
Script de diagnostic : on interroge l'API SANS filtre "where" ni "select"
pour voir telles quelles les colonnes disponibles et leurs vrais noms.
"""
import requests
import json
 
url = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/fr-en-adresse-et-geolocalisation-etablissements-premier-et-second-degre/records"
params = {"limit": 1}
# on demande juste 1 resultat, sans aucun filtre, pour voir la structure brute
 
reponse = requests.get(url, params=params, timeout=15)
print("Status code :", reponse.status_code)
print()
 
if reponse.status_code == 200:
    data = reponse.json()
    if data.get("results"):
        premier = data["results"][0]
        print("=== Toutes les colonnes disponibles ===")
        for cle in sorted(premier.keys()):
            print(f"  {cle} : {premier[cle]}")
    else:
        print("Aucun resultat retourne.")
else:
    print("Erreur :", reponse.text[:2000])
 
 
def main():
    # ETAPE 0 : on demande le nom de la commune une seule fois pour tout le pipeline
    # c'est ce nom qui va servir d'entree a chacune des etapes suivantes
    ville = input("Entrez le nom de la commune : ").strip()
    # .strip() supprime les espaces en trop si l'utilisateur en tape par erreur
 
    print(f"\n=== Pipeline DefiAccess pour '{ville}' ===\n")
 
    # ----------------------------------------------------------------
    # ETAPE 1 : Identification des PM
    # ----------------------------------------------------------------
 
    # ETAPE 1a : recuperation du code INSEE via l'API officielle geo.api.gouv.fr
    code_insee = get_code_insee_api(ville)
    if code_insee is None:
        # si la commune n'est pas trouvee on arrete tout le pipeline ici
        # ca ne sert a rien de continuer sans code INSEE valide
        print("❌ Impossible de continuer sans code INSEE valide.")
        return
 
    # ETAPE 1b : recuperation de l'osm_area_id via Nominatim
    osm_area_id = get_osm_area_id(ville)
    if osm_area_id is None:
        # ici on choisit de prevenir mais de continuer quand meme
        # car le code INSEE seul suffira pour les sources gouvernementales
        # (ecoles, mairies...), seule la recherche OSM complementaire sera affectee
        print("⚠️  osm_area_id non trouve, la recherche OSM complementaire sera ignoree plus tard.")
 
    print(f"\n✅ Etape 1 terminee : code_insee={code_insee} | osm_area_id={osm_area_id}")
 
    # ----------------------------------------------------------------
    # SUITE DU PIPELINE (pas encore branchee)
    # ----------------------------------------------------------------
    # Une fois identification_PM.py complete (get_ecoles_gouv, get_equipements_gouv,
    # get_PM_osm, construire_dataframe_PM), cette section appellera la fonction
    # d'orchestration de l'identification des PM pour obtenir un DataFrame
    # directement compatible avec filtre_distance() de proximite.py
 
    # df_pm = construire_dataframe_PM(ville)
    # if df_pm.empty:
    #     print("❌ Aucun PM trouve, impossible de continuer.")
    #     return
 
    # ETAPE 2 : nettoyage des intersections brutes (fichier source a definir)
    # df_intersections = charger_intersections(path_intersections, ville)
 
    # ETAPE 3 : filtrage par distance + fusion des croisements proches + repartition en equipes
    # df_filtre = filtre_distance(df_pm, df_intersections, rayon_km=0.2)
    # df_fusionne = fusion_croisement(df_filtre, threshold_km=0.03)
    # df_equipes = assigner_equipes(df_fusionne, n_equipes=5, meetup_lat=..., meetup_long=...)
 
    # ETAPE 4 : calcul de l'itineraire optimal pour chaque equipe
    # routes = route_toutes_equipes(df_equipes, rdv_lat=..., rdv_long=...)
 
    # ETAPE 5 : generation des feuilles terrain XLSX, une par equipe
    # chemins_fichiers = export_final_equipes(routes, dossier_sortie="data/output")
    # print(f"\n✅ Pipeline termine, fichiers generes : {chemins_fichiers}")
 
 
if __name__ == "__main__":
    main()