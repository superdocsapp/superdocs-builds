"""Realistic, deterministic mock data for Task 2A.

``load_mock_catalog`` returns a fresh catalog each time so examples and tests
can safely mutate a shared block without leaking state to another run.
"""

from __future__ import annotations

from pathlib import Path

from models import (
    Appliance,
    LocalRecommendation,
    MapDiagram,
    Photo,
    Property,
    PropertyCatalog,
    SharedBlock,
)


ASSETS_DIR = Path(__file__).parent / "assets"


def _shared_blocks() -> dict[str, SharedBlock]:
    return {
        "quiet-hours": SharedBlock(
            id="quiet-hours",
            block_type="house_rule",
            title="Quiet hours",
            content="Quiet hours are from 10 PM to 7 AM. Please keep music, TV, and conversations low during this time.",
            language_variants={
                "kn": {
                    "title": "ನಿಶ್ಯಬ್ದ ಸಮಯ",
                    "content": "ನಿಶ್ಯಬ್ದ ಸಮಯವು ರಾತ್ರಿ 10 ರಿಂದ ಬೆಳಿಗ್ಗೆ 7 ರವರೆಗೆ ಇರುತ್ತದೆ. ಈ ಸಮಯದಲ್ಲಿ ಸಂಗೀತ, ಟಿವಿ ಮತ್ತು ಸಂಭಾಷಣೆಯ ಧ್ವನಿಯನ್ನು ಕಡಿಮೆ ಇಡಿ.",
                }
            },
        ),
        "no-smoking": SharedBlock(
            id="no-smoking",
            block_type="house_rule",
            title="No smoking",
            content="Smoking and vaping are not permitted anywhere inside the property.",
            language_variants={
                "kn": {
                    "title": "ಧೂಮಪಾನ ನಿಷೇಧ",
                    "content": "ಮನೆಯ ಒಳಗೆ ಎಲ್ಲಿಯೂ ಧೂಮಪಾನ ಅಥವಾ ವೇಪಿಂಗ್‌ಗೆ ಅನುಮತಿ ಇಲ್ಲ.",
                }
            },
        ),
        "no-parties": SharedBlock(
            id="no-parties",
            block_type="house_rule",
            title="No parties or events",
            content="Parties, events, and unregistered visitors are not permitted.",
            language_variants={
                "kn": {
                    "title": "ಪಾರ್ಟಿ ಅಥವಾ ಕಾರ್ಯಕ್ರಮಗಳಿಲ್ಲ",
                    "content": "ಪಾರ್ಟಿಗಳು, ಕಾರ್ಯಕ್ರಮಗಳು ಮತ್ತು ನೋಂದಾಯಿಸದ ಸಂದರ್ಶಕರಿಗೆ ಅನುಮತಿ ಇಲ್ಲ.",
                }
            },
        ),
        "checkout-policy": SharedBlock(
            id="checkout-policy",
            block_type="checkout_policy",
            title="Check-out policy",
            content="Please check out by 11 AM, switch off appliances, place keys on the entry table, and send the manager a short confirmation message.",
            language_variants={
                "kn": {
                    "title": "ಚೆಕ್-ಔಟ್ ನಿಯಮ",
                    "content": "ಬೆಳಿಗ್ಗೆ 11 ಗಂಟೆಯೊಳಗೆ ಚೆಕ್-ಔಟ್ ಮಾಡಿ, ಉಪಕರಣಗಳನ್ನು ಆಫ್ ಮಾಡಿ, ಕೀಲಿಗಳನ್ನು ಪ್ರವೇಶದ ಮೇಜಿನ ಮೇಲೆ ಇರಿಸಿ ಮತ್ತು ವ್ಯವಸ್ಥಾಪಕರಿಗೆ ದೃಢೀಕರಣ ಸಂದೇಶ ಕಳುಹಿಸಿ.",
                }
            },
        ),
        "emergency-procedure": SharedBlock(
            id="emergency-procedure",
            block_type="emergency_procedure",
            title="Emergency procedure",
            content="For an immediate emergency call 112 first, then contact the property manager when it is safe to do so.",
            language_variants={
                "kn": {
                    "title": "ತುರ್ತು ಕ್ರಮ",
                    "content": "ತಕ್ಷಣದ ತುರ್ತು ಪರಿಸ್ಥಿತಿಯಲ್ಲಿ ಮೊದಲು 112 ಗೆ ಕರೆ ಮಾಡಿ; ಸುರಕ್ಷಿತವಾದಾಗ ಆಸ್ತಿ ವ್ಯವಸ್ಥಾಪಕರನ್ನು ಸಂಪರ್ಕಿಸಿ.",
                }
            },
        ),
    }


def _green_residency() -> Property:
    asset_dir = ASSETS_DIR / "green_residency"
    return Property(
        id="green",
        name="Green Residency",
        unit="Flat 302",
        address="Indiranagar, Bangalore, Karnataka",
        property_type="2-bedroom apartment",
        bedrooms=2,
        bathrooms=2,
        maximum_guests=4,
        check_in="2 PM",
        check_out="11 AM",
        access_instructions="Use the main gate keypad code sent on the day of arrival. Take the lift to the third floor; Flat 302 is the second door on the left.",
        wifi_network="GreenGuest",
        wifi_password="TEST-NEW-PASSWORD",
        appliances=[
            Appliance("Air conditioner", "Use the white remote beside the bed. Set it to Cool mode and keep doors and windows closed.", {"kn": {"name": "ಏರ್ ಕಂಡೀಷನರ್", "instructions": "ಹಾಸಿಗೆಯ ಪಕ್ಕದಲ್ಲಿರುವ ಬಿಳಿ ರಿಮೋಟ್ ಬಳಸಿ. ಕೂಲ್ ಮೋಡ್ ಆಯ್ಕೆಮಾಡಿ ಮತ್ತು ಬಾಗಿಲು-ಕಿಟಕಿಗಳನ್ನು ಮುಚ್ಚಿಡಿ."}}),
            Appliance("Washing machine", "Use liquid detergent only. Select the Quick Wash cycle for small loads and leave the door ajar after use.", {"kn": {"name": "ವಾಷಿಂಗ್ ಮೆಷಿನ್", "instructions": "ದ್ರವ ಡಿಟರ್ಜೆಂಟ್ ಮಾತ್ರ ಬಳಸಿ. ಸಣ್ಣ ಲೋಡ್‌ಗಳಿಗೆ ಕ್ವಿಕ್ ವಾಶ್ ಆಯ್ಕೆಮಾಡಿ ಮತ್ತು ಬಳಕೆಯ ನಂತರ ಬಾಗಿಲನ್ನು ಸ್ವಲ್ಪ ತೆರೆದಿಡಿ."}}),
            Appliance("Refrigerator", "The refrigerator is always on. Please keep the freezer door fully closed.", {"kn": {"name": "ರೆಫ್ರಿಜರೇಟರ್", "instructions": "ರೆಫ್ರಿಜರೇಟರ್ ಸದಾ ಚಾಲನೆಯಲ್ಲಿರುತ್ತದೆ. ಫ್ರೀಜರ್ ಬಾಗಿಲನ್ನು ಸಂಪೂರ್ಣವಾಗಿ ಮುಚ್ಚಿಡಿ."}}),
            Appliance("Microwave", "Use microwave-safe containers only and never operate the microwave empty.", {"kn": {"name": "ಮೈಕ್ರೋವೇವ್", "instructions": "ಮೈಕ್ರೋವೇವ್‌ಗೆ ಸುರಕ್ಷಿತ ಪಾತ್ರೆಗಳನ್ನು ಮಾತ್ರ ಬಳಸಿ; ಖಾಲಿಯಾಗಿ ಎಂದಿಗೂ ಚಾಲನೆ ಮಾಡಬೇಡಿ."}}),
            Appliance("TV", "Press the Home button on the remote to open streaming apps. Please sign out of personal accounts before checkout.", {"kn": {"name": "ಟಿವಿ", "instructions": "ಸ್ಟ್ರೀಮಿಂಗ್ ಆ್ಯಪ್‌ಗಳಿಗಾಗಿ ರಿಮೋಟ್‌ನ ಹೋಮ್ ಬಟನ್ ಒತ್ತಿ. ಚೆಕ್-ಔಟ್‌ಗೆ ಮೊದಲು ವೈಯಕ್ತಿಕ ಖಾತೆಗಳಿಂದ ಸೈನ್ ಔಟ್ ಮಾಡಿ."}}),
            Appliance("Water heater", "Switch it on 10 minutes before use, then switch it off after bathing.", {"kn": {"name": "ವಾಟರ್ ಹೀಟರ್", "instructions": "ಬಳಕೆಗೆ 10 ನಿಮಿಷ ಮೊದಲು ಆನ್ ಮಾಡಿ; ಸ್ನಾನದ ನಂತರ ಆಫ್ ಮಾಡಿ."}}),
        ],
        local_recommendations=[
            LocalRecommendation("Restaurant", "Nagarjuna", "Classic Andhra meals and biryani.", "550 m", {"kn": {"category": "ಉಪಹಾರ ಗೃಹ", "description": "ಸಾಂಪ್ರದಾಯಿಕ ಆಂಧ್ರ ಊಟ ಮತ್ತು ಬಿರಿಯಾನಿ."}}),
            LocalRecommendation("Grocery", "Nature's Basket", "Convenient groceries and essentials.", "350 m", {"kn": {"category": "ದಿನಸಿ ಅಂಗಡಿ", "description": "ಅನುಕೂಲಕರ ದಿನಸಿ ಮತ್ತು ಅಗತ್ಯ ವಸ್ತುಗಳು."}}),
            LocalRecommendation("Pharmacy", "Apollo Pharmacy", "Late-evening pharmacy and basic health supplies.", "400 m", {"kn": {"category": "ಔಷಧ ಅಂಗಡಿ", "description": "ತಡ ಸಂಜೆಯವರೆಗೆ ಔಷಧಿ ಮತ್ತು ಮೂಲ ಆರೋಗ್ಯ ಸಾಮಗ್ರಿಗಳು."}}),
            LocalRecommendation("Metro", "Indiranagar Metro Station", "Fast connection to MG Road and central Bangalore.", "700 m", {"kn": {"category": "ಮೆಟ್ರೋ", "description": "ಎಂ.ಜಿ. ರಸ್ತೆ ಮತ್ತು ಮಧ್ಯ ಬೆಂಗಳೂರಿಗೆ ವೇಗದ ಸಂಪರ್ಕ."}}),
            LocalRecommendation("Attraction", "Cubbon Park", "A peaceful urban park, ideal for a morning walk.", "5 km", {"kn": {"category": "ಪ್ರೇಕ್ಷಣೀಯ ಸ್ಥಳ", "description": "ಬೆಳಗಿನ ನಡಿಗೆಗೆ ಸೂಕ್ತವಾದ ಶಾಂತ ನಗರ ಉದ್ಯಾನ."}}),
        ],
        emergency_information={
            "emergency_number": "112",
            "property_manager": "Ananya Rao: +91 98765 43210",
            "hospital": "Manipal Hospital, Old Airport Road: +91 80 2502 4444",
        },
        photos=[
            Photo(asset_dir / "exterior.jpg", "Green Residency exterior", "Exterior of Green Residency"),
            Photo(asset_dir / "living_room.jpg", "Bright living room", "Living room seating area"),
            Photo(asset_dir / "bedroom_1.jpg", "Primary bedroom", "Primary bedroom with bed"),
            Photo(asset_dir / "kitchen.jpg", "Fully equipped kitchen", "Kitchen counter and appliances"),
            Photo(asset_dir / "bathroom.jpg", "Guest bathroom", "Clean bathroom with shower"),
        ],
        map_diagram=MapDiagram(asset_dir / "map_diagram.png", "Local wayfinding map", "Diagram showing Green Residency, metro, grocery, pharmacy, and hospital"),
        shared_block_ids=["quiet-hours", "no-smoking", "no-parties", "checkout-policy", "emergency-procedure"],
        language_variants={
            "kn": {
                "name": "ಗ್ರೀನ್ ರೆಸಿಡೆನ್ಸಿ",
                "property_type": "2 ಮಲಗುವ ಕೊಠಡಿಯ ಅಪಾರ್ಟ್‌ಮೆಂಟ್",
                "address": "ಇಂದಿರಾನಗರ, ಬೆಂಗಳೂರು, ಕರ್ನಾಟಕ",
                "unit": "ಫ್ಲಾಟ್ 302",
                "access_instructions": "ಆಗಮನದ ದಿನ ಕಳುಹಿಸುವ ಮುಖ್ಯ ಗೇಟ್ ಕೀಪ್ಯಾಡ್ ಕೋಡ್ ಬಳಸಿ. ಲಿಫ್ಟ್‌ನಲ್ಲಿ ಮೂರನೇ ಮಹಡಿಗೆ ಹೋಗಿ; ಫ್ಲಾಟ್ 302 ಎಡಭಾಗದ ಎರಡನೇ ಬಾಗಿಲು.",
                "welcome_message": "ನಿಮ್ಮ ವಾಸ್ತವ್ಯವನ್ನು ಆರಾಮದಾಯಕವಾಗಿಸಲು ನಾವು ಸಂತೋಷಪಡುತ್ತೇವೆ.",
                "emergency_information": {
                    "emergency_number": "112",
                    "property_manager": "ಅನನ್ಯಾ ರಾವ್: +91 98765 43210",
                    "hospital": "ಮಣಿಪಾಲ್ ಆಸ್ಪತ್ರೆ, ಓಲ್ಡ್ ಏರ್‌ಪೋರ್ಟ್ ರಸ್ತೆ: +91 80 2502 4444",
                },
            }
        },
    )


def _blue_residency() -> Property:
    asset_dir = ASSETS_DIR / "blue_residency"
    return Property(
        id="blue",
        name="Blue Residency",
        unit="Villa 14",
        address="Gokulam, Mysore, Karnataka",
        property_type="3-bedroom villa",
        bedrooms=3,
        bathrooms=3,
        maximum_guests=6,
        check_in="3 PM",
        check_out="11 AM",
        access_instructions="Enter through the blue side gate using the key-safe code sent before arrival. Villa 14 is at the end of the garden path; return keys to the safe at checkout.",
        wifi_network="BlueVillaNet",
        wifi_password="BLUE-STAY-2026",
        appliances=[
            Appliance("Air conditioner", "Use the remote in each bedroom and set it to 24°C for efficient cooling."),
            Appliance("Washing machine", "The machine is in the utility room. Use the Cotton cycle and do not overload it."),
            Appliance("Refrigerator", "Please use the labelled guest shelves in the refrigerator."),
            Appliance("Microwave", "Set the timer with the dial and use the Stop button before opening the door."),
            Appliance("TV", "Use the HDMI 1 input for the streaming stick; its remote is in the media drawer."),
            Appliance("Water heater", "Each bathroom heater has a red indicator light. Turn it off after use."),
        ],
        local_recommendations=[
            LocalRecommendation("Restaurant", "Vinayaka Mylari", "Well-known for soft dosas and South Indian breakfast.", "1.2 km"),
            LocalRecommendation("Grocery", "More Supermarket", "Everyday groceries and household supplies.", "800 m"),
            LocalRecommendation("Pharmacy", "MedPlus", "Pharmacy close to the main road.", "900 m"),
            LocalRecommendation("Metro", "Mysuru City Bus Stand", "Frequent local transport and city connections.", "2.5 km"),
            LocalRecommendation("Attraction", "Mysore Palace", "Historic palace with evening illumination on select days.", "3 km"),
        ],
        emergency_information={
            "emergency_number": "112",
            "property_manager": "Ravi Kumar: +91 99887 76655",
            "hospital": "Apollo BGS Hospitals, Kuvempunagar: +91 821 256 6666",
        },
        photos=[
            Photo(asset_dir / "exterior.jpg", "Blue Residency garden entrance", "Garden entrance of Blue Residency"),
            Photo(asset_dir / "living_room.jpg", "Villa living room", "Living room in Blue Residency"),
        ],
        map_diagram=MapDiagram(asset_dir / "map_diagram.png", "Local wayfinding map", "Diagram showing Blue Residency and nearby services"),
        shared_block_ids=["quiet-hours", "no-smoking", "no-parties", "checkout-policy", "emergency-procedure"],
        language_variants={
            "kn": {"name": "ಬ್ಲೂ ರೆಸಿಡೆನ್ಸಿ", "welcome_message": "ಮೈಸೂರಿನಲ್ಲಿ ನಿಮ್ಮ ವಾಸ್ತವ್ಯವನ್ನು ಆನಂದಿಸಿ."}
        },
    )


def load_mock_catalog() -> PropertyCatalog:
    """Return the two mock properties and their single shared-block registry."""
    return PropertyCatalog(
        properties={"green": _green_residency(), "blue": _blue_residency()},
        shared_blocks=_shared_blocks(),
    )
