from flask import render_template

from flask_artisan import Auth


class DashboardController:
    def index(self):
        return render_template("dashboard.html", user=Auth.user())
