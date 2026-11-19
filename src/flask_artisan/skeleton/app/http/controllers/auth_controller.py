from flask import request

from flask_artisan import Auth


class AuthController:
    def login(self):
        data = request.get_json(silent=True) or {}
        user = Auth.validate(email=data.get("email"), password=data.get("password"))
        if user is None:
            return {"message": "Invalid credentials."}, 401
        return {"token": user.create_token(data.get("device_name") or "api")}

    def logout(self):
        Auth.user().current_access_token().delete()
        return "", 204

    def user(self):
        return Auth.user()
