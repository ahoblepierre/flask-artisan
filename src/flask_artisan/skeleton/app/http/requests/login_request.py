from flask_artisan.validation import FormRequest


class LoginRequest(FormRequest):
    def rules(self):
        return {
            "email": "required|string|email",
            "password": "required|string",
            "device_name": "sometimes|string|max:255",
        }
