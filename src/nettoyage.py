import pandas as pd
import csv

def charger_intersections(path, ville):
    # charger le fichier CSV
    df = pd.read_csv(path).copy()
    #on recupere les lignes correspondantes à la ville saisie
    colonne= "properties/context"
    df_ville= df[df[colonne].str.contains(ville, case=False)]
    print(df.head())
    print("Nouveau")
    print(df_ville.head())
    #on remet au propre le tableau avec des colonnes disctinctes
    tableauFinal = df_ville.rename(columns={
        "geometry/coordinates/0": "longitude",
        "geometry/coordinates/1": "latitude",
        "properties/name": "intersection",
        "properties/context": "Ville/Commune",
        "properties/citycode": "Code Postale",
        "properties/depcode": "Code Département"
    })
    
    print(tableauFinal["Ville/Commune"].head())
    #on distinct les colonnes Ville et Département à partir de la colonne Ville/Commune
    tableauFinal = tableauFinal.drop(columns=["type", "geometry/type", "Code Postale", "Code Département"])
    tableauFinal = tableauFinal.reset_index(drop=True)
    
    
    #on corrige les fautes dù au texte encodé
    tableauFinal = correction_intersections(tableauFinal)
    tableauFinal = normailisation_intersections(tableauFinal)
    tableauFinal = doublons_intersections(tableauFinal)
    tableauFinal = filtrer_intersections(tableauFinal)

    return tableauFinal
    

def correction_intersections(tableauFinal):
    # Correction du texte encodé
    correction = tableauFinal.copy()
    correction["intersection"]= (correction["intersection"].str.replace('Ã©', 'é').
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
    return correction

def normailisation_intersections(tableauFinal):
    # Normaliser les noms de colonnes
    col="intersection"
    df=tableauFinal.copy()
    
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
    doublons = tableauFinal.copy()
    doublons["longitude"] = pd.to_numeric(doublons["longitude"])
    doublons["latitude"] = pd.to_numeric(doublons["latitude"])

    # supprimer doublons géographiques
    doublons= doublons.drop_duplicates(subset=["longitude", "latitude"],keep="first")

    return doublons

def filtrer_intersections(tableauFinal):
    # Filtrer les intersections en fonction du type de voie
    typevoie = "Avenue|Esplanade|Boulevard"  # Ajouter d'autres types de voies si nécessaire
    df= tableauFinal[tableauFinal["intersection"].str.contains(typevoie, case=False)]

    return df
