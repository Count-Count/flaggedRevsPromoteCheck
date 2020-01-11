#!/usr/bin/python
#
# (C) 2020 Count Count
#
# Distributed under the terms of the MIT license.

from __future__ import unicode_literals

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast, List, Any

import pytz

import pywikibot


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


class CriteriaChecker:
    def __init__(self, site) -> None:
        self.site = site
        self.timezone = pytz.timezone("Europe/Berlin")

    def getUserData(self, user: pywikibot.User, endTime: datetime) -> UserData:
        contribs = list(user.contributions(total=5000, start=endTime))
        return UserData(
            user,
            contribs,
            [contrib for contrib in contribs if contrib[0].namespace() == 0],
            self.site.logevents(page=f"User:{user.username}"),
            self.getUserRegistrationTimeSafe(user),
        )

    def getUserRegistrationTimeSafe(self, user: pywikibot.User) -> datetime:
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

    def checkGeneralEventLogCriterias(self, events) -> List[CriteriaCheck]:
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

    def checkGeneralEligibilityForPromotion(self, user: pywikibot.User) -> List[CriteriaCheck]:
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

    def checkRegistrationTime(self, registrationTime, minimumAgeInDays: int) -> List[CriteriaCheck]:
        criteriaChecks = []
        if not registrationTime:
            raise NotImplementedError
        if registrationTime > datetime.now() - timedelta(days=minimumAgeInDays):
            criteriaChecks.append(CriteriaCheck(False, "Das Benutzerkonto wurde vor weniger als 60 Tagen angelegt."))
        else:
            criteriaChecks.append(CriteriaCheck(True, "Das Benutzerkonto wurde vor mehr als 60 Tagen angelegt."))
        return criteriaChecks

    def checkEditCount(self, contribs, minimumEditCount: int) -> List[CriteriaCheck]:
        criteriaChecks = []
        if len(contribs) < minimumEditCount:
            criteriaChecks.append(CriteriaCheck(False, "Das Benutzerkonto hat weniger als 300 Bearbeitungen."))
        else:
            criteriaChecks.append(CriteriaCheck(True, "Das Benutzerkonto hat mindestens 300 Bearbeitungen."))
        return criteriaChecks

    def checkArticleEditCount(
        self, articleContribs, minimumEditCount: int, mostRecentEditTime, excludeXDaysBeforeLastEdit: int
    ) -> List[CriteriaCheck]:
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

    def checkMinimumEditedArticlePages(self, articleContribs, minimumSeparatePages: int) -> List[CriteriaCheck]:
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

    def checkSpacedEdits(self, contribs, minimumSpacedEdits: int) -> List[CriteriaCheck]:
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

    def checkCustomSummaryEditCount(self, contribs, minimumEditsWithCustomSummary: int) -> List[CriteriaCheck]:
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

    def checkRecentArticleEditCount(self, articleContribs, minimumEditCount: int, lastXDays) -> List[CriteriaCheck]:
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

    def checkUserEligibleForReviewGroup(self, userData: UserData) -> List[CriteriaCheck]:
        criteriaChecks: List[CriteriaCheck] = []
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

    def checkUserEligibleForAutoReviewGroup(self, userData: UserData) -> List[CriteriaCheck]:
        criteriaChecks: List[CriteriaCheck] = []
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
