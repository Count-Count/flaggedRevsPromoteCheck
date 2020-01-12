from datetime import datetime
import locale

from flask import Flask, abort
import pywikibot
import pytz
from criteria import CriteriaChecker

app = Flask("flaggedrevscrit")
locale.setlocale(locale.LC_ALL, "de_DE.utf8")
site = pywikibot.Site()
site.login()
timezone = pytz.timezone("Europe/Berlin")
criteriaChecker = CriteriaChecker(site)


@app.route("/<wiki>/<username>")
def checkCriteria(wiki: str, username: str) -> str:
    user = pywikibot.User(site, username)
    if not user.isRegistered():
        abort(400, "User not found.")
    crit = criteriaChecker.checkUserEligibleForAutoReviewGroup(criteriaChecker.getUserData(user, datetime.now()))

    res = ""
    if not list(filter(lambda criteria: not criteria.met, crit)):
        res += f"Benutzer:{username} erfüllt die Kriterien für passive Sichterrechte:"
    else:
        res += f"Benutzer:{username} erfüllt die Kriterien für passive Sichterrechte NICHT:"
    res += "<ul>"
    for c in crit:
        res += f'<li style="color:{ "green" if c.met else "red"}">' + c.text + "</li>"
    res += "</ul>"

    crit = criteriaChecker.checkUserEligibleForReviewGroup(criteriaChecker.getUserData(user, datetime.now()))
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