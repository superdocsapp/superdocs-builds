import json

with open('data/properties/haveli-jaipur-demo.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

data['id'] = 'haveli-jaipur-demo'
data['name'] = 'Haveli Jaipur Demo'
data['address_lines'] = ['Plot No 4, Civil Lines', 'Jaipur 302006, Rajasthan', 'India']
data['contact_name'] = 'Rahul Sharma'
data['contact_email'] = 'rahul@havelistays.example'
data['contact_phone'] = '+91 98765 43210'

# Update summary
data['listing']['summary']['$i18n']['en'] = 'Haveli Jaipur is a restored 1920s heritage home in the heart of the Pink City — sandstone walls, intricate jharokhas, and a rooftop view over the Aravalli hills. Three bedrooms, a shaded courtyard, and breakfast on the terrace: the royal Rajasthan you came for.'
data['listing']['summary']['$i18n']['es'] = 'Haveli Jaipur es una casa patrimonial restaurada de la década de 1920 en el corazón de la Ciudad Rosa: paredes de arenisca, intrincados jharokhas y una vista desde la azotea de las colinas de Aravalli.'
data['listing']['summary']['$i18n']['fr'] = 'Haveli Jaipur est une maison du patrimoine restaurée des années 1920 au coeur de la ville rose — murs en grès, jharokhas complexes et vue sur les collines des Aravalli.'

# Update space
data['listing']['space']['$i18n']['en'] = 'Two floors of calm: a double-height living room with traditional arches, a modern kitchen, and three bedrooms (two doubles, one twin) served by two renovated bathrooms.'
data['listing']['space']['$i18n']['es'] = 'Dos plantas tranquilas: un salón de doble altura con arcos tradicionales, una cocina moderna y tres dormitorios (dos dobles, uno con dos camas) con dos baños renovados.'
data['listing']['space']['$i18n']['fr'] = 'Deux étages de calme : un salon à double hauteur avec des arches traditionnelles, une cuisine moderne et trois chambres (deux doubles, une à lits jumeaux) avec deux salles de bains rénovées.'

# Update tagline
data['tagline']['$i18n']['en'] = 'A sun-washed heritage home, ninety seconds from the local bazaar'
data['tagline']['$i18n']['es'] = 'Una casa patrimonial bañada por el sol, a noventa segundos del bazar local'
data['tagline']['$i18n']['fr'] = 'Une maison du patrimoine baignée de soleil, à quatre-vingt-dix secondes du bazar local'

# Update neighborhood
data['listing']['neighborhood']['$i18n']['en'] = "You're 90 seconds from the vibrant local bazaars: spices, handicrafts, and the best kachoris in town."
data['listing']['neighborhood']['$i18n']['es'] = 'Estás a 90 segundos de los vibrantes bazares locales: especias, artesanías y los mejores kachoris de la ciudad.'
data['listing']['neighborhood']['$i18n']['fr'] = 'Vous êtes à 90 secondes des bazars locaux animés : épices, artisanat et les meilleurs kachoris de la ville.'

# Update transit
data['listing']['transit']['$i18n']['en'] = 'Jaipur airport is 30 minutes by car. E-rickshaws and cabs are readily available; the metro is a short walk away.'
data['listing']['transit']['$i18n']['es'] = 'El aeropuerto de Jaipur está a 30 minutos en coche. Hay rickshaws electrónicos y taxis disponibles; el metro está a un corto paseo.'
data['listing']['transit']['$i18n']['fr'] = "L'aéroport de Jaipur est à 30 minutes en voiture. Des e-rickshaws et des taxis sont facilement disponibles ; le métro est à quelques pas."

with open('data/properties/haveli-jaipur-demo.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
