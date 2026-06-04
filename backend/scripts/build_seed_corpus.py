"""Generate `app/ml/categorization/data/seed_corpus.csv`.

Hand-curated templates per category, mixed Romanian + English, with the
typical decorations a Romanian bank statement applies (POS PMT, branch
codes, location suffixes, random reference numbers). All examples are
synthetic — no real-customer data, no PII.

Run from `backend/`:
    python -m scripts.build_seed_corpus

Reproducible — same seed → same CSV. Re-run after editing this file to
refresh the on-disk corpus.
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

CORPUS_PATH = Path(__file__).resolve().parents[1] / "app" / "ml" / "categorization" / "data" / "seed_corpus.csv"

# Deterministic — re-running yields the same corpus and metrics.
RNG = random.Random(20260508)


# ---------------------------------------------------------------------------
# Decorations a typical Romanian bank statement adds around the merchant name.
# ---------------------------------------------------------------------------

PMT_PREFIXES = [
    "", "POS ", "Plata POS ", "PMT POS ", "Achizitie ", "Cumparare ",
    "Plata cu cardul ", "PURCHASE ", "PMT ",
]
LOCATION_SUFFIXES_RO = [
    "Bucuresti", "Cluj", "Timisoara", "Iasi", "Brasov", "Sibiu", "Constanta",
    "Ploiesti", "Oradea", "Galati", "Pipera", "Floreasca", "Baneasa",
    "Drumul Taberei", "Vitan", "Cotroceni", "Aviatorilor", "Promenada",
    "Mall Vitan", "AFI Cotroceni", "Park Lake", "Sun Plaza",
]
LOCATION_SUFFIXES_EN = [
    "Bucharest", "Online", "ROM", "RO", "EU", "Branch 12", "Store 04",
    "Mall", "Center", "Downtown",
]
BRANCH_TAILS = ["", " #001", " #14", " #221", " #4321", " (RO)", " RO",
                " 12345", " RID:34521", " AUT:887412"]


def _decorate(name: str, *, ro_bias: float = 0.6) -> str:
    """Wrap a base merchant with a realistic statement decoration."""
    pre = RNG.choice(PMT_PREFIXES)
    if RNG.random() < ro_bias:
        loc = RNG.choice(LOCATION_SUFFIXES_RO)
    else:
        loc = RNG.choice(LOCATION_SUFFIXES_EN)
    tail = RNG.choice(BRANCH_TAILS)
    base = name
    if RNG.random() < 0.4:
        base = base.upper()
    if RNG.random() < 0.2:
        base = base.lower()
    return f"{pre}{base} {loc}{tail}".strip()


def _expand(merchants: list[str], category: str, n: int = 12) -> list[tuple[str, str, str]]:
    """For each merchant base name, emit `n` decorated variants under `category`.

    The third tuple element is the *merchant base* — the un-decorated source
    string. The eval script uses this to do a merchant-holdout split so the
    same merchant never appears in both train and test.
    """
    out: list[tuple[str, str, str]] = []
    for m in merchants:
        for _ in range(n):
            out.append((_decorate(m), category, m))
    return out


# ---------------------------------------------------------------------------
# Per-category merchant pools. Mix of Romanian high-street + global brands +
# realistic-looking unknowns the rules don't cover (so the ML model has to
# generalize beyond regex matches).
# ---------------------------------------------------------------------------

GROCERIES = [
    # Romanian retail chains
    "Carrefour", "Auchan", "Kaufland", "Lidl", "Mega Image", "Profi",
    "Penny Market", "Selgros", "Metro Cash & Carry", "Cora", "La Doi Pasi",
    "DM Drogerie Markt", "Mic.ro", "ShopMagazin", "FreshMarket",
    "Supeco", "Albinuta Magazin", "Marketul de Cartier", "Family Market",
    "Diana Express", "Annabella", "AlimentaraXpress", "Magazin Mixt",
    "Carrefour Express", "Carrefour Market", "Mega Image Shop&Go",
    "Profi City", "Profi Loco", "XPRESS Market", "Niro Market",
    "Penny", "DM", "Macromex", "Auchan Drive", "Kaufland Online",
    "Lidl Plus", "Carrefour.ro online",
    # Local / fresh
    "Piata Obor", "Piata Amzei", "Piata Matache", "Targul de Legume",
    "Brutaria Paul", "Brutaria Boromir", "Boromir Prod", "Vel Pitar",
    "Brutaria Anatolia", "Patiseria Simigerie",
    # Specialty / international
    "Aldi", "Spar", "Eurospar", "Billa", "Tesco", "Coop", "Migros",
    "Whole Foods Market", "Trader Joe's", "Walmart Grocery",
    "Mercadona", "Carrefour City",
    # Eastern European chains (relevant to RO market reach)
    "Mere Pere magazin", "Inmedio", "Fresh Corner", "Eco Market",
    "Bio Romania", "Mega Bio", "Plafar magazin",
    # Misc
    "Magazinul de Cartier", "Supermarket Local", "Alimentara Express",
    "Mini Market Pipera", "Cosmetic & Food Shop",
]

RESTAURANTS = [
    # Delivery platforms
    "Glovo", "Wolt", "Tazz", "FoodPanda", "Uber Eats", "Bringo",
    "Bolt Food", "Hipmenu", "TakeAway",
    # Global fast-food chains — the user explicitly noted Burger King was
    # missing; we also add the long tail because the same omission likely
    # exists for Wendy's, Five Guys, Popeyes etc.
    "McDonalds", "McDonald's", "McD", "MCDS",
    "KFC", "Kentucky Fried Chicken",
    "Burger King", "BK", "BURGERKING",
    "Subway", "SUBWAY SANDWICH",
    "Starbucks", "STARBUCKS COFFEE",
    "Dominos Pizza", "Domino's",
    "Pizza Hut",
    "Wendys", "Wendy's",
    "Five Guys",
    "Shake Shack",
    "Popeyes Louisiana Kitchen",
    "Chick-fil-A",
    "Taco Bell",
    "Chipotle Mexican Grill",
    "Hardee's",
    "Carl's Jr",
    "Arby's",
    "Panera Bread",
    "Costa Coffee",
    "Tim Hortons",
    "Dunkin Donuts", "Dunkin'",
    "Krispy Kreme",
    "Pret a Manger",
    "Greggs",
    "Au Bon Pain",
    # Romanian fast-food + casual
    "5 to Go", "5toGo", "5-to-Go",
    "Spartan",
    "Springtime",
    "Mado Pastry & Coffee",
    "Fresca",
    "La Brutaria", "La Placinte",
    "Salad Box",
    "Wok to Walk",
    # Romanian sit-down + cafe
    "Caru' cu Bere", "Restaurantul La Mama", "Bistro French",
    "Cafenea Origo", "Coffee Shop Bohemia", "Pubul Trafic", "Bistroteca",
    "Sushi Master", "Burger Van", "Pizzeria Bonita", "Trattoria Buongiorno",
    "Restaurant Hanu' Berarilor", "Beans & Dots", "Caffe del Sud",
    "TucanoCoffee", "Loft Cafe", "Speakeasy",
    "Hard Rock Cafe",
    "Vatra Restaurant",
    "Linea Closer to the Moon",
    "Energiea Bar",
    "Vivo Restaurant",
    "Ramses Sushi",
    "Zen Sushi",
    "Edo Sushi",
    "Vietnam Restaurant",
    "Vietnameza Pipera",
    "El Torito Mexican",
    "Trattoria il Calcio",
    "Pizzeria Presto",
    "Pizzeria 4 Amici",
    "Hanu lui Manuc",
    "Beraria H",
    "Bere si grill",
    "Burgerista",
    "BurgerFest",
    "Smashburger",
    "Chef Burger",
    "Steak House Bucuresti",
    "Sushi Now",
    "Sushi to Go",
    "Coffee Lab",
    "Coffee Project",
    "M60 Coffee",
    "Origo Coffee",
    "Camera din Fata",
    "Acuarela Cafe",
    "Bistro Vintage",
    "Anaida Restaurant",
    "Curtea Veche Bistro",
    # Generic descriptors that should still land in Restaurants
    "Restaurant centrul vechi", "Cafenea Aviatorilor", "Pub Drumul Taberei",
    "Bar de zi Floreasca", "Terasa Vara Herastrau",
]

TRANSPORT = [
    # Rideshare
    "Bolt", "Bolt.eu", "BOLT*RIDE", "Bolt Romania",
    "Uber", "UBER*TRIP", "Uber Romania",
    "FreeNow", "Black Cab", "Yango",
    # Public transit (RO)
    "STB", "STB Bucuresti", "STB Abonament Online",
    "Metrorex", "Metrorex Abonament", "Metroul Bucuresti",
    "CFR Calatori", "CFR Bilet Online",
    "RATB", "RATBV Brasov", "RAT Sibiu", "RTEC Constanta",
    # Fuel
    "OMV", "OMV PetrolStation", "Petrom", "Petrom Statie",
    "MOL Romania", "MOL Group",
    "Rompetrol", "Rompetrol Statie",
    "Lukoil", "SOCAR", "Gazprom", "Shell Romania",
    # Parking, tolls, services
    "Parcare Piata Victoriei", "Parking Mall", "Parcare Aeroport Otopeni",
    "Autostrada A1", "Autostrada A2", "Rovinieta", "Roviniete Online",
    "Drumuri Nationale", "CNAIR Rovinieta",
    "Taxi Cobalcescu", "Taxi Pelicanul", "Taxi Cris",
    "Statia ITP", "ITP Service",
    "Vulcanizare Auto", "Cauciucuri Premium",
    "Service Auto Andrei", "Service Auto Premium", "Auto Service Pitesti",
    "Spalatorie Auto", "Carwash Express",
    # Bike / scooter / micro-mobility
    "Lime Scooter", "Tier Scooter", "Wolt Scooter", "Bolt Scooter",
    "VeloRent", "BikeRO",
    # International (not yet in rules)
    "TfL Oyster", "Deutsche Bahn", "DB Bahn", "SNCF", "Trenitalia",
    "Renfe", "OBB Austria",
    # Misc transport
    "Tarom flight", "Wizz Air voucher",
]

HOUSING = [
    "Chirie luna mai", "Chirie luna iunie", "Chirie luna iulie",
    "RENT MAY", "RENT JUNE", "RENT JULY",
    "Asociatie Proprietari Bloc 5", "Asociatie Proprietari Bloc 12",
    "Intretinere", "Întreținere casa", "Întreținere apartament",
    "Plata chirie", "Plata chirie iunie", "Plata chirie iulie",
    "Administrator bloc 12", "Administrator bloc 28",
    "Asociatie locatari", "Asociatie locatari sect 1",
    "Chirie apartament", "Chirie studio",
    "Comision agentie imobiliara",
    "Storia.ro listare", "Imobiliare.ro listare", "OLX Imobiliare",
    "Casa Inteligenta administrare",
    "Mortgage payment", "Rata ipoteca", "Rata credit ipotecar",
    "Asigurare locuinta", "Asigurare casa Allianz", "Asigurare apartament",
    "Garantie chirie", "Avans chirie", "Deposit rent",
    "RealEstate Romania", "Property Manager fees",
    "Curatenie apartament", "Curatenie casa",
    "Reparatii instalatie sanitara", "Instalator urgenta",
    "Electrician apartament", "Mentenanta lift",
]

UTILITIES = [
    "Enel Energie", "Enel Romania", "ENEL*FACT",
    "E.ON", "E.ON Energie Romania", "EON.RO factura",
    "Electrica Furnizare", "Electrica Distributie",
    "CEZ Vanzare", "CEZ Romania",
    "Hidroelectrica", "Hidroelectrica vanzare",
    "Engie Romania", "ENGIE FACT", "Engie GazNaturale",
    "Distrigaz Sud", "Gaze Naturale", "Gaze Naturale Romania",
    "Apa Nova", "Apa Nova Bucuresti", "Apa Regnault",
    "Raja Constanta", "Apa Cluj", "ApaServ Brasov", "Aquatim Timisoara",
    "RCS-RDS", "RCS RDS", "Digi Romania", "DIGI*FACT",
    "UPC Romania", "Vodafone Romania", "Vodafone Cable",
    "Telekom Romania", "Telekom Mobile", "Orange Romania",
    "Orange Romania Fixed", "Orange PrePay", "Orange Fix",
    "Salubritate URBAN", "Salubrizare Bucuresti", "REBU Bucuresti",
    "RetiM Servicii", "Termoenergetica", "Termoficare CET",
    "Radet Bucuresti", "Termoenergetica Sud",
    "Internet la Domiciliu", "Internet fibra optica",
    "Cablu TV + Internet", "TV Cablu Romtelecom",
    "Factura curent", "Factura gaze", "Factura apa", "Factura internet",
    "Apometru index", "Citire contor",
]

HEALTH = [
    "Farmacia Tei", "Farmacia Catena", "Farmacia Sensiblu", "Farmacia Dona",
    "Farmacia Help", "Farmacia 24h",
    "HelpNet", "Pharmacy 24/7", "Pharmacy ROK",
    "Regina Maria", "Reteaua Regina Maria",
    "Medicover", "Medicover Romania",
    "MedLife", "MedLife Constanta",
    "Sanador", "Sanador Diagnostic",
    "Synevo", "Synevo Laborator", "Synevo Labs",
    "Clinica Polisano",
    "Cabinet Stomatologic Smile", "Cabinet Stomatologic Bright",
    "Dentist Brilliant", "Dr Dentist", "Dr. Dent",
    "Medical Center Bucuresti", "Centrul Medical Pluton",
    "Centrul Medical Aviatorilor",
    "Optica Optiblu", "Lensa.ro", "Optimall optica",
    "Optica Quattro", "Lentile contact Online",
    "Spitalul Floreasca", "Spitalul Coltea", "Spitalul Elias",
    "Spitalul Sf. Pantelimon",
    "Policlinica Titu Maiorescu",
    "Cabinet Familie Dr. Popescu", "Medic de familie",
    "Cabinet Cardiologie", "Cabinet Dermatologie", "Cabinet Ortopedie",
    "Psiholog Cabinet",
    "Logoped sedinta",
    "Recoltare analize", "Analize medicale",
    "Vaccinare Centrul Medical",
    "Fizioterapie sedinta",
    "Yoga clasa", "Pilates studio", "Sala fitness 7card",
    "World Class Romania", "Lifeclub Sala",
]

ENTERTAINMENT = [
    "Cinema City", "Cinema City Promenada", "Cinema City AFI",
    "Cinemax", "Cinemax Iulius Mall",
    "Hollywood Multiplex",
    "Steam", "Steam Store", "Steam Wallet",
    "Epic Games Store", "Epic Games",
    "PlayStation Network", "PSN Store",
    "Xbox Live", "Xbox Game Pass",
    "Nintendo eShop", "Nintendo Switch Online",
    "GOG.com",
    "Eventim", "Eventim Bilet", "Bilet Master", "iaBilet",
    "iaBilet concert", "Bilet Filarmonica",
    "Teatrul National", "Teatrul Bulandra", "Teatrul Mic", "Teatrul Comedie",
    "Opera Bucuresti", "Opera Nationala",
    "Concert Sala Polivalenta", "Sala Palatului concert",
    "Festival Untold", "Festival Electric Castle", "Festival Awake",
    "Festival Neversea",
    "Bowling Cosmos", "Bowling Mega Mall",
    "Escape Room Logica", "Escape Room Adventure",
    "Karaoke Bar Avant", "Karaoke Sing City",
    "Bilete fotbal Steaua", "Bilete fotbal Dinamo",
    "Aquapark Therme",
    "Park Lake bowling",
    "Cinema 3D AFI",
    "Concert Mihai Margineanu",
    "Biletul Sportiv",
    "Roblox subscription",
    "Twitch subscription",
    "Discord Nitro",
    "Adobe Premiere Pro home",
    "Joc PC Steam",
]

SUBSCRIPTIONS = [
    "Spotify", "Spotify Premium", "Spotify Family",
    "Netflix", "Netflix Premium", "Netflix Standard",
    "HBO Max", "HBO Max RO", "Max.com",
    "Disney+", "Disney Plus", "Disney+ RO",
    "YouTube Premium", "YouTube Music", "YouTube TV",
    "Google One", "Google Storage", "Google Workspace",
    "iCloud", "iCloud Storage 200GB", "Apple One",
    "Apple.com/bill", "Apple Music",
    "GitHub Pro", "GitHub Copilot",
    "Notion Personal", "Notion Family", "Notion AI",
    "Figma Professional", "Figma Pro", "Linear App",
    "Vercel Pro", "Netlify Pro", "Cloudflare Pro",
    "DigitalOcean Droplet", "AWS Free Tier", "AWS billing",
    "Anthropic API", "OpenAI ChatGPT", "OpenAI Plus",
    "Claude.ai", "Claude Pro",
    "Audible",
    "Kindle Unlimited",
    "1Password Family", "1Password",
    "Bitwarden Premium", "ProtonMail", "ProtonVPN",
    "NordVPN", "Surfshark VPN", "ExpressVPN",
    "Adobe Creative Cloud", "Adobe Photoshop",
    "Microsoft 365 Family", "Office 365",
    "Dropbox Plus", "Dropbox Family",
    "Setapp",
    "Grammarly Premium",
    "DeepL Pro",
    "Evernote Personal",
    "Patreon membership",
    "OnlyFans subscription",
    "Substack subscription",
    "Medium membership",
    "Calm app",
    "Headspace",
    "Strava Premium",
    "Tinder Gold",
    "Bumble Premium",
    "LinkedIn Premium",
    "Coursera Plus annual",
    "MasterClass annual",
    "Duolingo Super",
    "Babbel subscription",
    "WordPress.com Premium",
    "Squarespace Plan",
    "Mailchimp Standard",
]

EDUCATION = [
    "Udemy", "Udemy Business", "Udemy Course",
    "Coursera", "Coursera Plus", "Coursera Specialization",
    "edX", "edX MicroMasters",
    "DataCamp", "DataCamp Premium",
    "Pluralsight", "Pluralsight Skills",
    "FrontendMasters", "Frontend Masters subscription",
    "Carturesti", "Carturesti Online",
    "Libraria Mihai Eminescu", "Libraria Diverta", "Libraria Humanitas",
    "Universitate Tehnica", "Universitatea Bucuresti", "Universitatea Cluj",
    "ASE Bucuresti", "ASE Taxa Master",
    "Facultatea de Informatica", "FMI Bucuresti", "FMI UBB",
    "Liceul Cantemir", "Colegiu National Sava",
    "Colegiul National Lazar", "Colegiul Mihai Viteazul",
    "Scoala Generala 4",
    "Curs Corporate Training", "Workshop UX", "Workshop UI",
    "Bootcamp Coding", "Bootcamp Data Science",
    "Khan Academy",
    "edX Microsoft",
    "LinkedIn Learning",
    "Skillshare",
    "Brilliant.org",
    "MasterClass course",
    "Codecademy",
    "Treehouse",
    "Memrise",
    "Babbel Learning",
    "Rosetta Stone",
    "Carte tehnica online",
    "Manual Editura Niculescu",
    "Editura Polirom carte",
    "Editura Humanitas",
    "Cursuri online IT",
    "Taxa scolarizare licenta",
    "Taxa scolarizare master",
    "Cazare camin studenti",
    "Bursa de studii",
    "Camin Bucuresti",
]

TRAVEL = [
    # OTAs
    "Booking.com", "Booking.com Hotel", "Booking RO",
    "Airbnb", "Airbnb Stay",
    "Hotels.com", "Trivago", "Expedia", "Kayak",
    "Agoda", "Hostelworld", "Vrbo",
    # Hotels (RO)
    "Hotel Cismigiu", "Hotel Caro", "Hotel Athenee Palace",
    "Hostel Friends",
    "Pensiune Bran", "Pensiune Sinaia", "Pensiune Sibiel",
    "Vila Carpati", "Vila Predeal",
    "Hotel Crowne Plaza",
    "Hotel Intercontinental",
    "Hotel Marriott Bucuresti",
    "Hotel Hilton Sibiu",
    # Airlines
    "Wizz Air", "WizzAir Bilet",
    "Blue Air", "TAROM", "TAROM bilet online",
    "Ryanair", "Lufthansa", "KLM", "Air France",
    "AeroItalia", "Vueling", "EasyJet",
    "British Airways", "Iberia",
    "Turkish Airlines", "AeroFlot",
    "Etihad Airways",
    "Emirates",
    "Qatar Airways",
    "Lufthansa Group",
    # Misc travel
    "Bilet avion online", "Tichet feribot",
    "Rezervare hotel Predeal", "Rezervare hotel Brasov",
    "Rezervare Airbnb Cluj",
    "Inchiriere masina Sixt", "Sixt Rent a Car",
    "Hertz Rent a Car", "Avis Rent",
    "Enterprise Car Rental",
    "GetYourGuide tur",
    "Viator tour",
    "Tour ghidat Roma",
    "Asigurare calatorie Allianz",
    "Asigurare travel City",
    "Excursie Italia",
    "City tour Lisbon",
    "Eurowings",
    "Norwegian Air",
]

SALARY = [
    "Salariu ACME SRL",
    "SALARY EMPLOYER", "SALARY TRANSFER",
    "Payroll April 2026", "Payroll May 2026", "Payroll June 2026",
    "Payslip ACME SRL", "Payslip Tech Corp",
    "Wage Transfer",
    "Direct Deposit ACME", "Direct Deposit Tech",
    "Salariu Net Aprilie", "Salariu Net Mai", "Salariu Net Iunie",
    "VIRAMENT SALARIU SRL", "VIRAMENT SALARIU NET",
    "Salariu luna mai", "Salariu luna iunie",
    "Direct Deposit Payroll",
    "Bonus performanta Q1", "Bonus performanta Q2",
    "Bonus anual",
    "Decont salarial",
    "Tichete masa Sodexo", "Tichete masa Up",
    "Tichete cadou Edenred",
    "Tichete vacanta",
    "Compensatie sport 7card", "Decont 7Card",
    "Salariu ore suplimentare",
    "Diurnă deplasare",
    "Decont deplasare",
    "Plata freelance proiect",
    "Plata contract drepturi autor",
    "Onorariu consultanta",
    "Royalty payment Amazon",
    "Stripe payout",
    "Upwork payout",
    "Fiverr payout",
]

TRANSFER = [
    "Transfer Revolut to BCR", "Transfer ING to Revolut",
    "Transfer BCR to ING",
    "Virament BCR catre BRD", "Virament BRD catre BCR",
    "Incasare de la Ion", "Incasare de la Maria",
    "Încasare salariu Maria",
    "P2P payment Andrei", "P2P payment Ana",
    "Transfer intern", "Transfer card to card",
    "Schimb valutar BCR", "Schimb valutar Raiffeisen",
    "Banca Transilvania transfer", "BT transfer",
    "Raiffeisen virament",
    "OTP Bank schimb", "OTP virament",
    "CEC Bank transfer", "CEC virament",
    "Revolut top-up", "Add money Revolut", "Top-up Revolut",
    "Revolut transfer to friend",
    "Wise transfer", "Wise FX",
    "Western Union transfer", "MoneyGram receive",
    "PayPal transfer", "PayPal payout",
    "Stripe internal transfer",
    "BRD transfer extern", "BCR transfer extern",
    "ING Home'Bank transfer",
    "Bank to bank SWIFT",
    "SEPA Credit Transfer",
    "Transfer cont curent",
    "Transfer in lei",
    "Transfer in EUR",
    "Schimb EUR-RON BCR",
]

INVESTMENTS = [
    "Trading 212 deposit", "Trading212 deposit", "Trading 212 Invest",
    "eToro deposit", "eToro buy",
    "Interactive Brokers",
    "DEGIRO transfer", "DEGIRO deposit",
    "XTB invest", "XTB deposit",
    "Revolut Invest", "Revolut stocks",
    "Coinbase deposit", "Coinbase buy",
    "Binance deposit", "Binance Spot",
    "Kraken purchase", "Kraken buy",
    "Crypto.com",
    "Broker BT Capital", "BT Capital Invest",
    "Brokerage Tradeville", "Tradeville Romania",
    "Stock purchase AAPL", "Stock purchase MSFT",
    "Equity buy MSFT", "Equity buy NVDA",
    "ETF VWCE", "ETF SPY", "ETF VOO",
    "ETF VUAA", "ETF EUNL", "ETF SXR8",
    "Fond mutual NN", "Fond mutual BT Asset Mgmt",
    "Pilon III pensie privata", "Pensie facultativa NN",
    "BVB tranzactie", "Bursa Bucuresti BVB",
    "Saxo Bank deposit", "Saxo Bank trade",
    "BlackRock iShares",
    "Vanguard ETF",
    "Robinhood deposit",
    "Webull deposit",
    "Fidelity Invest",
    "Charles Schwab",
    "TD Ameritrade",
    "Crypto staking reward",
    "Crypto airdrop",
    "P2P crypto exchange",
    "MetaMask transaction",
    "Uniswap swap",
    "OpenSea purchase NFT",
    "Real estate REIT",
    "Gold purchase BNR",
    "Argint investitie",
]

# "Other" includes plausible everyday merchants the rules deliberately don't
# cover, plus a smattering of random store names. Diverse text helps the ML
# model learn what NOT to confidently classify.
OTHER = [
    # Services + personal care
    "Florarie Diana", "Florarie Online", "Floraria Mada",
    "Frizerie Elite", "Frizerie Old School",
    "Salon Beauty Lounge", "Salon Coafor", "Beauty Salon Pretty",
    "Atelier Foto Andrei", "Foto Studio Premium",
    "Croitorie Express", "Croitorie de Lux",
    "Cofetaria Capsa", "Cofetaria Delice", "Cofetaria Boema",
    "Patiserie Boulangerie", "Patiserie Parisul",
    # Pet
    "Magazin Animale Companie", "Pet Shop Animax",
    "Pet Shop Animalier", "Petexpert",
    "Cabinet Veterinar Pet Doctor",
    # Repairs
    "Curatatorie chimica", "Curatatorie 5aSec",
    "Reparatii electrocasnice", "Service GSM",
    "Service Telefon", "Service Laptop", "iService Apple",
    "Geam Auto Service",
    # Bricolaj
    "Bricolaj Dedeman", "Hornbach magazin", "Praktiker",
    "Leroy Merlin", "BAUMAX",
    # Mobilier + decoratiuni
    "Mobexpert", "IKEA Bucuresti", "JYSK mobilier",
    "Kika mobilier", "Lem's mobilier",
    "Casa Rusu mobilier",
    # Sport
    "Decathlon", "Intersport", "Hervis Sports",
    "JD Sports", "Sportisimo",
    # Fashion
    "C&A fashion", "H&M magazin", "Zara online",
    "Bershka shop", "Pull&Bear", "Reserved RO",
    "LC Waikiki", "Sinsay",
    "Mango shop", "Massimo Dutti", "Stradivarius",
    "Uniqlo",
    "Tommy Hilfiger",
    "Calvin Klein store",
    "Adidas store", "Nike store", "Puma store",
    "New Yorker",
    "House", "Sephora",
    "Douglas magazin", "Marionnaud",
    "Pandora bijuterii", "Bijuterii B&D",
    # Online retail
    "Emag.ro", "eMAG", "Altex.ro", "PC Garage",
    "Evomag", "Domo Romania", "Cel.ro",
    "Compari.ro", "Vivre.ro", "Answear.ro",
    "Fashion Days", "About You",
    "Aliexpress order", "Amazon DE",
    "Amazon order", "Amazon.com",
    "Wish.com",
    "Temu order",
    "Shein order",
    "Etsy purchase",
    # Misc
    "Plata diversa", "Cadou online", "Achizitie diversa",
    "Donatie ONG", "Salvati Copiii donatie",
    "Crucea Rosie donatie",
    "Gift card", "Card cadou eMAG",
    "Achizitie aplicatie",
    "Plata online generic",
    "Card preplatit Up", "Up Card",
    "Tichet cultural Edenred",
]


def main() -> None:
    rows: list[tuple[str, str, str]] = []
    # Variant counts roughly equalize per-category row totals (the model uses
    # `class_weight="balanced"` but a flat-ish corpus still produces more
    # stable F1 across smaller categories like Housing).
    rows += _expand(GROCERIES, "Groceries", n=14)
    rows += _expand(RESTAURANTS, "Restaurants", n=14)
    rows += _expand(TRANSPORT, "Transport", n=14)
    rows += _expand(HOUSING, "Housing", n=18)        # smaller pool, more variants
    rows += _expand(UTILITIES, "Utilities", n=14)
    rows += _expand(HEALTH, "Health", n=14)
    rows += _expand(ENTERTAINMENT, "Entertainment", n=14)
    rows += _expand(SUBSCRIPTIONS, "Subscriptions", n=12)
    rows += _expand(EDUCATION, "Education", n=14)
    rows += _expand(TRAVEL, "Travel", n=14)
    rows += _expand(SALARY, "Salary", n=16)
    rows += _expand(TRANSFER, "Transfer", n=14)
    rows += _expand(INVESTMENTS, "Investments", n=12)
    rows += _expand(OTHER, "Other", n=10)

    # Dedupe while preserving order — light decorations occasionally collide.
    seen: set[tuple[str, str, str]] = set()
    unique: list[tuple[str, str, str]] = []
    for r in rows:
        if r not in seen:
            seen.add(r)
            unique.append(r)

    # Stable shuffle so the file order doesn't betray category boundaries.
    RNG.shuffle(unique)

    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CORPUS_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["description", "category", "merchant_base"])
        writer.writerows(unique)

    counts: dict[str, int] = {}
    merchants_per_cat: dict[str, set[str]] = {}
    for _desc, cat, base in unique:
        counts[cat] = counts.get(cat, 0) + 1
        merchants_per_cat.setdefault(cat, set()).add(base)

    print(f"Wrote {len(unique)} rows to {CORPUS_PATH.relative_to(CORPUS_PATH.parents[3])}")
    for cat in sorted(counts):
        print(f"  {cat:14s} {counts[cat]:4d} rows / {len(merchants_per_cat[cat]):3d} merchants")


if __name__ == "__main__":
    main()
