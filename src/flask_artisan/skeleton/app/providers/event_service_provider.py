from flask_artisan.events import EventServiceProvider as BaseEventServiceProvider


class EventServiceProvider(BaseEventServiceProvider):
    # Événement → écouteurs, appelés dans l'ordre :
    #   from app.events.order_shipped import OrderShipped
    #   from app.listeners.send_shipment_notification import SendShipmentNotification
    #   listen = {OrderShipped: [SendShipmentNotification]}
    listen = {}
