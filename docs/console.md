# Console

Les générateurs écrivent le fichier au bon endroit, avec un squelette prêt à l'emploi :

```bash
flask make:controller PhotoController            # app/http/controllers/photo_controller.py
flask make:controller PhotoController --resource # les 7 méthodes de Route.resource
flask make:controller Admin/UserController       # sous-dossier admin/
flask make:model Post                            # app/models/post.py
flask make:event OrderShipped                    # app/events/order_shipped.py
flask make:listener SendShipmentNotification --event OrderShipped  # app/listeners/…
flask make:mail OrderShipped                     # app/mail/order_shipped.py + son template
flask make:job ProcessPodcast                    # app/jobs/process_podcast.py
flask make:notification InvoicePaid              # app/notifications/invoice_paid.py
flask make:request StorePostRequest              # app/http/requests/store_post_request.py
flask make:middleware EnsureJson                 # app/http/middleware/ensure_json.py
flask make:provider PaymentServiceProvider       # app/providers/payment_service_provider.py
flask make:command SendEmails                    # app/console/commands/send_emails.py → flask app:send-emails
flask cache:clear                                # vide le cache (voir « Cache »)
```

Un fichier existant n'est jamais écrasé sans `--force`. `make:middleware` et `make:provider` affichent la ligne à ajouter au kernel ou à `config/app.py`.

Pas de `make:model -m` : les migrations sont générées depuis les colonnes du modèle. Ajoutez-les, puis lancez `flask make:migration`.

Vos commandes sont des commandes [Click](https://click.palletsprojects.com) dans `app/console/commands/`. Elles sont découvertes toutes seules et s'exécutent dans le contexte de l'application. Un fichier qui ne s'importe pas fait échouer les commandes du projet avec son nom (sur `flask --help`, Flask affiche l'erreur mais rend la main normalement). Les commandes du framework (`make:*`, `migrate`, `route:list`) et l'app web ne sont pas touchées :

```python
# app/console/commands/send_emails.py
import click

from app.models.user import User


@click.command("app:send-emails")
@click.argument("user_id", type=int)
def send_emails(user_id):
    """Envoie les emails en attente d'un utilisateur."""
    click.echo(User.find_or_fail(user_id).email)
```

`flask route:list` affiche les routes déclarées avec `Route` :

```
Méthodes   URI          Nom         Action                 Middlewares
POST       /api/login   api.login   AuthController@login
GET        /api/user    api.user    AuthController@user    Authenticate:api
```
