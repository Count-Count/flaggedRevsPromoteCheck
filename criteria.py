#!/usr/bin/python
#
# (C) 2020 Count Count
#
# Distributed under the terms of the MIT license.

from __future__ import unicode_literals

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast, List, Any, Dict

import pytz

import pywikibot
import re
from pywikibot.data import mysql


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
    flaggedRevsUserParams: Dict[str, str]


class CriteriaChecker:
    def __init__(self, site) -> None:
        self.site = site
        self.timezone = pytz.timezone("Europe/Berlin")

    def getFlaggedRevsUserParams(self, user: pywikibot.User) -> Dict[str, str]:
        res = list(
            mysql.mysql_query(
                "SELECT frp_user_params from flaggedrevs_promote,user where user_id=frp_user_id and user_name=%s limit 1",
                dbname="dewiki",
                params=user.username,
            )
        )
        rawParams = re.split("\n", res[0][0].decode())
        params = {}
        for rawParam in rawParams:
            match = re.match("(.*)=(.*)", rawParam)
            if not match:
                raise Exception(f"Unexpected flaggedRevs user param format in line {rawParam}")
            params[match.group(1)] = match.group(2)
        return params

    def getUserData(self, user: pywikibot.User, endTime: datetime) -> UserData:
        contribs = list(user.contributions(total=5000, start=endTime))
        articleContribs = list(user.contributions(total=5000, start=endTime, namespace=""))
        return UserData(
            user,
            contribs,
            articleContribs,
            self.site.logevents(page=f"User:{user.username}"),
            self.getUserRegistrationTimeSafe(user),
            self.getFlaggedRevsUserParams(user),
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
                if "editor" in rightsEv.oldgroups and not "editor" in rightsEv.newgroups:
                    hadReviewRightsRemovedBefore = True
                    break
                if "autoreview" in rightsEv.oldgroups and not "autoreview" in rightsEv.newgroups:
                    hadReviewRightsRemovedBefore = True
                    break
            if ev.type() == "block" and ev.action() == "block":
                wasBlockedBefore = True
                break
        if hadReviewRightsRemovedBefore:
            criteriaChecks.append(CriteriaCheck(False, "Dem Benutzer wurden Sicherrechte schon einmal entzogen."))
        else:
            criteriaChecks.append(CriteriaCheck(True, "Dem Benutzer wurden Sicherrechte noch nie entzogen."))
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
        ageInDays = (datetime.now() - registrationTime).days
        if registrationTime > datetime.now() - timedelta(days=minimumAgeInDays):
            criteriaChecks.append(
                CriteriaCheck(
                    False,
                    f"Das Benutzerkonto wurde erst vor {ageInDays} Tagen angelegt. Es muss aber mindestens {minimumAgeInDays} Tage alt sein.",
                )
            )
        else:
            criteriaChecks.append(
                CriteriaCheck(
                    True,
                    f"Das Benutzerkonto wurde vor {ageInDays} Tagen angelegt. Das sind mehr als die benötigten {minimumAgeInDays} Tage.",
                )
            )
        return criteriaChecks

    def checkEditCount(self, contribs, minimumEditCount: int) -> List[CriteriaCheck]:
        criteriaChecks = []
        if len(contribs) < minimumEditCount:
            criteriaChecks.append(
                CriteriaCheck(
                    False,
                    f"Das Benutzerkonto hat mit {len(contribs)} Bearbeitungen weniger als die benötigten {minimumEditCount}.",
                )
            )
        else:
            criteriaChecks.append(
                CriteriaCheck(
                    True,
                    f"Das Benutzerkonto hat mit {len(contribs)} Bearbeitungen mehr als die benötigten {minimumEditCount}.",
                )
            )
        return criteriaChecks

    def checkArticleEditCount(
        self, articleContribs, minimumEditCount: int, excludeXDaysBeforeLastEdit: int
    ) -> List[CriteriaCheck]:
        relevantEdits = [
            contrib
            for contrib in articleContribs
            if contrib[2] < datetime.now() - timedelta(days=excludeXDaysBeforeLastEdit)
        ]

        criteriaChecks = []
        if len(relevantEdits) < minimumEditCount:
            criteriaChecks.append(
                CriteriaCheck(
                    False,
                    f"Das Benutzerkonto hat mit {len(relevantEdits)} Bearbeitungen im Artikelnamensraum weniger als die benötigten {minimumEditCount}. Änderungen "
                    + (
                        "des letzten Tages"
                        if excludeXDaysBeforeLastEdit == 1
                        else f"der letzten {excludeXDaysBeforeLastEdit} Tage"
                    )
                    + " wurden nicht berücksichtigt.",
                )
            )
        else:
            criteriaChecks.append(
                CriteriaCheck(
                    True,
                    f"Das Benutzerkonto hat mit {len(relevantEdits)} Bearbeitungen im Artikelnamensraum mehr als die benötigten {minimumEditCount}. Änderungen "
                    + (
                        "des letzten Tages"
                        if excludeXDaysBeforeLastEdit == 1
                        else f"der letzten {excludeXDaysBeforeLastEdit} Tage"
                    )
                    + " wurden nicht berücksichtigt.",
                )
            )
        return criteriaChecks

    def checkMinimumEditedArticlePages(self, articleContribs, minimumSeparatePages: int) -> List[CriteriaCheck]:
        criteriaChecks = []
        articlePageCount = len(set([contrib[0].title() for contrib in articleContribs]))
        if articlePageCount < minimumSeparatePages:
            criteriaChecks.append(
                CriteriaCheck(
                    False,
                    f"Das Benutzerkonto hat nur {articlePageCount} verschiedene Seiten im ANR bearbeitet. Das sind weniger als die benötigten mehr als {minimumSeparatePages} Seiten.",
                )
            )
        else:
            criteriaChecks.append(
                CriteriaCheck(
                    True,
                    f"Das Benutzerkonto hat mit {articlePageCount} verschiedene Seiten im ANR bearbeitet. Damit ist die benötigte Mindestanzahl von {minimumSeparatePages} erreicht.",
                )
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
                        False,
                        f"Das Benutzerkonto hat mit {spacedEditCount} Bearbeitungen, die untereinander einen Mindestabstand von jeweils 3 Tagen aufweisen, weniger als die benötigten {minimumSpacedEdits}.",
                    )
                )
            else:
                criteriaChecks.append(
                    CriteriaCheck(
                        True,
                        f"Das Benutzerkonto hat mit {spacedEditCount} Bearbeitungen, die untereinander einen Mindestabstand von jeweils 3 Tagen aufweisen, die benötigte Anzahl von {minimumSpacedEdits} erreicht.",
                    )
                )
        else:
            criteriaChecks.append(
                CriteriaCheck(
                    False,
                    f"Das Benutzerkonto hat noch keine Bearbeitungen, und damit auch weniger als {minimumSpacedEdits} Bearbeitungen mit mindestens drei Tagen Abstand.",
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
                    f"Das Benutzerkonto hat nur bei {customSummaryCount} Bearbeitungen aktiv die Zusammenfassungszeile genutzt. Das sind weniger als die benötigten {minimumEditsWithCustomSummary} Bearbeitungen.",
                )
            )
        else:
            criteriaChecks.append(
                CriteriaCheck(
                    True,
                    f"Das Benutzerkonto hat bei {customSummaryCount} Bearbeitungen aktiv die Zusammenfassungszeile genutzt. Das sind mehr als die benötigten {minimumEditsWithCustomSummary} Bearbeitungen.",
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
                    False,
                    f"Das Benutzerkonto hat mit in den letzten 30 Tagen weniger als die benötigten {minimumEditCount}.",
                )
            )
        else:
            criteriaChecks.append(
                CriteriaCheck(
                    True,
                    f"Das Benutzerkonto hat in den letzten 30 Tagen mehr als die benötigten {minimumEditCount} Bearbeitungen im ANR.",
                )
            )
        return criteriaChecks

    def checkRevertCountRatio(self, contribs, flaggedRevsUserParams, maxRatio):
        criteriaChecks = []
        actRatio = float(flaggedRevsUserParams["revertedEdits"]) / len(contribs)
        if actRatio > maxRatio:
            criteriaChecks.append(
                CriteriaCheck(
                    False,
                    f"Das Benutzerkonto hat mit {actRatio*100:0.2f}% einen zu großen Anteil an zurückgesetzten Bearbeitungen. Maximal {maxRatio*100:0.0f}% sind erlaubt.",
                )
            )
        else:
            criteriaChecks.append(
                CriteriaCheck(
                    True,
                    f"Das Benutzerkonto hat mit {actRatio*100:0.2f}% weniger als den maximal erlaubten Anteil an zurückgesetzten Bearbeitungen ({maxRatio*100:0.0f}%).",
                )
            )
        return criteriaChecks

    def checkUserEligibleForReviewGroup(self, userData: UserData) -> List[CriteriaCheck]:
        criteriaChecks: List[CriteriaCheck] = []
        criteriaChecks += self.checkGeneralEligibilityForPromotion(userData.user)
        criteriaChecks += self.checkGeneralEventLogCriterias(userData.logEntries)
        criteriaChecks += self.checkRegistrationTime(userData.registrationTime, 60)
        criteriaChecks += self.checkEditCount(userData.contribs, 300)
        criteriaChecks += self.checkArticleEditCount(userData.articleContribs, 300, 1)
        # TODO: also check for 200 reviewed edits alternative
        criteriaChecks += self.checkSpacedEdits(userData.articleContribs, 15)
        criteriaChecks += self.checkMinimumEditedArticlePages(userData.articleContribs, 14)
        criteriaChecks += self.checkRecentArticleEditCount(userData.articleContribs, 5, 30)
        criteriaChecks += self.checkCustomSummaryEditCount(userData.contribs, 30)
        criteriaChecks += self.checkRevertCountRatio(userData.contribs, userData.flaggedRevsUserParams, 0.03)

        return criteriaChecks

    def checkUserEligibleForAutoReviewGroup(self, userData: UserData) -> List[CriteriaCheck]:
        criteriaChecks: List[CriteriaCheck] = []
        criteriaChecks += self.checkGeneralEligibilityForPromotion(userData.user)
        criteriaChecks += self.checkGeneralEventLogCriterias(userData.logEntries)
        criteriaChecks += self.checkRegistrationTime(userData.registrationTime, 30)
        criteriaChecks += self.checkArticleEditCount(userData.articleContribs, 150, 2)
        # TODO: also check for 50 reviewed edits alternative
        criteriaChecks += self.checkSpacedEdits(userData.articleContribs, 7)
        criteriaChecks += self.checkMinimumEditedArticlePages(userData.articleContribs, 8)
        criteriaChecks += self.checkCustomSummaryEditCount(userData.contribs, 20)

        return criteriaChecks
