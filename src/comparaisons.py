"""
On effectue la comparaisons de l'éfficacité des differentes sources ici
"""
import pandas as pd
from geopy.distance import geodesic

def recuperation_comp(nom_fichier1, nom_fichier2, rayon =20):
    
    fichier2=pd.read_excel(nom_fichier2)
    fich1=nom_fichier1.copy().to_dict("records")
    fich2=fichier2.to_dict("records")

    egaux = []
    diff=[]

    for i in fich1:
        for j in fich2:
            dist=geodesic((i["latitude"],i["longitude"]),
                          (j["latitude"],j["longitude"])
                          ).meters
            if dist < rayon:

                if i[""]