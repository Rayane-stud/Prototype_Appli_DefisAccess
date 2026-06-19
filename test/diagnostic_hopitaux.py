"""
Diagnostic v2 : on corrige l'erreur 406 d'Overpass en ajoutant
un User-Agent et en testant differentes methodes d'envoi.
"""
import requests
 
print("=== TEST : hopitaux via OSM Overpass pour Garches (avec headers) ===")
url_overpass = "https://overpass-api.de/api/interpreter"
query = """[out:json][timeout:25];
area(3600072019)->.zone;
(
  node["amenity"="hospital"](area.zone);
  way["amenity"="hospital"](area.zone);
);
out center;"""
 
headers = {
    "User-Agent": "DefiaccessPM/1.0 (association accessibilite)",
    "Content-Type": "application/x-www-form-urlencoded"
}
 
reponse = requests.post(url_overpass, data={"data": query}, headers=headers, timeout=30)
print("Status code :", reponse.status_code)
 
if reponse.status_code == 200:
    elements = reponse.json().get("elements", [])
    print(f"{len(elements)} hopital(aux) trouve(s) pour Garches via OSM")
    for el in elements:
        tags = el.get("tags", {})
        print(" -", tags.get("name", "sans nom"))
else:
    print("Erreur :", reponse.text[:500])