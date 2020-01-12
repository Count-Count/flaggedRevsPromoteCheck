from datetime import datetime
import locale

from flask import Flask
import pywikibot
import pytz
from criteria import CriteriaChecker

app = Flask("flaggedrevscrit")
locale.setlocale(locale.LC_ALL, "de_DE.utf8")
site = pywikibot.Site()
site.login()
timezone = pytz.timezone("Europe/Berlin")
criteriaChecker = CriteriaChecker(site)


@app.route("/<wiki>/<user>")
def checkCriteria(wiki: str, user: str) -> str:
    crit = criteriaChecker.checkUserEligibleForAutoReviewGroup(
        criteriaChecker.getUserData(pywikibot.User(site, user), datetime.now())
    )

    res = ""
    if not list(filter(lambda criteria: not criteria.met, crit)):
        res += "Kriterien für passive Sichterrechte werden erfüllt:"
    else:
        res += "Kriterien für passive Sichterrechte werden NICHT erfüllt:"
    res += "<ul>"
    for c in crit:
        res += "<li>" + c.text + "</li>"
    res += "</ul>"

    crit = criteriaChecker.checkUserEligibleForReviewGroup(
        criteriaChecker.getUserData(pywikibot.User(site, user), datetime.now())
    )
    if not list(filter(lambda criteria: not criteria.met, crit)):
        res += "Kriterien für aktive Sichterrechte werden erfüllt:"
    else:
        res += "Kriterien für aktive Sichterrechte werden NICHT erfüllt:"
    res += "<ul>"
    for c in crit:
        res += "<li>" + c.text + "</li>"
    res += "</ul>"

    return res


if __name__ == "__main__":
    app.run()
