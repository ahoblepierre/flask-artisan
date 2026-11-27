# Flask-Artisan

**Les conventions de Laravel, mais c'est du Flask.**

Flask-Artisan donne une structure prête à l'emploi aux applications Flask : conteneur de services,
service providers, configuration par fichiers, façades et helpers. L'application reste un vrai
objet `Flask` : `flask run`, les extensions Flask et leur documentation fonctionnent tels quels.

> Version 0.10 (alpha) : l'API peut encore changer avant la 1.0. Voir le [changelog](https://github.com/ahoblepierre/flask-artisan/blob/main/CHANGELOG.md).

## Démarrer un projet

Prérequis : Python 3.10 ou plus (`python3 --version`). Sur macOS, le `python3` livré avec Xcode est un 3.9 : installez une version récente (python.org ou Homebrew).

```bash
python3 -m venv .venv && source .venv/bin/activate   # environnement virtuel
pip install flask-artisan
flask-artisan new blog
cd blog
pip install -r requirements.txt
flask run
```

Le projet généré :

```
blog/
├── app/http/controllers/  # controllers (connexion web et API fournies)
├── app/http/requests/     # Form Requests
├── app/http/kernel.py     # middlewares : globaux, alias, groupes web et api
├── app/models/            # modèles (User fourni, Notifiable)
├── app/notifications/     # notifications (flask make:notification)
├── app/providers/         # AppServiceProvider, EventServiceProvider, RouteServiceProvider
├── bootstrap/app.py       # crée l'Application
├── config/                # app, auth, cache, database, filesystems, flask, mail, queue
├── database/migrations/   # migrations générées
├── resources/views/       # templates Jinja (layout, connexion, e-mails)
├── routes/web.py          # routes web (CSRF, sessions)
├── routes/api.py          # routes préfixées par /api, toujours en JSON
├── routes/console.py      # tâches planifiées
├── tests/                 # conftest (SQLite en mémoire) et exemples
├── wsgi.py                # détecté par `flask run`
└── .env                   # APP_KEY générée automatiquement
```

## Feuille de route v0.1 (publiée)

1. ✅ Socle : package, Application, conteneur, providers, config, façades
2. ✅ Routage et middlewares (`routes/web.py`, controllers en classes)
3. ✅ ORM façon Eloquent sur SQLAlchemy, migrations
4. ✅ Authentification (façade `Auth`, guards session et token)
5. ✅ Commandes `flask make:*`, `flask migrate`, `flask route:list`

Après la v0.1 :

- ✅ Validation (`FormRequest`, règles façon Laravel, 422 JSON ou redirection avec les erreurs)
- ✅ Événements (`Event.dispatch`, écouteurs, `Event.fake()`)
- ✅ Mail (mailables, transports `smtp` / `log` / `array`, `Mail.fake()`)
- ✅ Queues (jobs sur RQ, `flask queue:work`, échecs, `Mail.queue`, écouteurs `ShouldQueue`, `Queue.fake()`)
- ✅ Cache (`Cache.get/put/remember/increment`, stores `file`, `redis`, `array`)
- ✅ Limitation de débit et verrous (`throttle`, `RateLimiter`, `Cache.lock`, `TRUSTED_PROXIES`)
- ✅ Tâches planifiées (`routes/console.py`, `flask schedule:run`)
- ✅ Vues HTML et formulaires (`errors`, `old()`, CSRF, page de connexion)
- ✅ Tests HTTP (assertions chaînables, `acting_as`)
- ✅ Stockage de fichiers (façade `Storage`, disques local et S3, uploads)
- ✅ Notifications (canaux `mail` et `database`, `Notifiable`, `Notification.fake()`)
- ✅ Kit de démarrage `flask auth:install` (inscription, mot de passe oublié, vérification de l'e-mail, URLs signées)
