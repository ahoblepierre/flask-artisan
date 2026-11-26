from importlib.metadata import version


def test_package_importable():
    import flask_artisan

    assert flask_artisan.__version__ == "0.5.0"


def test_installed_metadata_matches_version():
    import flask_artisan

    assert version("flask-artisan") == flask_artisan.__version__
