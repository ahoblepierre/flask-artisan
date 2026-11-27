# Configuration

```python
# config/app.py
from flask_artisan import env

config = {"name": env("APP_NAME", "Blog"), "debug": env("APP_DEBUG", False)}
```

```python
from flask_artisan import config

config("app.name")
config("app.timezone", "UTC")  # valeur par défaut
```
