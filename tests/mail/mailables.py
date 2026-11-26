from flask_artisan.mail import Mailable


class Hello(Mailable):
    subject = "Hi"
    view = "emails/hello.html"
    text = "emails/hello.txt"

    def __init__(self, name):
        self.name = name


class HtmlOnly(Hello):
    text = None


class TextOnly(Hello):
    view = None


class Empty(Mailable):
    subject = "Rien"
