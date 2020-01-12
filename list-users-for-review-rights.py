#!/usr/bin/python
#
# (C) 2020 Count Count
#
# Distributed under the terms of the MIT license.

from __future__ import unicode_literals

import locale
from datetime import datetime, timedelta
from typing import cast, List, Any, Set

import pytz
import pywikibot

from criteria import CriteriaChecker


class Program:
    def __init__(self) -> None:
        self.site = pywikibot.Site()
        self.site.login()
        self.timezone = pytz.timezone("Europe/Berlin")
        self.criteriaChecker = CriteriaChecker(self.site)

    def listNewUsers(self) -> None:
        alreadyChecked: Set[str] = set()
        startTime = datetime(2020, 1, 11)
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
            if username in alreadyChecked:
                continue
            alreadyChecked.add(username)
            count += 1
            # if count % 100 == 0:
            #     print(f"Checked {count} users.")
            user = pywikibot.User(self.site, username)
            if not "review" in user.rights():
                userData = self.criteriaChecker.getUserData(user, endTime)
                criteriaChecks = self.criteriaChecker.checkUserEligibleForReviewGroup(userData)
                if not list(filter(lambda criteria: not criteria.met, criteriaChecks)):
                    usersToBePromoted.append(user)
                else:
                    criteriaChecks = self.criteriaChecker.checkUserEligibleForAutoReviewGroup(userData)
                    if not list(filter(lambda criteria: not criteria.met, criteriaChecks)):
                        usersToBePromotedToAutoReview.append(user)
        print("Aktive Sichter:")
        print(f"{len(usersToBePromoted)} Benutzer gefunden.")
        for user in sorted(usersToBePromoted):
            print(
                f"* {{{{Wikipedia:Gesichtete Versionen/Rechtevergabe/Vorlage|{user.username}}}}} ([https://tools.wmflabs.org/flaggedrevspromotioncheck/dewiki/{{{{urlencode:{user.username}|PATH}}}} Kriterien überprüfen])"
            )
        print()
        print("Passive Sichter:")
        print(f"{len(usersToBePromotedToAutoReview)} Benutzer gefunden.")
        for user in sorted(usersToBePromotedToAutoReview):
            print(
                f"* {{{{Wikipedia:Gesichtete Versionen/Rechtevergabe/Vorlage|{user.username}}}}} ([https://tools.wmflabs.org/flaggedrevspromotioncheck/dewiki/{{{{urlencode:{user.username}|PATH}}}} Kriterien überprüfen])"
            )

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
