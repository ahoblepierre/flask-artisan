"""Tâches planifiées, lancées par `flask schedule:run` (cron, chaque minute) ou `flask schedule:work`.

Ce fichier n'est chargé que par les commandes schedule:*, jamais par l'app web.
"""

from flask_artisan import Schedule

# Supprime les entrées expirées du cache, dont les compteurs de limitation laissés par chaque
# adresse IP (sans elle, le store `file` grossit sans fin).
Schedule.command("cache:prune").hourly()

# Une commande flask (celles du framework ou de app/console/commands/) :
# Schedule.command("cache:clear").daily_at("03:00")

# Un job, envoyé dans la queue (recommandé pour un travail long) :
# from app.jobs.send_report import SendReport
# Schedule.job(SendReport(), queue="reports").weekly_on(1, "08:00")

# Une fonction, avec l'injection du conteneur :
# def prune_tokens():
#     ...
# Schedule.call(prune_tokens).hourly().without_overlapping()
