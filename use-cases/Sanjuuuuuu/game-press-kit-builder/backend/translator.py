"""
Deterministic translation layer for the Game Press Kit Builder.

The translation interface is deliberately isolated from the
localization/invariant logic so it can later be replaced with
an LLM or translation API without changing the rest of the system.
"""


SPANISH_TRANSLATIONS = {
    # ---------------------------------------------------------
    # Descriptions
    # ---------------------------------------------------------

    "Emberfall is an action-adventure RPG about a young firekeeper restoring ancient beacons across a ruined kingdom.":
        "Emberfall es un RPG de acción y aventura sobre una joven guardiana del fuego que restaura antiguos faros a través de un reino en ruinas.",

    "Emberfall is an action-adventure RPG about a young firekeeper crossing a ruined kingdom to restore ancient beacons and uncover the truth behind the fall of her homeland. Players explore a ruined fantasy kingdom, master fire-based abilities, restore ancient beacons, discover hidden lore, and customize their abilities through a flexible skill system.":
        "Emberfall es un RPG de acción y aventura sobre una joven guardiana del fuego que atraviesa un reino en ruinas para restaurar antiguos faros y descubrir la verdad detrás de la caída de su tierra natal. Los jugadores exploran un reino de fantasía en ruinas, dominan habilidades basadas en el fuego, restauran antiguos faros, descubren conocimientos ocultos y personalizan sus habilidades mediante un sistema de habilidades flexible.",

    "Emberfall is an action-adventure RPG about a young firekeeper crossing a ruined kingdom to restore ancient beacons and uncover the truth behind the fall of her homeland. Developed by Northstar Forge, Emberfall combines exploration, combat, environmental storytelling and character progression across a ruined fantasy kingdom. Players use fire-based abilities to overcome enemies and interact with the environment while restoring ancient beacons that reconnect the world. The game also includes optional ruins, journals and environmental storytelling for players interested in uncovering its history. A flexible skill system allows players to customize their abilities as they progress.":
        "Emberfall es un RPG de acción y aventura sobre una joven guardiana del fuego que atraviesa un reino en ruinas para restaurar antiguos faros y descubrir la verdad detrás de la caída de su tierra natal. Desarrollado por Northstar Forge, Emberfall combina exploración, combate, narrativa ambiental y progresión del personaje en un reino de fantasía en ruinas. Los jugadores utilizan habilidades basadas en el fuego para superar enemigos e interactuar con el entorno mientras restauran antiguos faros que vuelven a conectar el mundo. El juego también incluye ruinas opcionales, diarios y narrativa ambiental para quienes quieran descubrir su historia. Un sistema de habilidades flexible permite a los jugadores personalizar sus habilidades a medida que avanzan.",

    "Emberfall is an action-adventure RPG about a young firekeeper crossing a ruined kingdom to restore ancient beacons and uncover the truth behind the fall of her homeland. Players also explore a ruined fantasy kingdom connected by ancient beacon routes., and master fire-based combat abilities and combine them with environmental interactions., and restore ancient beacons to unlock new regions and fast-travel routes.":
        "Emberfall es un RPG de acción y aventura sobre una joven guardiana del fuego que atraviesa un reino en ruinas para restaurar antiguos faros y descubrir la verdad detrás de la caída de su tierra natal. Los jugadores también exploran un reino de fantasía en ruinas conectado por antiguas rutas de faros, dominan habilidades de combate basadas en el fuego y restauran antiguos faros para desbloquear nuevas regiones.",

    "Emberfall is an action-adventure RPG about a young firekeeper crossing a ruined kingdom to restore ancient beacons and uncover the truth behind the fall of her homeland. Developed by Northstar Forge, Emberfall is a action-adventure RPG. Emberfall began as a small prototype focused on fire-based exploration mechanics before expanding into a full action-adventure RPG. The team drew inspiration from illustrated fantasy novels, ruined medieval architecture and the feeling of exploring abandoned places. Key features include: Explore a ruined fantasy kingdom connected by ancient beacon routes. Master fire-based combat abilities and combine them with environmental interactions. Restore ancient beacons to unlock new regions and fast-travel routes. Discover hidden lore through optional ruins, journals and environmental storytelling. Customize abilities through a flexible skill system.":
        "Emberfall es un RPG de acción y aventura sobre una joven guardiana del fuego que atraviesa un reino en ruinas para restaurar antiguos faros y descubrir la verdad detrás de la caída de su tierra natal. Desarrollado por Northstar Forge, Emberfall es un RPG de acción y aventura. Emberfall comenzó como un pequeño prototipo centrado en mecánicas de exploración basadas en el fuego antes de convertirse en un RPG completo de acción y aventura. El equipo se inspiró en novelas de fantasía ilustradas, la arquitectura medieval en ruinas y la sensación de explorar lugares abandonados. Las características principales incluyen explorar un reino de fantasía en ruinas conectado por antiguas rutas de faros, dominar habilidades de combate basadas en el fuego, restaurar antiguos faros, descubrir conocimientos ocultos y personalizar habilidades mediante un sistema flexible.",

    "Emberfall is an action-adventure RPG about a young firekeeper crossing a ruined kingdom to restore ancient beacons and uncover the truth behind the fall of her homeland.":
        "Emberfall es un RPG de acción y aventura sobre una joven guardiana del fuego que atraviesa un reino en ruinas para restaurar antiguos faros y descubrir la verdad detrás de la caída de su tierra natal.",

    "Emberfall is an action-adventure RPG about a young firekeeper crossing a ruined kingdom to restore ancient beacons and uncover the truth behind the fall of her homeland. Key features include: Explore a ruined fantasy kingdom connected by ancient beacon routes. Master fire-based combat abilities and combine them with environmental interactions. Restore ancient beacons to unlock new regions and fast-travel routes.":
        "Emberfall es un RPG de acción y aventura sobre una joven guardiana del fuego que atraviesa un reino en ruinas para restaurar antiguos faros y descubrir la verdad detrás de la caída de su tierra natal. Las características principales incluyen explorar un reino de fantasía en ruinas conectado por antiguas rutas de faros, dominar habilidades de combate basadas en el fuego y restaurar antiguos faros para desbloquear nuevas regiones.",

    "Emberfall is an action-adventure RPG about a young firekeeper crossing a ruined kingdom to restore ancient beacons and uncover the truth behind the fall of her homeland. Developed by Northstar Forge, Emberfall is an Action-adventure RPG. Emberfall began as a small prototype focused on fire-based exploration mechanics before expanding into a full action-adventure RPG. The team drew inspiration from illustrated fantasy novels, ruined medieval architecture and the feeling of exploring abandoned places. Key features include: Explore a ruined fantasy kingdom connected by ancient beacon routes. Master fire-based combat abilities and combine them with environmental interactions. Restore ancient beacons to unlock new regions and fast-travel routes. Discover hidden lore through optional ruins, journals and environmental storytelling. Customize abilities through a flexible skill system.":
        "Emberfall es un RPG de acción y aventura sobre una joven guardiana del fuego que atraviesa un reino en ruinas para restaurar antiguos faros y descubrir la verdad detrás de la caída de su tierra natal. Desarrollado por Northstar Forge, Emberfall es un RPG de acción y aventura. Emberfall comenzó como un pequeño prototipo centrado en mecánicas de exploración basadas en el fuego antes de convertirse en un RPG completo de acción y aventura. El equipo se inspiró en novelas de fantasía ilustradas, la arquitectura medieval en ruinas y la sensación de explorar lugares abandonados. Las características principales incluyen explorar un reino de fantasía en ruinas conectado por antiguas rutas de faros, dominar habilidades de combate basadas en el fuego, restaurar antiguos faros, descubrir conocimientos ocultos y personalizar habilidades mediante un sistema flexible.",

    "Ashvale is a tactical adventure about a courier crossing a storm-scarred valley to reconnect isolated settlements.":
        "Ashvale es una aventura táctica sobre un mensajero que atraviesa un valle marcado por tormentas para reconectar asentamientos aislados.",
    "Ashvale is a tactical adventure about a courier crossing a storm-scarred valley to reconnect isolated settlements. Key features include: Navigate a storm-scarred valley connected by old trade roads. Plan encounters around weather and terrain. Reconnect settlements by restoring damaged relay towers.":
        "Ashvale es una aventura táctica sobre un mensajero que atraviesa un valle marcado por tormentas para reconectar asentamientos aislados. Las características principales incluyen navegar por un valle marcado por tormentas conectado por antiguas rutas comerciales, planificar encuentros según el clima y el terreno, y reconectar asentamientos restaurando torres de comunicación dañadas.",
    "Ashvale is a tactical adventure about a courier crossing a storm-scarred valley to reconnect isolated settlements. Developed by Copper Lantern, Ashvale is a Tactical adventure. Ashvale began as a prototype about route planning before expanding into a tactical adventure. The team drew inspiration from mountain trade routes, travel journals and changing weather. Key features include: Navigate a storm-scarred valley connected by old trade roads. Plan encounters around weather and terrain. Reconnect settlements by restoring damaged relay towers. Discover local stories through letters and abandoned camps. Customize the courier's route and equipment.":
        "Ashvale es una aventura táctica sobre un mensajero que atraviesa un valle marcado por tormentas para reconectar asentamientos aislados. Desarrollado por Copper Lantern, Ashvale es una aventura táctica. Ashvale comenzó como un prototipo sobre planificación de rutas antes de convertirse en una aventura táctica. El equipo se inspiró en rutas comerciales de montaña, diarios de viaje y cambios meteorológicos. Las características principales incluyen navegar por un valle marcado por tormentas, planificar encuentros según el clima y el terreno, reconectar asentamientos, descubrir historias locales y personalizar la ruta y el equipo del mensajero.",
    "Navigate a storm-scarred valley connected by old trade roads.": "Navega por un valle marcado por tormentas conectado por antiguas rutas comerciales.",
    "Plan encounters around weather and terrain.": "Planifica encuentros según el clima y el terreno.",
    "Reconnect settlements by restoring damaged relay towers.": "Reconecta asentamientos restaurando torres de comunicación dañadas.",
    "Discover local stories through letters and abandoned camps.": "Descubre historias locales mediante cartas y campamentos abandonados.",
    "Customize the courier's route and equipment.": "Personaliza la ruta y el equipo del mensajero.",
    "Ashvale began as a prototype about route planning before expanding into a tactical adventure.": "Ashvale comenzó como un prototipo sobre planificación de rutas antes de convertirse en una aventura táctica.",
    "The team drew inspiration from mountain trade routes, travel journals and changing weather.": "El equipo se inspiró en rutas comerciales de montaña, diarios de viaje y cambios meteorológicos.",

    # ---------------------------------------------------------
    # Features
    # ---------------------------------------------------------

    "Explore a ruined fantasy kingdom connected by ancient beacon routes.":
        "Explora un reino de fantasía en ruinas conectado por antiguas rutas de faros.",

    "Master fire-based combat abilities and combine them with environmental interactions.":
        "Domina habilidades de combate basadas en el fuego y combínalas con interacciones ambientales.",

    "Restore ancient beacons to unlock new regions and fast-travel routes.":
        "Restaura antiguos faros para desbloquear nuevas regiones y rutas de viaje rápido.",

    "Discover hidden lore through optional ruins, journals and environmental storytelling.":
        "Descubre conocimientos ocultos mediante ruinas opcionales, diarios y narrativa ambiental.",

    "Customize abilities through a flexible skill system.":
        "Personaliza tus habilidades mediante un sistema de habilidades flexible.",

    # ---------------------------------------------------------
    # History and inspiration
    # ---------------------------------------------------------

    "Emberfall began as a small prototype focused on fire-based exploration mechanics before expanding into a full action-adventure RPG.":
        "Emberfall comenzó como un pequeño prototipo centrado en mecánicas de exploración basadas en el fuego antes de convertirse en un RPG completo de acción y aventura.",

    "The team drew inspiration from illustrated fantasy novels, ruined medieval architecture and the feeling of exploring abandoned places.":
        "El equipo se inspiró en novelas de fantasía ilustradas, la arquitectura medieval en ruinas y la sensación de explorar lugares abandonados.",
}


def translate_text(
    text: str,
    language: str,
) -> str:
    """
    Translate narrative text.

    Currently supports Spanish using a deterministic
    translation dictionary.

    This interface can later be replaced by an LLM
    without changing the localization pipeline.
    """

    if language.lower() != "spanish":
        raise ValueError(
            f"Unsupported language: {language}"
        )

    if text not in SPANISH_TRANSLATIONS:
        raise ValueError(
            f"No verified {language} translation exists for the supplied narrative text."
        )
    return SPANISH_TRANSLATIONS[text]


def translate_features(
    features: list[str],
    language: str,
) -> list[str]:
    """
    Translate feature descriptions.
    """

    return [
        translate_text(feature, language)
        for feature in features
    ]


def translate_descriptions(
    descriptions: dict,
    language: str,
) -> dict:
    """
    Translate all three required description lengths.
    """

    return {
        "one_line": translate_text(
            descriptions["one_line"],
            language,
        ),
        "one_paragraph": translate_text(
            descriptions["one_paragraph"],
            language,
        ),
        "long_form": translate_text(
            descriptions["long_form"],
            language,
        ),
    }


def translate_history(
    history: dict,
    language: str,
) -> dict:
    """
    Translate history and inspiration.
    """

    return {
        "history": translate_text(
            history["history"],
            language,
        ),
        "inspiration": translate_text(
            history["inspiration"],
            language,
        ),
    }