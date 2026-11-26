from flask_artisan.queue import Job, ShouldQueue

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


class Retried(Boom):
    tries = 3


class Backoff(Boom):
    tries = 4
    backoff = [5, 30]


class BadFailedOnce(BadFailed):
    pass


class Slow(Ping):
    timeout = 5


class AddUncommitted(Job):
    def handle(self):
        from flask_artisan import DB

        DB.session.add(QPodcast(title="pending"))
        DB.session.flush()


class CountPodcasts(Job):
    def handle(self):
        Record.append(QPodcast.query().count())


class Shipped:
    def __init__(self, podcast, note="x"):
        self.podcast = podcast
        self.note = note


class QueuedListener(ShouldQueue):
    queue = "listeners"
    tries = 3

    def handle(self, event):
        Record.append(("handle", event.podcast.title, event.note))

    def on_ship(self, event):
        Record.append(("on_ship", event.podcast.title))


class PlainListener:
    def handle(self, event):
        Record.append("plain")


class AudioBoom(Boom):
    queue = "audio"
