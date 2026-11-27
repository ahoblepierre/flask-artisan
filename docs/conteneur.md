# Conteneur de services

```python
from flask_artisan import app

app().bind(Mailer, SmtpMailer)                        # nouvelle instance à chaque make
app().singleton(Cache, lambda app: RedisCache("..."))  # une seule instance
app().make(ReportService)  # dépendances du constructeur injectées d'après leurs annotations
```
