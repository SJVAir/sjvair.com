"""
Hand-kept crosswalk from a normalised DDRDP project or dairy name
(ddrdp.normalise_name()) to the CADD dairy it names, for grants
import_ddrdp couldn't match by name and mailing city (or a unique name
Valley-wide). Extend it from import_ddrdp's "Unmatched" printout, one entry
at a time, each with a comment saying why: what CADD calls the dairy and
where, and what the PDF calls the project and where.
"""

CROSSWALK = {
    # '<normalised project or dairy name>': <cadd_id>,
    # CADD: "<CADD name>", <CADD mailing city>; PDF: "<PDF project title>", <PDF city>

    # 2026-09-29, Fresno county
    'bar 20': 10069,
    # CADD: "Bar 20 Dairy No. 2 & 3", Kerman; PDF: "Bar 20 Dairy Biogas", Kerman
    'van der hoek': 11019,
    # CADD: "Bar None/Van Der Hoek Dairy", Helm; PDF: "Van Der Hoek Dairy Digester Pipeline Project", Helm
    'van der kooi': 11667,
    # CADD: "Charles Vander Kooi Dairy", Riverdale; PDF: "Van Der Kooi Dairy Digester Pipeline Project", Riverdale
    'vanderham': 10514,
    # CADD: "L & J Vanderham Dairy", Riverdale; PDF: "Vanderham Dairy Digester Pipeline Project", Riverdale
    'wilson': 10400,
    # CADD: "J & D Wilson & Sons Dairy", Riverdale; PDF: "Wilson Dairy Digester Project", Riverdale

    # 2026-09-29, Kern county
    'albert goyenetche': 10340,
    # CADD: "Goyenetche Dairy", Buttonwillow; PDF: "Albert Goyenetche Dairy Biogas", Buttonwillow
    'boschma': 10940,
    # CADD: "Boschma & Sons Dairy", Wasco; PDF: "Boschma Dairy Biogas", Wasco
    'poso creek': 10718,
    # CADD: "Poso Creek Family Dairy", Wasco; PDF: "Poso Creek Dairy Biogas", Wasco

    # 2026-09-29, Kings county
    'verwey hanford': 11670,
    # CADD: "Philip Verwey Farms Dairy", Hanford; PDF: "Verwey-Hanford Dairy Digester", Hanford
    'de groot south': 10856,
    # CADD: "DeGroot Dairy South", Hanford; PDF: "De Groot South Dairy Biogas", Hanford
    'mattos bros': 10608,
    # CADD: "Mattos Brothers Dairy", Hanford; PDF: "Mattos Bros Dairy Digester Project", Hanford
    'avenue circle h': 11674,
    # CADD: "Circle H Dairy", Corcoran; PDF: "Dairy Avenue and Circle H Biogas LLC", Corcoran

    # 2026-09-29, Madera county
    'verwey madera': 10710,
    # CADD: "Philip Verwey Dairy, Inc.", Madera; PDF: "Verwey-Madera Dairy Digester", Madera

    # 2026-09-29, Merced county
    'five h': 11261,
    # CADD: "Five H Farms #2", Merced; PDF: "Five H Dairy Digester Pipeline Project", Merced
    'meirinho': 11180,
    # CADD: "Meirinho Holsteins, LP", Merced; PDF: "Meirinho Dairy Digester Pipeline Project", Merced
    'rockshar': 11538,
    # CADD: "Rock-Shar Dairy", Merced; PDF: "Rockshar Dairy Digester Pipeline Project", Merced
    # CADD: "Fred Melo Dairy", Merced; PDF: "Melo Dairy Digester Pipeline Project", Merced
    'oliveira aafk central cluster': 11129,
    # CADD: "Joe Oliveira Dairy", Hilmar; PDF: "Oliveira Dairy - AAFK Central Dairy Digester Cluster", Hilmar
    'wickstrom jersey aafk central cluster': 11124,
    # CADD: "Wickstrom Jersey Farms, Inc.", Hilmar; PDF: "Wickstrom Jersey Farms - AAFK Central Dairy Digester Cluster", Hilmar
    'cdf howard': 11536,
    # CADD: "California Dairy Farms (CDF) Howard", Livingston; PDF: "CDF Howard Dairy Digester Project", Livingston
    '2 coelho': 11092,
    # CADD: "Coelho Frank & Sons LP", El Nido; PDF: "(2) Coelho Dairy Digester Project", El Nido

    # 2026-09-29, Stanislaus county
    'ahlem jerseys aafk central cluster': 11750,
    # CADD: "Ahlem Foothill Farms - Crows Landing", Crows Landing; PDF: "Ahlem Farms Jerseys - AAFK Central Dairy Digester Cluster", Crows Landing
    'albert mendes aafk central cluster': 10021,
    # CADD: "Albert Mendes Dairy", Crows Landing; PDF: "Albert Mendes Dairy - AAFK Central Dairy Digester Cluster", Crows Landing
    'trinkler aafk central cluster': 10864,
    # CADD: "Trinkler Dairy Farms", Ceres; PDF: "Trinkler Dairy - AAFK Central Dairy Digester Cluster", Ceres

    # 2026-09-29, Tulare county
    'hamstra': 11015,
    # CADD: "Hamstra Dairy Complex", Tulare; PDF: "Hamstra Dairy Biogas", Tulare
    'r vander eyk': 10438,
    # CADD: "Robert Vander Eyk Dairy", Pixley; PDF: "R. Vander Eyk Dairy Digester Fuel Pipeline", Pixley
    '4k': 11045,
    # CADD: "4K Dairy Farm Partnership", Pixley; PDF: "4K Dairy Digester Pipeline Project", Pixley
    'fm jerseys virtual': 10977,
    # CADD: "FM Jerseys Dairy", Tipton; PDF: "FM Jerseys Dairy Digester Virtual Pipeline Project", Tipton
    'horizon jersey': 11042,
    # CADD: "Horizon Jerseys Dairy", Tipton; PDF: "Horizon Jersey Dairy Biogas", Tipton
    'jacobus de groot 2': 11101,
    # CADD: "former Jacobus Degroot Dairy #2, de Groot Feedlot", Visalia; PDF: "Jacobus De Groot #2 Dairy Biogas", Visalia
    'udder': 10879,
    # CADD: "Brasil's Udder Dairy", Visalia; PDF: "Udder Dairy Biogas", Visalia
    'vander poel': 10070,
    # CADD: "John Vander Poel Dairy (Pixley)", Pixley; PDF: "Vander Poel Dairy Digester Pipeline Project", Pixley
    'art leyendekker': 10294,
    # CADD: "Arthur Leyendekker Dairy", Visalia; PDF: "Art Leyendekker Dairy Biogas", Visalia

    # Left unmatched on purpose:
    # - centralized/cluster projects that don't plainly name a single host dairy
    #   (Simoes Centralized, Clauss and Sunwest, T&W [two Bakersfield candidates],
    #   Top Line [three Hanford candidates], DeJager North [two Chowchilla
    #   candidates], Blue Sky [two Merced candidates], Ahlem Farms Dairy Biogas
    #   [several Hilmar candidates], Ahlem Farms Dairy Digester Project [Vista vs
    #   Vista II, both Denair], Matos Energy Works [two Merced candidates],
    #   Barcellos/Brasil Centralized, P&M Dairy and VP Farms)
    # - projects with no city/county in the PDF (cancelled/terminated): Red Top
    #   Madera, Williams Family, De Groot North, Milky Way, GP Dairy, Lakeshore
    #   Dairy Digester, Meirinho West, River Rock, (7) Brasil
    # - ambiguous: Melo Dairy (Merced): three CADD dairies carry the Melo name; no title detail picks one.
    # - no plausible CADD dairy found: Belonave, BV Dairy Biogas, Bear JR Biogas,
    #   S&S Dairy (Ceres), DJ South (Merced), Fern Oaks (Porterville),
    #   Southpoint Ranch (Madera), Grand View (Le Grand), JR Dairy (Tipton),
    #   Double L (Kings-listed, Merced city)
    # - Solano county (non-Valley): HD Ranch Biogas
}
