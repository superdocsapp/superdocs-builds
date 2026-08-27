from __future__ import annotations

from .art import generate_all
from .models import FloorRoom, Photo, Property, SharedBlock, i18n
from .store import Store


def _t(*pairs: tuple[str, str]) -> dict:
    return i18n(*pairs)


def _build_blocks() -> list[SharedBlock]:
    blocks = [
        SharedBlock(
            id="blk-brand-haveli-stays", kind="brand", name="Haveli Stays Brand",
            description="Operator brand kit used by every manual.",
            content={
                "primary": "#0F766E", "accent": "#C2703D", "sand": "#F7F2EA",
                "ink": "#232A31", "muted": "#68717A",
                "operator_name": "Haveli Stays · Rajasthan",
                "logo_path": "assets/art/operator-logo.png",
            }),
        SharedBlock(
            id="blk-arrival-standard", kind="arrival", name="Standard Arrival",
            description="Warm welcome, generic access steps (codes live on each property).",
            content={
                "greeting": _t(("en", "Welcome! We are thrilled you are here."),
                               ("es", "¡Bienvenido! Estamos encantados de tenerte aquí."),
                               ("fr", "Bienvenue ! Nous sommes ravis de vous recevoir."),
                               ("de", "Willkommen! Wir freuen uns sehr, dass Sie da sind."),
                               ("it", "Benvenuto! Siamo felici di averti qui."),
                               ("pt", "Bem-vindo! Estamos muito contentes por ter consigo."),
                               ("nl", "Welkom! Wat leuk dat u er bent.")),
                "checkin_time": "16:00",
                "checkout_time": "11:00",
                "key_location": _t(
                    ("en", "Your key is in the brass lock box by the entrance. The code is set per stay — see your check-in message."),
                    ("es", "La llave está en la caja fuerte dorada junto a la entrada. El código cambia con cada reserva — mira tu mensaje de check-in."),
                    ("fr", "La clé se trouve dans la boîte à clés laiton près de l'entrée. Le code change à chaque séjour — voir votre message d'arrivée.")),
                "parking": _t(
                    ("en", "Free parking inside the gated driveway; additional visitor parking available on the lane."),
                    ("es", "Aparcamiento gratuito en la entrada cerrada; aparcamiento adicional para visitantes disponible en la calle."),
                    ("fr", "Stationnement gratuit dans l'allée fermée ; stationnement supplémentaire pour les visiteurs dans la rue.")),
                "steps": [
                    _t(("en", "Walk through the carved wooden gate into the central courtyard."),
                       ("es", "Cruce la puerta de madera tallada hacia el patio central."),
                       ("fr", "Passez la porte en bois sculpté menant à la cour centrale.")),
                    _t(("en", "Take the key from the brass lock box and keep it with you."),
                       ("es", "Tome la llave de la caja de latón y llévela consigo."),
                       ("fr", "Prenez la clé dans la boîte en laiton et gardez-la avec vous.")),
                    _t(("en", "Head to the main suite on the first floor."),
                       ("es", "Diríjase a la suite principal en el primer piso."),
                       ("fr", "Rendez-vous à la suite principale au premier étage.")),
                    _t(("en", "Make yourself a fresh masala chai or coffee; the machine is ready."),
                       ("es", "Prepárese un té chai o café recién hecho; la máquina está lista."),
                       ("fr", "Préparez-vous un thé chai ou un café frais ; la machine est prête.")),
                ],
            }),
        SharedBlock(
            id="blk-wifi-fibre", kind="wifi", name="Fibre WiFi Guide",
            description="Connection instructions shared by all properties "
                        "(SSID/password are property overrides).",
            content={
                "qr": True,
                "instructions": _t(
                    ("en", "Our fibre line reaches every room. Join the guest network shown below — no login page, just the password."),
                    ("es", "Nuestra fibra llega a todas las habitaciones. Únase a la red de invitados indicada abajo: sin página de inicio de sesión, solo la contraseña."),
                    ("fr", "Notre fibre couvre toutes les pièces. Rejoignez le réseau invité indiqué ci-dessous — pas de portail, juste le mot de passe."),
                    ("de", "Unser Glasfaseranschluss erreicht jeden Raum. Verbinden Sie sich mit dem unten angezeigten Gastnetzwerk – kein Login, nur das Passwort."),
                    ("nl", "Ons glasvezelnetwerk bereikt elke kamer. Maak verbinding met het gastennetwerk hieronder – geen inlogpagina, alleen het wachtwoord.")),
                "tips": [
                    _t(("en", "The router lives in the living-room shelf. A quick reboot fixes almost everything."),
                       ("es", "El router está en la estantería del salón. Un reinicio rápido casi siempre lo soluciona."),
                       ("fr", "La box se trouve sur l'étagère du salon. Un redémarrage suffit presque toujours.")),
                    _t(("en", "Streaming, video calls and remote work are all comfortably supported."),
                       ("es", "Streaming, videollamadas y teletrabajo funcionan sin problemas."),
                       ("fr", "Streaming, appels vidéo et télétravail fonctionnent parfaitement.")),
                ],
            }),
        SharedBlock(
            id="blk-appliances-standard", kind="appliances", name="Appliance Basics",
            description="Numbered how-tos for the standard amenity set.",
            content={
                "intro": _t(
                    ("en", "Everything here works the way you'd hope. Short guides for the few things that like being asked nicely."),
                    ("es", "Todo funciona como esperas. Guías breves para las pocas cosas que piden un poco de mimo."),
                    ("fr", "Tout fonctionne simplement. Petits guides pour les quelques appareils qui méritent qu'on les chérisse.")),
                "items": [
                    {"name": _t(("en", "Espresso machine"), ("es", "Cafetera espresso"),
                                ("fr", "Machine à espresso")),
                     "steps": [
                         _t(("en", "Fill the tank at the back with fresh water."),
                            ("es", "Llene el depósito trasero con agua fresca."),
                            ("fr", "Remplissez le réservoir arrière d'eau fraîche.")),
                         _t(("en", "Drop a capsule in the top slot, lever down."),
                            ("es", "Inserte una cápsula arriba y baje la palanca."),
                            ("fr", "Insérez une capsule dessus et abaissez le levier.")),
                         _t(("en", "Press the small cup button; ready in 25 seconds."),
                            ("es", "Pulse el botón de taza pequeña; lista en 25 segundos."),
                            ("fr", "Appuyez sur le petit bouton tasse ; prête en 25 secondes."))]},
                    {"name": _t(("en", "Dishwasher"), ("es", "Lavavajillas"),
                                ("fr", "Lave-vaisselle")),
                     "steps": [
                         _t(("en", "Twist the salt cap under the sink once a month."),
                            ("es", "Rellene la sal bajo el fregadero una vez al mes."),
                            ("fr", "Vérifiez le sel sous l'évier une fois par mois.")),
                         _t(("en", "Tablets go in the little door inside."),
                            ("es", "La pastilla va en la compuerta interior."),
                            ("fr", "La pastille se place dans le compartiment intérieur.")),
                         _t(("en", "Choose Eco, press Start, close the door twice."),
                            ("es", "Elija Eco, pulse Inicio y cierre la puerta dos veces."),
                            ("fr", "Choisissez Eco, appuyez sur Start, fermez la porte deux fois."))]},
                    {"name": _t(("en", "Washing machine"), ("es", "Lavadora"),
                                ("fr", "Lave-linge")),
                     "steps": [
                         _t(("en", "Detergent drawer: left = wash, middle = softener."),
                            ("es", "Cajetín: izquierda = detergente, centro = suavizante."),
                            ("fr", "Tiroir : gauche = lessive, centre = adoucissant.")),
                         _t(("en", "Pick 40° Cottons for everyday loads."),
                            ("es", "Para el día a día, elija Algodones 40°."),
                            ("fr", "Pour l'usage courant : Coton 40°.")),
                         _t(("en", "Drying rack is on the terrace."),
                            ("es", "El tendedero está en la terraza."),
                            ("fr", "L'étendoir est sur la terrasse."))]},
                    {"name": _t(("en", "Induction hob"), ("es", "Placa de inducción"),
                                ("fr", "Plaque à induction")),
                     "steps": [
                         _t(("en", "Touch the power key, then a zone within 5 seconds."),
                            ("es", "Toque la tecla de encendido y luego una zona en 5 segundos."),
                            ("fr", "Touchez la touche marche puis une zone sous 5 secondes.")),
                         _t(("en", "Only pans that attract a magnet will heat."),
                            ("es", "Solo calientan los recipientes que atraigan un imán."),
                            ("fr", "Seuls les ustensiles attirés par un aimant chauffent.")),
                         _t(("en", "Hold power to lock when little chefs are around."),
                            ("es", "Mantenga pulsado el botón para bloquear si hay niños."),
                            ("fr", "Maintenez la touche pour verrouiller en présence d'enfants."))]},
                    {"name": _t(("en", "Air conditioning"), ("es", "Aire acondicionado"),
                                ("fr", "Climatisation")),
                     "steps": [
                         _t(("en", "Remote ON, then pick Snowflake for cooling."),
                            ("es", "ON en el mando y elija el copo de nieve para frío."),
                            ("fr", "ON sur la télécommande, puis choisissez le flocon.")),
                         _t(("en", "24°C keeps rooms cool without freezing anyone."),
                            ("es", "24 °C refresca sin helar a nadie."),
                            ("fr", "24 °C rafraîchit sans glacer personne.")),
                         _t(("en", "Please switch it off when you head out."),
                            ("es", "Apáguelo cuando salga. Gracias."),
                            ("fr", "Éteignez-le en sortant. Merci."))]},
                ],
            }),
        SharedBlock(
            id="blk-rules-warm-firm", kind="rules", name="House Rules — Warm but Firm",
            description="Friendly rules shared across the portfolio.",
            content={
                "note": _t(
                    ("en", "A handful of simple things keep this place lovely for you and the guests after you."),
                    ("es", "Unas pocas cosas sencillas mantienen esta casa preciosa para usted y para los próximos huéspedes."),
                    ("fr", "Quelques gestes simples gardent cette maison adorable pour vous comme pour les voyageurs suivants.")),
                "rules": [
                    {"title": _t(("en", "Respect the quiet hours"),
                                 ("es", "Respete el descanso del vecindario"),
                                 ("fr", "Respectez le calme du quartier")),
                     "detail": _t(("en", "The walls are heritage and the neighbours are friends."),
                                  ("es", "Los muros son patrimoniales y los vecinos, amigos."),
                                  ("fr", "Les murs sont historiques et les voisins sont des amis."))},
                    {"title": _t(("en", "No smoking indoors"),
                                 ("es", "No fumar dentro"),
                                 ("fr", "Ne pas fumer à l'intérieur")),
                     "detail": _t(("en", "The courtyard ashtray is your friend."),
                                  ("es", "El cenicero del patio es su amigo."),
                                  ("fr", "Le cendrier de la cour est votre ami."))},
                    {"title": _t(("en", "No parties or extra visitors"),
                                 ("es", "Sin fiestas ni visitas adicionales"),
                                 ("fr", "Pas de fêtes ni de visiteurs supplémentaires")),
                     "detail": _t(("en", "Registered guests only, please."),
                                  ("es", "Solo los huéspedes registrados, por favor."),
                                  ("fr", "Uniquement les voyageurs inscrits, merci."))},
                    {"title": _t(("en", "Sort your recycling"),
                                 ("es", "Separe el reciclaje"),
                                 ("fr", "Triez vos déchets")),
                     "detail": _t(("en", "Colour-coded bins are in the courtyard."),
                                  ("es", "Contenedores por colores en el patio."),
                                  ("fr", "Bacs colorés dans la cour."))},
                    {"title": _t(("en", "Leave it roughly as you found it"),
                                 ("es", "Déjela más o menos como la encontró"),
                                 ("fr", "Rendez le lieu à peu près comme vous l'avez trouvé")),
                     "detail": _t(("en", "Dishes in the machine and we handle the rest."),
                                  ("es", "Vajilla en el lavavajillas y nosotros nos ocupamos del resto."),
                                  ("fr", "La vaisselle au lave-vaisselle, on s'occupe du reste."))},
                ],
            }),
    ]

    recs = SharedBlock(
        id="blk-recs-jaipur-centre", kind="recommendations",
        name="Jaipur Pink City & Civil Lines Picks",
        description="Operator-curated neighbourhood guide (Jaipur Civil Lines & Pink City).",
        content={
            "note": _t(
                ("en", "All of these are a short ride or stroll away. Book dinners at heritage venues in advance — popular spots fill up fast."),
                ("es", "Todo está a poca distancia en coche o a pie. Reserve cenas en locales patrimoniales con antelación: los lugares populares se llenan rápido."),
                ("fr", "Tous ces lieux sont à une courte distance en voiture ou à pied. Réservez à l'avance dans les lieux historiques.")),
            "categories": [
                {"name": _t(("en", "Eat & drink"), ("es", "Comer y beber"),
                            ("fr", "Table & boissons")), "icon": "",
                 "places": [
                     {"name": "Laxmi Mishthan Bhandar (LMB)",
                      "desc": _t(("en", "Legendary Johari Bazaar eatery; must-try pyaaz kachori and ghewar."),
                                 ("es", "Emblemático local de Johari Bazaar; pruebe el pyaaz kachori y el ghewar."),
                                 ("fr", "Restaurant légendaire du Johari Bazaar ; goûtez au pyaaz kachori et au ghewar.")),
                      "walk": "12 min drive"},
                     {"name": "Baradari Restaurant",
                      "desc": _t(("en", "Contemporary fine dining inside City Palace with stunning courtyards."),
                                 ("es", "Alta cocina contemporánea dentro del City Palace en un hermoso patio."),
                                 ("fr", "Cuisine raffinée au sein du City Palace dans une superbe cour.")),
                      "walk": "15 min drive"},
                     {"name": "Handi Restaurant",
                      "desc": _t(("en", "Renowned North Indian and Mughlai grills on MI Road."),
                                 ("es", "Famosas parrilladas del norte de la India y mogol en MI Road."),
                                 ("fr", "Grillades réputées du nord de l'Inde et mogholes sur MI Road.")),
                      "walk": "8 min drive"},
                     {"name": "Curious Life Coffee Roasters",
                      "desc": _t(("en", "Speciality coffee, artisan brews, and fresh breakfast."),
                                 ("es", "Café de especialidad, bebidas artesanales y desayuno fresco."),
                                 ("fr", "Café de spécialité, boissons artisanales et petit-déjeuner frais.")),
                      "walk": "5 min drive"}]},
                {"name": _t(("en", "Essentials"), ("es", "Lo básico"),
                            ("fr", "Essentiels")), "icon": "",
                 "places": [
                     {"name": "Krishna Supermarket",
                      "desc": _t(("en", "Full grocery store open until 22:00."),
                                 ("es", "Supermercado completo abierto hasta las 22:00."),
                                 ("fr", "Supermarché complet ouvert jusqu'à 22h00.")),
                      "walk": "4 min"},
                     {"name": "Apollo Pharmacy",
                      "desc": _t(("en", "24-hour pharmacy with home delivery."),
                                 ("es", "Farmacia abierta 24 h con servicio a domicilio."),
                                 ("fr", "Pharmacie 24h/24 avec livraison à domicile.")),
                      "walk": "5 min"}]},
                {"name": _t(("en", "Hidden gems"), ("es", "Rincones secretos"),
                            ("fr", "Trésors cachés")), "icon": "",
                 "places": [
                     {"name": "Anokhi Museum of Hand Printing",
                      "desc": _t(("en", "Heritage textile museum inside a restored haveli."),
                                 ("es", "Museo textil patrimonial dentro de una haveli restaurada."),
                                 ("fr", "Musée du textile dans un haveli restauré.")),
                      "walk": "25 min drive"},
                     {"name": "Nahargarh Sunset Point",
                      "desc": _t(("en", "Breathtaking panoramic sunset views over Jaipur city."),
                                 ("es", "Vistas panorámicas impresionantes del atardecer sobre Jaipur."),
                                 ("fr", "Vue panoramique imprenable sur le coucher de soleil à Jaipur.")),
                      "walk": "20 min drive"}]},
                {"name": _t(("en", "Getting around"), ("es", "Transporte"),
                            ("fr", "Transports")), "icon": "",
                 "places": [
                     {"name": "Civil Lines Metro Station",
                      "desc": _t(("en", "Fast air-conditioned transit across Jaipur."),
                                 ("es", "Metro rápido con aire acondicionado por todo Jaipur."),
                                 ("fr", "Métro rapide et climatisé à travers Jaipur.")),
                      "walk": "6 min"},
                     {"name": "Auto & Cab Stand",
                      "desc": _t(("en", "Uber, Ola and e-rickshaws readily available 24/7."),
                                 ("es", "Uber, Ola y rickshaws electrónicos disponibles 24/7."),
                                 ("fr", "Uber, Ola et e-rickshaws disponibles 24h/24.")),
                      "walk": "2 min"}]},
            ],
        })
    blocks.append(recs)

    emergency = SharedBlock(
        id="blk-emergency-jaipur", kind="emergency",
        name="Emergency — Jaipur",
        description="Regional emergency contacts + shut-off guidance.",
        content={
            "number": "112",
            "contacts": [
                {"label": _t(("en", "Police (control room)"), ("es", "Policía"),
                             ("fr", "Police")), "value": "100"},
                {"label": _t(("en", "Fire brigade"), ("es", "Bomberos"),
                             ("fr", "Pompiers")), "value": "101"},
                {"label": _t(("en", "Ambulance / Medical"), ("es", "Ambulancia"),
                             ("fr", "Ambulance")), "value": "108"},
                {"label": _t(("en", "Out-of-hours host assistance"), ("es", "Asistencia al huésped 24 h"),
                             ("fr", "Assistance hôte 24h")), "value": "+91 98765 43210"},
            ],
            "shutoffs": {
                "gas": _t(("en", "Turn the knob on the LPG cylinder in the kitchen cabinet fully clockwise."),
                          ("es", "Gire el regulador de la bombona de gas en el mueble de la cocina a la derecha."),
                          ("fr", "Tournez le détendeur de la bouteille de gaz dans le placard de cuisine à fond à droite.")),
                "water": _t(("en", "Main valve in the courtyard utility shaft; rotate blue lever 90 degrees."),
                            ("es", "Válvula principal en la trampilla del patio; gire la palanca azul 90 grados."),
                            ("fr", "Vanne principale dans le regard de la cour ; tournez le levier bleu à 90 degrés.")),
                "electrics": _t(("en", "Main breaker panel behind the foyer door; trip the main black switch."),
                                ("es", "Cuadro eléctrico tras la puerta de entrada; baje el interruptor principal negro."),
                                ("fr", "Tableau électrique principal derrière la porte d'entrée ; abaissez le disjoncteur noir.")),
            },
        })
    blocks.append(emergency)
    return blocks


def _listing_content() -> dict:
    return {
        "summary": _t(
            ("en", "Haveli Jaipur is a restored 1920s heritage home in the heart of the Pink City — sandstone walls, intricate jharokhas, and a rooftop view over the Aravalli hills. Three bedrooms, a shaded courtyard, and breakfast on the terrace: the royal Rajasthan you came for."),
            ("es", "Haveli Jaipur es una casa patrimonial restaurada de la década de 1920 en el corazón de la Ciudad Rosa: paredes de arenisca, intrincados jharokhas y una vista desde la azotea de las colinas de Aravalli. Tres dormitorios, patio fresco y desayunos en la terraza."),
            ("fr", "Haveli Jaipur est une maison du patrimoine restaurée des années 1920 au coeur de la ville rose — murs en grès, jharokhas complexes et vue sur les collines des Aravalli depuis la terrasse. Trois chambres, une cour ombragée, le petit-déjeuner dehors.")),
        "space": _t(
            ("en", "Two floors of calm: a double-height living room with traditional arches, a modern kitchen, and three bedrooms (two doubles, one twin) served by two renovated bathrooms. Air conditioning throughout, blackout blinds everywhere."),
            ("es", "Dos plantas tranquilas: un salón de doble altura con arcos tradicionales, una cocina moderna y tres dormitorios (dos dobles, uno con dos camas) con dos baños renovados. Aire acondicionado en toda la casa y estores opacos."),
            ("fr", "Deux étages de calme : un salon à double hauteur avec des arches traditionnelles, une cuisine moderne et trois chambres (deux doubles, une à lits jumeaux) avec deux salles de bains rénovées. Climatisation partout et stores occultants.")),
        "guest_access": _t(
            ("en", "You have the whole haveli: rooftop terrace, central courtyard, and the outdoor lounge. Self check-in with digital access — codes are sent the morning of arrival."),
            ("es", "Toda la haveli es suya: terraza en la azotea, patio central y salón exterior. Auto-check-in con acceso digital: los códigos llegan la mañana de la llegada."),
            ("fr", "Tout le haveli est à vous : terrasse sur le toit, cour centrale et salon extérieur. Arrivée autonome par code numérique — codes envoyés le matin de l'arrivée.")),
        "neighborhood": _t(
            ("en", "You're 90 seconds from the vibrant local bazaars: spices, handicrafts, and the best kachoris in town. City Palace and Hawa Mahal are just minutes away."),
            ("es", "Está a 90 segundos de los vibrantes bazares locales: especias, artesanías y los mejores kachoris de la ciudad. El Palacio de la Ciudad y el Hawa Mahal están a pocos minutos."),
            ("fr", "Vous êtes à 90 secondes des bazars locaux animés : épices, artisanat et les meilleurs kachoris de la ville. Le City Palace et Hawa Mahal sont à quelques minutes.")),
        "transit": _t(
            ("en", "Jaipur International Airport is 25 minutes by car (pre-paid taxi / Uber ≈ ₹400). E-rickshaws and cabs are readily available; the metro is a short walk away."),
            ("es", "El aeropuerto internacional de Jaipur está a 25 minutos en coche (taxi prepago / Uber ≈ ₹400). Hay rickshaws electrónicos y taxis disponibles; el metro está a un corto paseo."),
            ("fr", "L'aéroport international de Jaipur est à 25 minutes en voiture (taxi prépayé / Uber ≈ 400 ₹). Des e-rickshaws et des taxis sont facilement disponibles ; le métro est à quelques pas.")),
        "selling_points": [
            _t(("en", "Steps from the vibrant bazaar yet whisper-quiet inside the courtyard"),
               ("es", "A pasos del animado bazar y, aun así, muy silencioso dentro del patio"),
               ("fr", "À deux pas du bazar animé, pourtant très calme à l'intérieur de la cour")),
            _t(("en", "Rooftop terrace built for evening tea and slow sunsets over the Aravalli hills"),
               ("es", "Azotea diseñada para tomar el té al atardecer y contemplar las colinas de Aravalli"),
               ("fr", "Terrasse sur le toit conçue pour le thé du soir et les couchers de soleil sur les collines d'Aravalli")),
            _t(("en", "Fast fibre WiFi, dedicated workspace, real coffee machine"),
               ("es", "WiFi de fibra rápida, zona de trabajo y buena cafetera"),
               ("fr", "Fibre rapide, espace de travail dédié, vraie machine à café")),
        ],
        "unique_features": [
            _t(("en", "Hand-carved Rajasthani sandstone jharokhas and restored antique doors"),
               ("es", "Jharokhas de arenisca rajastaní tallados a mano y puertas antiguas restauradas"),
               ("fr", "Jharokhas en grès du Rajasthan sculptés à la main et portes d'époque restaurées")),
            _t(("en", "Courtyard plunge pool and rooftop stargazing lounge"),
               ("es", "Piscina en el patio y zona de descanso en la azotea para observar las estrellas"),
               ("fr", "Bassin de détente dans la cour et salon sur le toit pour observer les étoiles")),
        ],
        "amenities": ["Fibre WiFi (600 Mbps)", "Air conditioning",
                      "Full kitchen + espresso machine", "Washer & dishwasher",
                      "Rooftop terrace", "Smart self check-in"],
    }


def seed_demo_data(store: Store, force: bool = False) -> str:
    """Create blocks + Haveli Jaipur; returns the property id."""
    if force:
        for bid in list(store.load_blocks()):
            store.delete_block(bid)
        for pid in list(store.load_properties()):
            store.delete_property(pid)

    for block in _build_blocks():
        store.save_block(block)

    art_files = generate_all("assets/art")

    prop = Property(
        id="haveli-jaipur-demo", name="Haveli Jaipur Demo",
        tagline=_t(("en", "A sun-washed heritage home, ninety seconds from the local bazaar"),
                   ("es", "Una casa patrimonial bañada por el sol, a noventa segundos del bazar local"),
                   ("fr", "Une maison du patrimoine baignée de soleil, à quatre-vingt-dix secondes du bazar local")),
        address_lines=["Plot No 4, Civil Lines", "Jaipur 302006, Rajasthan", "India"],
        contact_name="Rahul Sharma", contact_phone="+91 98765 43210",
        contact_email="rahul@havelistays.example",
        paper_size="A4", base_lang="en", languages=["en", "es", "fr"],
        listing=_listing_content(),
        floorplan_note=_t(("en", "Ground floor shown; rooftop terrace sits above bedroom 1."),
                          ("es", "Se muestra la planta baja; la azotea está sobre el dormitorio 1."),
                          ("fr", "Rez-de-chaussée ; la terrasse domine la chambre 1.")))

    # ---- links to shared library -------------------------------------------
    prop.link_block("brand", "blk-brand-haveli-stays")
    prop.link_block("arrival", "blk-arrival-standard")
    prop.link_block("wifi", "blk-wifi-fibre")
    prop.link_block("appliances", "blk-appliances-standard")
    prop.link_block("rules", "blk-rules-warm-firm")
    prop.link_block("recommendations", "blk-recs-jaipur-centre")
    prop.link_block("emergency", "blk-emergency-jaipur")

    # ---- property-specific facts as OVERRIDES ------------------------------
    prop.set_override("wifi", {
        "ssid": "HaveliJaipur_Guest",
        "password": "haveli-jaipur-2026",
    })
    prop.set_override("arrival", {
        "door_code": "19#20",
        "checkout_time": "11:00",
    })
    prop.set_override("emergency", {
        "hospital": {
            "name": "Fortis Escorts Hospital",
            "address": "Jawaharlal Nehru Marg, Malviya Nagar, Jaipur",
            "phone": "+91 141 254 7000",
            "_note": "24h emergency and trauma centre",
        },
    })

    captions = {
        "cover-exterior": _t(("en", "Golden hour in Civil Lines"),
                             ("es", "Hora dorada en Civil Lines"),
                             ("fr", "Heure dorée à Civil Lines")),
        "living-room": _t(("en", "The double-height heritage living room"),
                          ("es", "El salón patrimonial de doble altura"),
                          ("fr", "Le séjour patrimonial cathédrale")),
        "kitchen": _t(("en", "Cook's kitchen, induction ready"),
                      ("es", "Cocina de verdad, inducción lista"),
                      ("fr", "Vraie cuisine, plaque à induction")),
        "master-bedroom": _t(("en", "Bedroom 1 with carved wood finishes"),
                             ("es", "Dormitorio 1 con acabados en madera tallada"),
                             ("fr", "Chambre 1 avec finitions en bois sculpté")),
        "pool-deck": _t(("en", "Courtyard plunge pool"),
                        ("es", "Piscina en el patio"),
                        ("fr", "Bassin de détente dans la cour")),
    }
    section_map = {
        "cover-exterior": "cover", "living-room": "living", "kitchen": "kitchen",
        "master-bedroom": "bedroom", "pool-deck": "pool",
    }
    for name, path in art_files.items():
        if name == "logo":
            continue
        prop.photos.append(Photo(
            id=f"ph-{name}", section=section_map[name],
            caption=captions.get(name, {}), local_path=path,
            alt=name.replace("-", " ")))

    prop.floorplan = [
        FloorRoom("living", 0, 0, 5.2, 4.0),
        FloorRoom("kitchen", 5.2, 0, 3.4, 4.0),
        FloorRoom("terrace", 8.6, 0, 2.6, 4.0),
        FloorRoom("bedroom1", 0, 4.0, 4.2, 3.4),
        FloorRoom("bathroom", 4.2, 4.0, 2.2, 3.4),
        FloorRoom("bedroom2", 6.4, 4.0, 4.8, 3.4),
    ]

    store.create_property(prop)
    return prop.id
