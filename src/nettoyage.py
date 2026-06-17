import pandas as pd
import csv

def charger_intersections(path, ville):
    # charger le fichier CSV
    df = pd.read_csv(path)
    #on recupere les lignes correspondantes à la ville saisie
    colonne= df.columns[0]
    df_ville= df[df[colonne].str.contains(ville, case=False)]
    print(df.head())
    print("Nouveau")
    print(df_ville.head())
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
    print(tableauFinal["Ville/Commune"].head())
    #on distinct les colonnes Ville et Département à partir de la colonne Ville/Commune
    tableauFinal[["Ville", "Département"]] = (tableauFinal["Ville/Commune"]
        .str.split(",", n=1, expand=True))
    
    
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
    col="Intersections"
    df=tableauFinal
    
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
    doublons["Longitude"] = pd.to_numeric(tableauFinal["Longitude"])
    doublons["Latitude"] = pd.to_numeric(tableauFinal["Latitude"])
    
    # supprimer doublons géographiques
    doublons= doublons.drop_duplicates(subset=["Longitude", "Latitude"],keep="first")

    return doublons

def filtrer_intersections(tableauFinal):
    # Filtrer les intersections en fonction du type de voie
    typevoie = {"Avenue","Esplanade", "Boulevard"}  # Ajouter d'autres types de voies si nécessaire
    df= tableauFinal[tableauFinal["Intersections"].str.contains(typevoie.item(), case=False)]

    return df


#demander le nom de la commune
ville=input("Entrez le nom de la commune : ")

#demander le nom du fichier csv
nom = input("Entrez le nom du fichier CSV (sans l'extension .csv) : ")
path="data/output/" + nom + ".csv"
tableau=charger_intersections(path, ville)
print (tableau)


