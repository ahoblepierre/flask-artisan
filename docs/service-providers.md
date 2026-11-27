# Service providers

```python
from flask_artisan import ServiceProvider


class MailServiceProvider(ServiceProvider):
    def register(self):
        self.app.singleton(Mailer, SmtpMailer)

    def boot(self):
        mail_extension.init_app(self.app)  # n'importe quelle extension Flask
```

Ajoutez la classe à `providers` dans `config/app.py`.
