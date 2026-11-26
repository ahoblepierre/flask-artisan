from flask_artisan.queue import Job

from .models import QPodcast

Record: list = []


class Service:
    pass


class Ping(Job):
    def __init__(self, word):
        self.word = word

    def handle(self):
        Record.append(self.word)


class Injected(Job):
    def handle(self, svc: Service):
        Record.append(svc)


class WithPodcast(Job):
    def __init__(self, podcast: QPodcast):
        self.podcast = podcast

    def handle(self):
        Record.append(self.podcast)


class Boom(Job):
    def handle(self):
        Record.append("try")
        raise RuntimeError("boom")

    def failed(self, exc):
        Record.append(("failed", str(exc)))


class BadFailed(Boom):
    def failed(self, exc):
        raise ValueError("failed a cassé")


class Unserializable(Job):
    def __init__(self):
        self.handle_ = object()

    def handle(self):
        Record.append("ran")
