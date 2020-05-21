#!/usr/bin/python
#
# (C) 2020 Count Count
#
# Distributed under the terms of the MIT license.

from __future__ import unicode_literals

import locale
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast, List, Any, Set

import os
import re

import pytz
import pywikibot

from criteria import CriteriaChecker


@dataclass
class AlreadyReportedCandidates:
    reviewCandidates: Set[str]
    autoReviewCandidates: Set[str]


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

    def getAlreadyReportedCandidates(self) -> AlreadyReportedCandidates:
        page = pywikibot.Page(self.site, "Wikipedia:Gesichtete Versionen/Rechtevergabe/Botliste")
        self.site.loadrevisions(page, rvdir=True, content=True, user=self.site.user())
        actualRevs = page._revisions.values()
        newText = None
        reviewCandidates = set()
        autoReviewCandidates = set()
        pattern = re.compile(r"\{\{Wikipedia:Gesichtete Versionen/Rechtevergabe/Vorlage\|([^}]+)\}\}")
        for rev in [x for x in actualRevs]:
            oldText = page.getOldVersion(rev.parent_id) if not newText else newText
            newText = rev.text
            addedText = newText[len(oldText) :]
            targetSet = set()
            for line in addedText.split("\n"):
                if line == "; Kandidaten für aktive Sichterrechte":
                    targetSet = reviewCandidates
                elif line == "; Kandidaten für passive Sichterrechte":
                    targetSet = autoReviewCandidates
                for match in pattern.finditer(line):
                    user = match.group(1)
                    targetSet.add(user)

        return AlreadyReportedCandidates(reviewCandidates, autoReviewCandidates)

    def listNewUsers(self) -> None:
        alreadyReportedCandidates = self.getAlreadyReportedCandidates()
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
                userData = self.criteriaChecker.getUserData(user, endTime, False)

                # check for review rights
                reviewCriteriaChecks = self.criteriaChecker.checkUserEligibleForReviewGroup(userData)
                eligibleForReview = not list(filter(lambda criteria: not criteria.met, reviewCriteriaChecks))
                if eligibleForReview and not username in alreadyReportedCandidates.reviewCandidates:
                    usersToBePromoted.append(user)
                    continue

                # check for autoreview rights
                if "autoreview" in user.rights() or username in alreadyReportedCandidates.autoReviewCandidates:
                    continue
                autoReviewCriteriaChecks = self.criteriaChecker.checkUserEligibleForAutoReviewGroup(userData)
                eligibleForAutoReview = not list(filter(lambda criteria: not criteria.met, autoReviewCriteriaChecks))
                if eligibleForAutoReview:
                    usersToBePromotedToAutoReview.append(user)

        newSection = f"\n\n== {self.getDateString(startTime)} ==\n"
        newSection += "; Kandidaten für aktive Sichterrechte\n"
        #        print(f"{len(usersToBePromoted)} Benutzer gefunden.")
        if usersToBePromoted:
            for user in sorted(usersToBePromoted):
                newSection += f"* {{{{Wikipedia:Gesichtete Versionen/Rechtevergabe/Vorlage|{user.username}}}}}\n"
        else:
            newSection += f":''keine''\n"
        newSection += "\n"
        newSection += "; Kandidaten für passive Sichterrechte\n"
        #        print(f"{len(usersToBePromotedToAutoReview)} Benutzer gefunden.")
        if usersToBePromotedToAutoReview:
            for user in sorted(usersToBePromotedToAutoReview):
                newSection += f"* {{{{Wikipedia:Gesichtete Versionen/Rechtevergabe/Vorlage|{user.username}}}}}\n"
        else:
            newSection += f":''keine''\n"

        if not usersToBePromoted and not usersToBePromotedToAutoReview:
            newSection += f"{{{{Erledigt|--~~~~}}}}\n"

        page = pywikibot.Page(self.site, "Wikipedia:Gesichtete Versionen/Rechtevergabe/Botliste")
        page.text += newSection
        page.save(summary=f"Neue Kandidaten für den {self.getDateString(startTime)} hinzugefügt.")

        print(newSection)

    def checkSingleUser(self) -> None:
        crit = self.criteriaChecker.checkUserEligibleForReviewGroup(
            self.criteriaChecker.getUserData(
                pywikibot.User(self.criteriaChecker.site, "Benutzer:Beson"), datetime(2020, 1, 6), False
            )
        )
        if list(filter(lambda criteria: not criteria.met, crit)):
            print(f"User not eligible")
        else:
            print(f"User eligible")


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
