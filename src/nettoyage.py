import pandas as pd
import csv

def charger_intersections(path, ville):
    # charger le fichier CSV
    df = pd.read_csv(path)
    #on recupere les lignes correspondantes à la ville saisie
    colonne= df.columns[0]
    df_ville= df[df[colonne].str.contains(ville, case=False)]
    
    #on remet au propre le tableau avec des colonnes disctinctes
    lignes=[next(csv.reader([ligne])) for ligne in df_ville[colonne]]
    tableauFinal = pd.DataFrame(lignes,columns=["type","geometry/type","Longitude",
            "Latitude",
            "Intersections",
            "Ville/Commune",
            "Code Postale",
            "Code Département"
        ]
    )
    #on distinct les colonnes Ville et Département à partir de la colonne Ville/Commune
    tableauFinal[["Ville", "Département"]] = (
        tableauFinal["Ville/Commune"]
        .str.split(",", expand=True)
    )
    #on corrige les fautes dù au texte encodé
    tableauFinal = correction_intersections(tableauFinal)
    tableauFinal = normailisation_intersections(tableauFinal)
    tableauFinal = doublons_intersections(tableauFinal)
    tableauFinal = filtrer_intersections(tableauFinal)
    
    return tableauFinal

def correction_intersections(tableauFinal):
    # Correction du texte encodé
    tableauFinal["Intersections"]= (tableauFinal["Intersections"].str.replace('Ã©', 'é').
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
    return tableauFinal

def normailisation_intersections(tableauFinal):
    # Normaliser les noms de colonnes
    #df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')

    return df

def doublons_intersections(tableauFinal):
    # Identifier les doublons
    #doublons = tableauFinal[tableauFinal.duplicated()]

    return doublons

def filtrer_intersections(tableauFinal):
    # Filtrer les intersections en fonction du type de voie
    typevoie = {"Avenue","Esplanade", "Boulevard"}  # Ajouter d'autres types de voies si nécessaire
    tableauFinal= tableauFinal[tableauFinal["Intersections"].str.contains("|".join(typevoie), case=False)]


    return intersections_commune


#demander le nom de la commune
ville=input("Entrez le nom de la commune : ")

#demander le nom du fichier csv
nom = input("Entrez le nom du fichier CSV (sans l'extension .csv) : ")
path="data/output/" + nom + ".csv"




