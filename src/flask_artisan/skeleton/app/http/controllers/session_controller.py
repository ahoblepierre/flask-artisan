from flask import flash, redirect, render_template, url_for

from app.http.requests.login_request import LoginRequest
from flask_artisan import Auth
from flask_artisan.validation import ValidationError


class SessionController:
    """Connexion par formulaire (guard session) : routes/web.py."""

    def create(self):
        return render_template("auth/login.html")

    def store(self, request: LoginRequest):
        data = request.validated()
        if not Auth.attempt(email=data["email"], password=data["password"]):
            # Renvoie sur le formulaire, avec l'erreur et l'email saisi (comme Laravel).
            raise ValidationError({"email": ["Ces identifiants ne correspondent à aucun compte."]})
        flash("Connecté.")
        return redirect(url_for("dashboard"))

    def destroy(self):
        Auth.logout()
        return redirect("/")
