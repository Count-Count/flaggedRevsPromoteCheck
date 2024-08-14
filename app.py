import locale
import platform
from datetime import datetime

import pytz
import pywikibot
from flask import Flask, abort

from criteria import CriteriaChecker

if platform.system() == "Darwin":
    locale.setlocale(locale.LC_ALL, "de_DE.UTF-8")
else:
    locale.setlocale(locale.LC_ALL, "de_DE.utf8")

app = Flask("flaggedrevscrit")
site = pywikibot.Site()
site.login()
timezone = pytz.timezone("Europe/Berlin")
criteriaChecker = CriteriaChecker(site)


@app.route("/<wiki>/<username>")
def checkCriteria(wiki: str, username: str) -> str:
    user = pywikibot.User(site, username)
    if not user.isRegistered():
        abort(400, "User not found.")

    if user.editCount() >= 5000:
        return "This tool only works for users with less than 5000 edits."

    userData = criteriaChecker.getUserData(user, datetime.now(), True)

    crit = criteriaChecker.checkUserEligibleForAutoReviewGroup(userData)
    res = ""
    if not list(filter(lambda criteria: not criteria.met, crit)):
        res += f"Benutzer:{username} erfüllt die Kriterien für passive Sichterrechte:"
    else:
        res += f"Benutzer:{username} erfüllt die Kriterien für passive Sichterrechte NICHT:"
    res += "<ul>"
    for c in crit:
        res += f'<li style="color:{ "green" if c.met else "red"}">' + c.text + "</li>"
    res += "</ul>"

    crit = criteriaChecker.checkUserEligibleForReviewGroup(userData)
    if not list(filter(lambda criteria: not criteria.met, crit)):
        res += f"Benutzer:{username} erfüllt die Kriterien für aktive Sichterrechte:"
    else:
        res += f"Benutzer:{username} erfüllt die Kriterien für aktive Sichterrechte NICHT:"
    res += "<ul>"
    for c in crit:
        res += f'<li style="color:{ "green" if c.met else "red"}">' + c.text + "</li>"
    res += "</ul>"

    return res


if __name__ == "__main__":
    app.run()
