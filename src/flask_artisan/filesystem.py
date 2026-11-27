"""Stockage de fichiers façon Laravel : façade `Storage`, disques `local` et `s3`, `Storage.fake()`."""

import io
import mimetypes
import os
import secrets
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote

from flask import send_file
from werkzeug.utils import secure_filename

# Types servis « en ligne » (route du disque public, objets S3). Tout autre type, dont
# text/html et image/svg+xml, part en pièce jointe : un fichier envoyé ne doit jamais
# s'exécuter comme une page du site (XSS stocké).
INLINE_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/avif",
        "application/pdf",
        "text/plain",
    }
)

DEFAULT_DISKS = {
    "local": {"driver": "local", "root": "storage/app/private"},
    "public": {"driver": "local", "root": "storage/app/public", "url": "/storage", "serve": True},
}


def is_inline(mimetype: str | None) -> bool:
    if not mimetype:
        return False
    return mimetype in INLINE_TYPES or mimetype.split("/", 1)[0] in ("audio", "video")


def guess_type(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _clean(path, allow_empty: bool = False) -> str:
    """Chemin relatif sûr, `/` comme séparateur ; ValueError sinon (jamais hors du disque)."""
    if not isinstance(path, str):
        raise ValueError(f"Chemin invalide : {path!r}.")  # noqa: TRY004 (même erreur pour tout chemin refusé)
    if path == "" and allow_empty:
        return ""
    if "\\" in path or "\x00" in path or path.startswith("/"):
        raise ValueError(f"Chemin refusé : {path!r}.")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError(f"Chemin refusé : {path!r}.")
    return path


def _extension(filename: str | None) -> str:
    """Extension sûre (en minuscules, avec le point) du nom envoyé, sinon ""."""
    name = secure_filename(filename or "")
    if "." not in name:
        return ""
    ext = name.rsplit(".", 1)[1].lower()
    return f".{ext}" if ext.isalnum() else ""


def _bytes(contents) -> bytes:
    if isinstance(contents, str):
        return contents.encode()
    if isinstance(contents, (bytes, bytearray)):
        return bytes(contents)
    return contents.read()


class Disk:
    """API commune ; chaque pilote fournit _write, _read, _exists, _delete, _size, _files."""

    def put(self, path: str, contents) -> str:
        path = _clean(path)
        self._write(path, _bytes(contents))
        return path

    def get(self, path: str) -> bytes:
        return self._read(_clean(path))

    def exists(self, path: str) -> bool:
        return self._exists(_clean(path))

    def missing(self, path: str) -> bool:
        return not self.exists(path)

    def delete(self, *paths: str) -> bool:
        cleaned = [_clean(p) for p in paths]  # tout valider avant de supprimer
        return all([self._delete(p) for p in cleaned])  # noqa: C419 (liste : tout supprimer)

    def size(self, path: str) -> int:
        return self._size(_clean(path))

    def files(self, directory: str = "") -> list[str]:
        return sorted(self._files(_clean(directory, allow_empty=True)))

    def url(self, path: str) -> str:
        path = _clean(path)
        if not self._url:
            raise RuntimeError("Ce disque n'a pas d'URL : ajoutez 'url' à sa config.")
        return f"{self._url.rstrip('/')}/{quote(path)}"

    def path(self, path: str) -> Path:
        raise RuntimeError(f"{type(self).__name__} n'a pas de chemin local.")

    def put_file(self, directory: str, file) -> str:
        """Enregistre un fichier envoyé (FileStorage) sous un nom aléatoire."""
        return self.put_file_as(directory, file, secrets.token_hex(20) + _extension(file.filename))

    def put_file_as(self, directory: str, file, name: str) -> str:
        if "/" in name:
            raise ValueError(f"Nom de fichier refusé : {name!r} (un seul segment).")
        directory = _clean(directory, allow_empty=True)
        return self.put(f"{directory}/{_clean(name)}" if directory else _clean(name), file.stream)

    def download(self, path: str, name: str | None = None):
        data = self.get(path)
        return send_file(
            io.BytesIO(data), as_attachment=True, download_name=name or path.rsplit("/", 1)[-1]
        )

    def assert_exists(self, path: str):
        if not self.exists(path):
            raise AssertionError(f"Fichier absent du disque : {path!r}.")
        return self

    def assert_missing(self, path: str):
        if self.exists(path):
            raise AssertionError(f"Fichier présent sur le disque : {path!r}.")
        return self


class LocalDisk(Disk):
    def __init__(self, root, url: str | None = None):
        self.root = Path(root).resolve()
        self._url = url

    def path(self, path: str) -> Path:
        return self.root / _clean(path)

    def _write(self, path: str, data: bytes) -> None:
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=full.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, full)  # écriture atomique : jamais de fichier à moitié écrit
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _read(self, path: str) -> bytes:
        return (self.root / path).read_bytes()

    def _exists(self, path: str) -> bool:
        return (self.root / path).is_file()

    def _delete(self, path: str) -> bool:
        try:
            (self.root / path).unlink()
        except FileNotFoundError:
            return False
        return True

    def _size(self, path: str) -> int:
        return (self.root / path).stat().st_size

    def _files(self, directory: str) -> list[str]:
        base = self.root / directory
        if not base.is_dir():
            return []
        prefix = f"{directory}/" if directory else ""
        return [
            prefix + p.name
            for p in base.iterdir()
            if p.is_file() and not p.name.startswith(".tmp-")
        ]


class FakeDisk(LocalDisk):
    """Disque de Storage.fake() : un dossier temporaire ; l'URL reste celle du vrai disque."""

    def __init__(self, manager: "FilesystemManager", real: Disk):
        super().__init__(tempfile.mkdtemp(prefix="flask-artisan-"))
        self._manager = manager
        self._real = real

    def url(self, path: str) -> str:
        return self._real.url(path)

    def __enter__(self) -> "FakeDisk":  # noqa: PYI034 (typing.Self exige 3.11)
        return self

    def __exit__(self, *exc) -> None:
        self._manager.restore()


class S3Disk(Disk):
    """Bucket S3 (ou compatible : MinIO, R2 par `endpoint`) ; boto3 importé à l'usage."""

    def __init__(
        self,
        bucket: str,
        region: str | None = None,
        key: str | None = None,
        secret: str | None = None,
        endpoint: str | None = None,
        url: str | None = None,
        root: str = "",
    ):
        self.bucket = bucket
        self.region = region or "us-east-1"
        self._credentials = (key or None, secret or None)
        self._endpoint = endpoint or None
        self._url = url or None
        self._root = root.strip("/")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                import boto3
            except ImportError:
                raise RuntimeError(
                    'Le disque s3 demande boto3 : pip install "flask-artisan[s3]".'
                ) from None
            key, secret = self._credentials
            # Sans clé ni secret : la chaîne d'identifiants de boto3 (variables, rôle IAM).
            self._client = boto3.client(
                "s3",
                region_name=self.region,
                endpoint_url=self._endpoint,
                aws_access_key_id=key,
                aws_secret_access_key=secret,
            )
        return self._client

    def _key(self, path: str) -> str:
        return f"{self._root}/{path}" if self._root and path else (self._root or path)

    def url(self, path: str) -> str:
        key = quote(self._key(_clean(path)))
        if self._url:
            return f"{self._url.rstrip('/')}/{key}"
        if self._endpoint:
            return f"{self._endpoint.rstrip('/')}/{self.bucket}/{key}"
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"

    def _missing_error(self, exc) -> bool:
        return exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound")

    def _write(self, path: str, data: bytes) -> None:
        content_type = guess_type(path)
        extra = {"ContentType": content_type}
        if not is_inline(content_type):
            # Servi par le bucket ou le CDN, sans passer par notre route : protégé ici.
            extra["ContentDisposition"] = "attachment"
        self.client.put_object(Bucket=self.bucket, Key=self._key(path), Body=data, **extra)

    def _read(self, path: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            return self.client.get_object(Bucket=self.bucket, Key=self._key(path))["Body"].read()
        except ClientError as exc:
            if self._missing_error(exc):
                raise FileNotFoundError(path) from None
            raise

    def _head(self, path: str):
        from botocore.exceptions import ClientError

        try:
            return self.client.head_object(Bucket=self.bucket, Key=self._key(path))
        except ClientError as exc:
            if self._missing_error(exc):
                return None
            raise

    def _exists(self, path: str) -> bool:
        return self._head(path) is not None

    def _delete(self, path: str) -> bool:
        existed = self._exists(path)
        self.client.delete_object(Bucket=self.bucket, Key=self._key(path))
        return existed

    def _size(self, path: str) -> int:
        head = self._head(path)
        if head is None:
            raise FileNotFoundError(path)
        return head["ContentLength"]

    def _files(self, directory: str) -> list[str]:
        prefix = self._key(directory)
        prefix = f"{prefix}/" if prefix else ""
        strip = len(f"{self._root}/") if self._root else 0
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix, Delimiter="/"
        )
        return [obj["Key"][strip:] for page in pages for obj in page.get("Contents", [])]


PUBLIC = {
    "put",
    "get",
    "exists",
    "missing",
    "delete",
    "size",
    "files",
    "url",
    "path",
    "put_file",
    "put_file_as",
    "download",
    "assert_exists",
    "assert_missing",
}


class FilesystemManager:
    """Le service `"filesystem"` (façade `Storage`) : ses méthodes visent le disque par défaut."""

    def __init__(self, app):
        self._app = app
        self._fakes: dict[str, FakeDisk] = {}

    def _config(self, key: str, default=None):
        return self._app.make("config").get(f"filesystems.{key}", default)

    def _name(self, name: str | None) -> str:
        return name or self._config("default", "local")

    def disk(self, name: str | None = None) -> Disk:
        name = self._name(name)
        if name in self._fakes:
            return self._fakes[name]
        return self._build(name)

    def _build(self, name: str) -> Disk:
        disks = self._config("disks", DEFAULT_DISKS)
        if name not in disks:
            raise ValueError(f"Disque inconnu : {name!r} (config filesystems.disks).")
        options = disks[name]
        driver = options.get("driver")
        if driver == "local":
            root = Path(options.get("root", f"storage/app/{name}"))
            return LocalDisk(
                root if root.is_absolute() else self._app.base_path(str(root)), options.get("url")
            )
        if driver == "s3":
            return S3Disk(
                options.get("bucket"),
                options.get("region"),
                options.get("key"),
                options.get("secret"),
                options.get("endpoint"),
                options.get("url"),
                options.get("root", ""),
            )
        raise ValueError(f"Pilote de disque inconnu : {driver!r} (disque {name!r}).")

    def fake(self, name: str | None = None) -> FakeDisk:
        name = self._name(name)
        old = self._fakes.pop(name, None)
        if old is not None:
            shutil.rmtree(old.root, ignore_errors=True)
        disk = self._fakes[name] = FakeDisk(self, self._build(name))
        return disk

    def restore(self) -> None:
        for disk in self._fakes.values():
            shutil.rmtree(disk.root, ignore_errors=True)
        self._fakes.clear()

    def __getattr__(self, name: str):
        if name in PUBLIC:
            return getattr(self.disk(), name)
        raise AttributeError(name)
