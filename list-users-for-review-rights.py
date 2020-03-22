#!/usr/bin/python
#
# (C) 2020 Count Count
#
# Distributed under the terms of the MIT license.

from __future__ import unicode_literals

import locale
from datetime import datetime, timedelta
from typing import cast, List, Any, Set

import os

import pytz
import pywikibot

from criteria import CriteriaChecker


class Program:
    def __init__(self) -> None:
        self.site = pywikibot.Site()
        self.site.login()
        self.timezone = pytz.timezone("Europe/Berlin")
        self.criteriaChecker = CriteriaChecker(self.site)

    @staticmethod
    def getDateString(date: int) -> str:
        dayFormat = "%-d" if os.name != "nt" else "%d"
        return date.strftime(f"{dayFormat}. %B %Y")

    def listNewUsers(self) -> None:
        h24Ago = datetime.now() - timedelta(days=1)
        startTime = datetime(h24Ago.year, h24Ago.month, h24Ago.day, 0, 0, 0)
        endTime = startTime + timedelta(hours=24)
        recentChanges = self.site.recentchanges(end=startTime, start=endTime)  # reverse order
        usernames = set()
        for ch in recentChanges:
            if "userhidden" in ch:
                continue
            if (ch["type"] == "edit" or ch["type"] == "new") and not "anon" in ch:
                usernames.add(ch["user"])
        usersToBePromoted = []
        usersToBePromotedToAutoReview = []
        print(f"Checking {len(usernames)} users for {startTime}...")
        count = 0
        for username in usernames:
            count += 1
            if count % 100 == 0:
                print(f"Checked {count} users.")
            user = pywikibot.User(self.site, username)
            if not "review" in user.rights():
                userData = self.criteriaChecker.getUserData(user, endTime)
                criteriaChecks = self.criteriaChecker.checkUserEligibleForReviewGroup(userData)
                if not list(filter(lambda criteria: not criteria.met, criteriaChecks)):
                    usersToBePromoted.append(user)
                elif not "autoreview" in user.rights():
                    criteriaChecks = self.criteriaChecker.checkUserEligibleForAutoReviewGroup(userData)
                    if not list(filter(lambda criteria: not criteria.met, criteriaChecks)):
                        usersToBePromotedToAutoReview.append(user)
        newSection = f"\n\n== {self.getDateString(startTime)} ==\n"
        newSection += "; Kandidaten für aktive Sichterrechte\n"
        #        print(f"{len(usersToBePromoted)} Benutzer gefunden.")
        for user in sorted(usersToBePromoted):
            newSection += f"* {{{{Wikipedia:Gesichtete Versionen/Rechtevergabe/Vorlage|{user.username}}}}}\n"
        newSection += "\n"
        newSection += "; Kandidaten für passive Sichterrechte\n"
        #        print(f"{len(usersToBePromotedToAutoReview)} Benutzer gefunden.")
        for user in sorted(usersToBePromotedToAutoReview):
            newSection += f"* {{{{Wikipedia:Gesichtete Versionen/Rechtevergabe/Vorlage|{user.username}}}}}\n"
        page = pywikibot.Page(self.site, "Wikipedia:Gesichtete Versionen/Rechtevergabe/Botliste")
        page.text += newSection
        page.save(summary=f"Neue Kandidaten für den {self.getDateString(startTime)} hinzugefügt.")

        print(newSection)

    def checkSingleUser(self) -> None:
        crit = self.criteriaChecker.checkUserEligibleForReviewGroup(
            self.criteriaChecker.getUserData(
                pywikibot.User(self.criteriaChecker.site, "Benutzer:Quild009"), datetime(2020, 1, 6)
            )
        )
        if not list(filter(lambda criteria: not criteria.met, crit)):
            print(f"User not eligible")


def main() -> None:
    locale.setlocale(locale.LC_ALL, "de_DE.utf8")
    pywikibot.handle_args()
    # Program().checkSingleUser()
    Program().listNewUsers()


if __name__ == "__main__":
    try:
        main()
    finally:
        pywikibot.stopme()
