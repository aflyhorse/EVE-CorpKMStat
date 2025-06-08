"""
Authentication routes and views.
"""

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from kmstat import app, db
from kmstat.models import User


@app.route("/login", methods=["GET", "POST"])
def login():
    """Login page."""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        remember_me = request.form.get("remember_me") is not None

        if not username or not password:
            flash("请输入用户名和密码", "error")
            return render_template("auth/login.html")

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user, remember=remember_me)
            next_page = request.args.get("next")
            return redirect(next_page) if next_page else redirect(url_for("dashboard"))
        else:
            flash("用户名或密码错误", "error")

    return render_template("auth/login.html.jinja2")


@app.route("/logout")
@login_required
def logout():
    """Logout current user."""
    logout_user()
    flash("已成功登出", "success")
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """Change current user's password."""
    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        if not all([current_password, new_password, confirm_password]):
            flash("请填写所有字段", "error")
            return render_template("auth/change_password.html")

        if not current_user.check_password(current_password):
            flash("当前密码错误", "error")
            return render_template("auth/change_password.html")

        if new_password != confirm_password:
            flash("新密码与确认密码不匹配", "error")
            return render_template("auth/change_password.html")

        if len(new_password) < 6:
            flash("密码长度至少为6位", "error")
            return render_template("auth/change_password.html")

        current_user.set_password(new_password)
        db.session.commit()
        flash("密码修改成功", "success")
        return redirect(url_for("dashboard"))

    return render_template("auth/change_password.html.jinja2")
