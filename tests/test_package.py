def test_package_importable():
    import flask_artisan

    assert flask_artisan.__version__ == "0.1.0.dev0"
