# Clés copiées telles quelles dans app.config : c'est ici que se configurent les extensions Flask.
config = {
    # Cookie de session non envoyé par les requêtes POST venues d'autres sites (avec le CSRF).
    "SESSION_COOKIE_SAMESITE": "Lax",
    # Âge maximal (en secondes) d'un cookie de session accepté, défaut Flask : 31 jours.
    # Un cookie copié reste valide jusque-là, même après logout : raccourcissez si besoin.
    # "PERMANENT_SESSION_LIFETIME": 60 * 60 * 24 * 7,
}
