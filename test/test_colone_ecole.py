"""
Script de diagnostic : on interroge l'API SANS filtre "where" ni "select"
pour voir telles quelles les colonnes disponibles et leurs vrais noms.
"""
import requests
import json

print("=== DEBUT DU SCRIPT ===")
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