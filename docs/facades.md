# Façades

```python
from flask_artisan import Config, Facade

Config.get("app.name")


class Payment(Facade):
    accessor = PaymentGateway  # n'importe quelle clé du conteneur


Payment.charge(...)
```
