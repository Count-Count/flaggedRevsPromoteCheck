#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Published by zhuyifei1999 (https://wikitech.wikimedia.org/wiki/User:Zhuyifei1999)
# under the terms of Creative Commons Attribution-ShareAlike 3.0 Unported (CC BY-SA 3.0)
# https://creativecommons.org/licenses/by-sa/3.0/

from __future__ import unicode_literals

import os
import re
import time
import random
import signal
import threading
import hashlib
import locale
import pytz
import re
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast, List, Any

import pywikibot
from pywikibot.comms.eventstreams import site_rc_listener
from pywikibot.diff import PatchManager

# from redis import Redis
# from redisconfig import KEYSIGN


TIMEOUT = 60  # We expect at least one rc entry every minute


class TimeoutError(Exception):
    pass


def on_timeout(signum, frame):
    raise TimeoutError


@dataclass
class CriteriaCheck:
    met: bool
    text: str


@dataclass
class UserData:
    user: pywikibot.User
    contribs: List[Any]
    articleContribs: List[Any]
    logEntries: List[Any]
    registrationTime: datetime


class Controller:
    def __init__(self):
        self.site = pywikibot.Site()
        self.site.login()  # T153541
        self.timezone = pytz.timezone("Europe/Berlin")

    def getUserData(self, user: pywikibot.User, endTime):
        contribs = list(user.contributions(total=5000, start=endTime))
        return UserData(
            user,
            contribs,
            [contrib for contrib in contribs if contrib[0].namespace() == 0],
            self.site.logevents(page=f"User:{user.username}"),
            self.getUserRegistrationTimeSafe(user),
        )

    def getUserRegistrationTimeSafe(self, user):
        registrationTime = user.registration()
        if registrationTime:
            return registrationTime

        events = self.site.logevents(user=user.username, logtype="newusers")
        for ev in events:
            if ev.type() == "newusers":
                if ev.action() == "newusers" or ev.action() == "autocreate" or ev.action() == "create2":
                    return ev.timestamp()
                else:
                    raise NotImplementedError

        # Happens for old accounts
        oldestContribList = list(user.contributions(reverse=True, total=1))
        if len(oldestContribList) == 1:
            return oldestContribList[0][2]
        else:
            raise NotImplementedError

    def checkGeneralEventLogCriterias(self, events):
        criteriaChecks = []
        wasBlockedBefore = False
        hadReviewRightsRemovedBefore = False
        for ev in events:
            if ev.type() == "rights":
                rightsEv = cast(pywikibot.logentries.RightsEntry, ev)
                if rightsEv.oldgroups is None or rightsEv.newgroups is None:
                    continue
                if "review" in rightsEv.oldgroups and not "review" in rightsEv.newgroups:
                    hadReviewRightsRemovedBefore = True
                    break
                if "autoreview" in rightsEv.oldgroups and not "autoreview" in rightsEv.newgroups:
                    hadReviewRightsRemovedBefore = True
                    break
            if ev.type() == "block" and ev.action() == "block":
                wasBlockedBefore = True
                break
        if hadReviewRightsRemovedBefore:
            criteriaChecks.append(CriteriaCheck(False, "Dem Benutzer wurden Sicherreichte schon einmal entzogen."))
        else:
            criteriaChecks.append(CriteriaCheck(True, "Dem Benutzer wurden Sicherreichte noch nie entzogen."))
        if wasBlockedBefore:
            criteriaChecks.append(CriteriaCheck(False, "Der Benutzer wurde schon einmal gesperrt."))
        else:
            criteriaChecks.append(CriteriaCheck(True, "Der Benutzer wurde noch nie gesperrt."))
        return criteriaChecks

    def checkGeneralEligibilityForPromotion(self, user):
        criteriaChecks = []
        if user.isBlocked():
            criteriaChecks.append(CriteriaCheck(False, "Benutzer ist gesperrt."))
        else:
            criteriaChecks.append(CriteriaCheck(True, "Benutzer ist nicht gesperrt."))
        if self.site.isBot(user.username):
            criteriaChecks.append(CriteriaCheck(False, "Benutzer ist ein Bot."))
        else:
            criteriaChecks.append(CriteriaCheck(True, "Benutzer ist kein Bot."))
        return criteriaChecks

    def checkRegistrationTime(self, registrationTime, minimumAgeInDays):
        criteriaChecks = []
        if not registrationTime:
            raise NotImplementedError
        if registrationTime > datetime.now() - timedelta(days=minimumAgeInDays):
            criteriaChecks.append(CriteriaCheck(False, "Das Benutzerkonto wurde vor weniger als 60 Tagen angelegt."))
        else:
            criteriaChecks.append(CriteriaCheck(True, "Das Benutzerkonto wurde vor mehr als 60 Tagen angelegt."))
        return criteriaChecks

    def checkEditCount(self, contribs, minimumEditCount):
        criteriaChecks = []
        if len(contribs) < minimumEditCount:
            criteriaChecks.append(CriteriaCheck(False, "Das Benutzerkonto hat weniger als 300 Bearbeitungen."))
        else:
            criteriaChecks.append(CriteriaCheck(True, "Das Benutzerkonto hat mindestens 300 Bearbeitungen."))
        return criteriaChecks

    def checkArticleEditCount(self, articleContribs, minimumEditCount, mostRecentEditTime, excludeXDaysBeforeLastEdit):
        relevantEdits = [
            contrib
            for contrib in articleContribs
            if contrib[2] < mostRecentEditTime - timedelta(days=excludeXDaysBeforeLastEdit)
        ]

        criteriaChecks = []
        if len(relevantEdits) < minimumEditCount:
            criteriaChecks.append(
                CriteriaCheck(False, "Das Benutzerkonto hat weniger als 300 Bearbeitungen im Artikelnamensraum.")
            )
        else:
            criteriaChecks.append(
                CriteriaCheck(True, "Das Benutzerkonto hat mehr als 300 Bearbeitungen im Artikelnamensraum.")
            )
        return criteriaChecks

    def checkMinimumEditedArticlePages(self, articleContribs, minimumSeparatePages):
        criteriaChecks = []
        articlePageCount = len(set([contrib[0].title() for contrib in articleContribs]))
        if articlePageCount < minimumSeparatePages:
            criteriaChecks.append(
                CriteriaCheck(False, "Das Benutzerkonto hat weniger als 14 verschiedene Seiten im ANR bearbeitet.")
            )
        else:
            criteriaChecks.append(
                CriteriaCheck(True, "Das Benutzerkonto hat mehr als 14 verschiedene Seiten im ANR bearbeitet.")
            )
        return criteriaChecks

    def checkSpacedEdits(self, contribs, minimumSpacedEdits):
        criteriaChecks = []
        if len(contribs) > 0:
            lastContrib = contribs[0]
            spacedEditCount = 0
            for contrib in contribs:
                if lastContrib[2] - contrib[2] > timedelta(days=3):
                    spacedEditCount += 1
                    lastContrib = contrib
            if spacedEditCount < minimumSpacedEdits:
                criteriaChecks.append(
                    CriteriaCheck(
                        False, "Das Benutzerkonto hat weniger als 15 Bearbeitungen mit mindestens drei Tagen Abstand."
                    )
                )
            else:
                criteriaChecks.append(
                    CriteriaCheck(
                        True, "Das Benutzerkonto hat mindestens 15 Bearbeitungen mit mindestens drei Tagen Abstand."
                    )
                )
        else:
            criteriaChecks.append(
                CriteriaCheck(
                    False, "Das Benutzerkonto hat weniger als 15 Bearbeitungen mit mindestens drei Tagen Abstand."
                )
            )
        return criteriaChecks

    def checkCustomSummaryEditCount(self, contribs, minimumEditsWithCustomSummary):
        criteriaChecks = []
        customSummaryCount = 0
        for contrib in contribs:
            summary = contrib[3]
            if (
                summary
                and summary != ""
                and not re.match(r"^/\*.*\*/$", summary)
                and not summary.startswith("[[Hilfe:Zusammenfassung und Quellen#Auto-Zusammenfassung|AZ]]:")
            ):
                customSummaryCount += 1
        if customSummaryCount < minimumEditsWithCustomSummary:
            criteriaChecks.append(
                CriteriaCheck(
                    False,
                    "Das Benutzerkonto hat bei weniger als 30 Bearbeitungen aktiv die Zusammenfassungszeile genutzt.",
                )
            )
        else:
            criteriaChecks.append(
                CriteriaCheck(
                    True,
                    "Das Benutzerkonto hat bei mindestens 30 Bearbeitungen aktiv die Zusammenfassungszeile genutzt.",
                )
            )
        return criteriaChecks

    def checkRecentArticleEditCount(self, articleContribs, minimumEditCount, lastXDays):
        criteriaChecks = []
        if len(articleContribs) < minimumEditCount or datetime.now() - articleContribs[4][2] > timedelta(
            days=lastXDays
        ):
            criteriaChecks.append(
                CriteriaCheck(
                    False, "Das Benutzerkonto hat in den letzten 30 Tagen weniger als fünf Bearbeitungen im ANR."
                )
            )
        else:
            criteriaChecks.append(
                CriteriaCheck(True, "Das Benutzerkonto hat in den letzten 30 Tagen mehr als fünf Bearbeitungen im ANR.")
            )
        return criteriaChecks

    def checkUserEligibleForReviewGroup(self, userData):
        criteriaChecks = []
        criteriaChecks += self.checkGeneralEligibilityForPromotion(userData.user)
        criteriaChecks += self.checkGeneralEventLogCriterias(userData.logEntries)
        criteriaChecks += self.checkRegistrationTime(userData.registrationTime, 60)
        criteriaChecks += self.checkEditCount(userData.contribs, 300)
        criteriaChecks += self.checkArticleEditCount(userData.articleContribs, 300, userData.contribs[0][2], 1)
        # TODO: also check for 200 reviewed edits alternative
        criteriaChecks += self.checkSpacedEdits(userData.articleContribs, 15)
        criteriaChecks += self.checkMinimumEditedArticlePages(userData.articleContribs, 14)
        criteriaChecks += self.checkRecentArticleEditCount(userData.articleContribs, 5, 30)
        criteriaChecks += self.checkCustomSummaryEditCount(userData.contribs, 30)
        # TODO: check revert ratio

        return criteriaChecks

    def checkUserEligibleForAutoReviewGroup(self, userData):
        criteriaChecks = []
        criteriaChecks += self.checkGeneralEligibilityForPromotion(userData.user)
        criteriaChecks += self.checkGeneralEventLogCriterias(userData.logEntries)
        criteriaChecks += self.checkRegistrationTime(userData.registrationTime, 30)
        criteriaChecks += self.checkArticleEditCount(userData.articleContribs, 150, userData.contribs[0][2], 2)
        # TODO: also check for 50 reviewed edits alternative
        criteriaChecks += self.checkSpacedEdits(userData.articleContribs, 7)
        criteriaChecks += self.checkMinimumEditedArticlePages(userData.articleContribs, 8)
        criteriaChecks += self.checkRecentArticleEditCount(userData.articleContribs, 5, 30)
        criteriaChecks += self.checkCustomSummaryEditCount(userData.contribs, 20)

        return criteriaChecks

    def listNewUsers(self):
        alreadyChecked = set()
        startTime = datetime(2020, 1, 7)
        endTime = startTime + timedelta(days=1)
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
                criteriaChecks = self.checkUserEligibleForReviewGroup(self.getUserData(user, endTime))
                if not list(filter(lambda criteria: not criteria.met, criteriaChecks)):
                    usersToBePromoted.append(user)
                else:
                    criteriaChecks = self.checkUserEligibleForAutoReviewGroup(self.getUserData(user, endTime))
                    if not list(filter(lambda criteria: not criteria.met, criteriaChecks)):
                        usersToBePromotedToAutoReview.append(user)
        print("Aktive Sichter:")
        print(f"{len(usersToBePromoted)} Benutzer gefunden.")
        for user in sorted(usersToBePromoted):
            print(f"* {{{{Wikipedia:Gesichtete Versionen/Rechtevergabe/Vorlage|{user.username}}}}}")
        print()
        print("Passive Sichter:")
        print(f"{len(usersToBePromotedToAutoReview)} Benutzer gefunden.")
        for user in sorted(usersToBePromotedToAutoReview):
            print(f"* {{{{Wikipedia:Gesichtete Versionen/Rechtevergabe/Vorlage|{user.username}}}}}")

    def checkSingleUser(self):
        crit = self.checkUserEligibleForReviewGroup(
            self.getUserData(pywikibot.User(self.site, "Benutzer:Quild009"), datetime(2020, 1, 6))
        )
        if not list(filter(lambda criteria: not criteria.met, crit)):
            print(f"")


def main():
    locale.setlocale(locale.LC_ALL, "de_DE.utf8")
    pywikibot.handle_args()
    # Controller().checkSingleUser()
    Controller().listNewUsers()


if __name__ == "__main__":
    try:
        main()
    finally:
        pywikibot.stopme()
