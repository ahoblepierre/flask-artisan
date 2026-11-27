# Flask-Artisan

**Les conventions de Laravel, mais c'est du Flask.**

Flask-Artisan donne une structure prête à l'emploi aux applications Flask : conteneur de services,
service providers, configuration par fichiers, façades et helpers. L'application reste un vrai
objet `Flask` : `flask run`, les extensions Flask et leur documentation fonctionnent tels quels.

> Version 0.8 (alpha) : l'API peut encore changer avant la 1.0. Voir le [changelog](https://github.com/ahoblepierre/flask-artisan/blob/main/CHANGELOG.md).

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
├── app/http/controllers/  # controllers
├── app/http/kernel.py    # middlewares : globaux, alias, groupes web et api
├── app/providers/        # AppServiceProvider, RouteServiceProvider
├── routes/web.py         # routes web
├── routes/api.py         # routes préfixées par /api
├── bootstrap/app.py      # crée l'Application
├── app/models/            # modèles (User fourni)
├── config/app.py         # nom, environnement, debug, clé, providers
├── config/database.py    # connexions sqlite, mysql, mariadb, pgsql
├── database/migrations/  # migrations générées
├── config/flask.py       # clés copiées dans app.config (extensions Flask)
├── tests/
├── wsgi.py               # détecté par `flask run`
└── .env                  # APP_KEY générée automatiquement
```

## Feuille de route v0.1 (publiée)

1. ✅ Socle : package, Application, conteneur, providers, config, façades
2. ✅ Routage et middlewares (`routes/web.py`, controllers en classes)
3. ✅ ORM façon Eloquent sur SQLAlchemy, migrations
4. ✅ Authentification (façade `Auth`, guards session et token)
5. ✅ Commandes `flask make:*`, `flask migrate`, `flask route:list`

Après la v0.1 :

- ✅ Validation (`FormRequest`, règles façon Laravel, réponses 422 JSON)
- ✅ Événements (`Event.dispatch`, écouteurs, `Event.fake()`)
- ✅ Mail (mailables, transports `smtp` / `log` / `array`, `Mail.fake()`)
- ✅ Queues (jobs sur RQ, `flask queue:work`, échecs, `Mail.queue`, écouteurs `ShouldQueue`, `Queue.fake()`)
- ✅ Cache (`Cache.get/put/remember/increment`, stores `file`, `redis`, `array`)
- ✅ Limitation de débit et verrous (`throttle`, `RateLimiter`, `Cache.lock`, `TRUSTED_PROXIES`)
