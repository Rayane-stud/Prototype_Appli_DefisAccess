"""
On a confirme que code_insee_commune="92033" fonctionne tout seul.
On cherche maintenant comment ajouter le filtre "mairie uniquement".
"""
import requests
 
url = "https://api-lannuaire.service-public.fr/api/explore/v2.1/catalog/datasets/api-lannuaire-administration/records"
 
tentatives = [
    {"where": 'code_insee_commune="92033" AND type_service_local="mairie"', "limit": 5},
    {"where": 'code_insee_commune="92033" AND pivot_type_service_local="mairie"', "limit": 5},
    {"where": 'code_insee_commune="92033"', "limit": 30},
]
 
for i, params in enumerate(tentatives, 1):
    print(f"\n=== TENTATIVE {i} : {params} ===")
    reponse = requests.get(url, params=params, timeout=15)
    print("Status code :", reponse.status_code)
    if reponse.status_code == 200:
        data = reponse.json()
        print("Nombre de resultats :", len(data.get("results", [])))
        for r in data.get("results", []):
            pivot = r.get("pivot")
            print(" -", r.get("nom"), "| pivot:", pivot)
    else:
        print("Erreur :", reponse.text[:500])