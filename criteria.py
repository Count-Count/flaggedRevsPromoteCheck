#!/usr/bin/python
#
# (C) 2020 Count Count
#
# Distributed under the terms of the MIT license.

from __future__ import unicode_literals

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, cast

import pytz
import pywikibot
from pywikibot.data import mysql
from pywikibot.site import Namespace


@dataclass
class CriteriaCheck:
    met: bool
    text: str


@dataclass
class UserData:
    user: pywikibot.User
    editCount: int
    contribs: List[Any]
    articleContribs: List[Any]
    flaggedEditCount: int
    logEntries: List[Any]
    registrationTime: datetime
    flaggedRevsUserParams: Dict[str, str]


class CriteriaChecker:
    def __init__(self, site: pywikibot.site.BaseSite) -> None:
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
        params = {}
        if res:
            rawParams = re.split("\n", res[0][0].decode())
            for rawParam in rawParams:
                match = re.match("(.*)=(.*)", rawParam)
                if not match:
                    raise Exception(f"Unexpected flaggedRevs user param format in line {rawParam}")
                params[match.group(1)] = match.group(2)
        return params

    def getFlaggedRevisionCount(self, contribs) -> int:
        revs = ""
        for contrib in contribs:
            if contrib["ns"] == 0 or contrib["ns"] == Namespace.TEMPLATE:
                if len(revs) != 0:
                    revs += "|"
                revs += str(contrib["revid"])
        flaggedEdits = 0
        if len(revs) != 0:
            revisionsRequest = pywikibot.data.api.Request(
                site=self.site,
                parameters={
                    "action": "query",
                    "format": "json",
                    "prop": "revisions",
                    "rvprop": "flagged|ids",
                    "revids": revs,
                },
            )
            data = revisionsRequest.submit()
            pages = data["query"]["pages"]
            for page in pages:
                for revision in pages[page]["revisions"]:
                    if "flagged" in revision:
                        flaggedEdits += 1
        return flaggedEdits

    def getFlaggedEditCount(self, user: pywikibot.User, exactResults: bool) -> int:
        (_, _, lastEditTimestamp, _) = user.last_edit
        contribsRequest = pywikibot.data.api.Request(
            site=self.site,
            parameters={
                "action": "query",
                "format": "json",
                "list": "usercontribs",
                "uclimit": "5000",
                "ucuser": user.username,
                "ucnamespace": "0|6|10|14|828",
                "ucstart": lastEditTimestamp - timedelta(days=2),
            },
        )
        data = contribsRequest.submit()
        contribs = data["query"]["usercontribs"]
        flaggedEdits = self.getFlaggedRevisionCount(contribs[:500])
        contribsRest = contribs[500:]
        while contribsRest and (exactResults or flaggedEdits < 200):
            contribsPart = contribsRest[:500]
            contribsRest = contribsRest[500:]
            flaggedEdits += self.getFlaggedRevisionCount(contribsPart)
        return flaggedEdits

    def getUserData(self, user: pywikibot.User, endTime: datetime, exactResults: bool) -> UserData:
        contribs = list(user.contributions(total=5000, start=endTime))
        articleContribs = list(user.contributions(total=5000, start=endTime, namespaces=Namespace.MAIN))
        flaggedEditCount = self.getFlaggedEditCount(user, exactResults)
        return UserData(
            user,
            user.editCount(force=True),
            contribs,
            articleContribs,
            flaggedEditCount,
            self.site.logevents(page=f"User:{user.username}"),
            self.getUserRegistrationTimeSafe(user),
            self.getFlaggedRevsUserParams(user),
        )

    def getUserRegistrationTimeSafe(self, user: pywikibot.User) -> pywikibot.Timestamp:
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
        if user.is_blocked():
            criteriaChecks.append(CriteriaCheck(False, "Benutzer ist gesperrt."))
        else:
            criteriaChecks.append(CriteriaCheck(True, "Benutzer ist nicht gesperrt."))
        if self.site.isBot(user.username):
            criteriaChecks.append(CriteriaCheck(False, "Benutzer ist ein Bot."))
        else:
            criteriaChecks.append(CriteriaCheck(True, "Benutzer ist kein Bot."))
        return criteriaChecks

    def checkRegistrationTime(
        self, registrationTime: pywikibot.Timestamp, minimumAgeInDays: int
    ) -> List[CriteriaCheck]:
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

    def checkEditCount(self, editCount: int, minimumEditCount: int) -> List[CriteriaCheck]:
        criteriaChecks = []
        if editCount < minimumEditCount:
            criteriaChecks.append(
                CriteriaCheck(
                    False,
                    f"Das Benutzerkonto hat mit {editCount} Bearbeitungen weniger als die benötigten {minimumEditCount}.",
                )
            )
        else:
            criteriaChecks.append(
                CriteriaCheck(
                    True,
                    f"Das Benutzerkonto hat mit {editCount} Bearbeitungen mehr als die benötigten {minimumEditCount}.",
                )
            )
        return criteriaChecks

    def checkArticleEditCountOrFlaggedEditCount(
        self, flaggedRevsUserParams, flaggedEditCount: int, minimumEditCount: int, minimumFlaggedEditCount: int
    ) -> List[CriteriaCheck]:
        criteriaChecks = []

        totalContentEdits = (
            int(flaggedRevsUserParams["totalContentEdits"]) if "totalContentEdits" in flaggedRevsUserParams else 0
        )

        if totalContentEdits < minimumEditCount and flaggedEditCount < minimumFlaggedEditCount:
            criteriaChecks.append(
                CriteriaCheck(
                    False,
                    f"Das Benutzerkonto hat mit {totalContentEdits} Bearbeitungen im Artikelnamensraum weniger als die benötigten {minimumEditCount}"
                    f" und mit {flaggedEditCount} gesichteten Bearbeitungen weniger als die benötigten {minimumFlaggedEditCount}.",
                )
            )
        elif totalContentEdits >= minimumEditCount:
            criteriaChecks.append(
                CriteriaCheck(
                    True,
                    f"Das Benutzerkonto hat mit {totalContentEdits} Bearbeitungen im Artikelnamensraum mehr als die benötigten {minimumEditCount}.",
                )
            )
        else:
            criteriaChecks.append(
                CriteriaCheck(
                    True,
                    f"Das Benutzerkonto hat mit {flaggedEditCount} gesichteten Bearbeitungen mehr als die benötigten {minimumFlaggedEditCount}.",
                )
            )
        return criteriaChecks

    def checkMinimumEditedArticlePages(self, flaggedRevsUserParams, minimumSeparatePages: int) -> List[CriteriaCheck]:
        criteriaChecks = []
        uniqueContentPages = (
            flaggedRevsUserParams["uniqueContentPages"] if "uniqueContentPages" in flaggedRevsUserParams else ""
        )
        articlePageCount = 0 if not uniqueContentPages else len(list(uniqueContentPages.split(",")))
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
                    f"Das Benutzerkonto hat {articlePageCount} verschiedene Seiten im ANR bearbeitet. Damit ist die benötigte Mindestanzahl von {minimumSeparatePages} erreicht.",
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

    def checkCustomSummaryEditCount(
        self, flaggedRevsUserParams, minimumEditsWithCustomSummary: int
    ) -> List[CriteriaCheck]:
        criteriaChecks = []
        customSummaryCount = (
            int(flaggedRevsUserParams["editComments"]) if "editComments" in flaggedRevsUserParams else 0
        )
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
                    f"Das Benutzerkonto hat mit in den letzten 30 Tagen weniger als die benötigten {minimumEditCount} Bearbeitungen im ANR.",
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

    def checkRevertCountRatio(self, contribs, flaggedRevsUserParams, maxRatio: float) -> List[CriteriaCheck]:
        criteriaChecks = []
        if not "revertedEdits" in flaggedRevsUserParams:
            criteriaChecks.append(
                CriteriaCheck(
                    True,
                    "Es gibt keine Einträge zu zurückgesetzten Bearbeitungen.",
                )
            )
        else:
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
        criteriaChecks += self.checkEditCount(userData.editCount, 300)
        criteriaChecks += self.checkArticleEditCountOrFlaggedEditCount(
            userData.flaggedRevsUserParams, userData.flaggedEditCount, 300, 200
        )
        criteriaChecks += self.checkSpacedEdits(userData.contribs, 15)
        criteriaChecks += self.checkMinimumEditedArticlePages(userData.flaggedRevsUserParams, 14)
        criteriaChecks += self.checkRecentArticleEditCount(userData.articleContribs, 5, 30)
        criteriaChecks += self.checkCustomSummaryEditCount(userData.flaggedRevsUserParams, 30)
        criteriaChecks += self.checkRevertCountRatio(userData.contribs, userData.flaggedRevsUserParams, 0.03)

        return criteriaChecks

    def checkUserEligibleForAutoReviewGroup(self, userData: UserData) -> List[CriteriaCheck]:
        criteriaChecks: List[CriteriaCheck] = []
        criteriaChecks += self.checkGeneralEligibilityForPromotion(userData.user)
        criteriaChecks += self.checkGeneralEventLogCriterias(userData.logEntries)
        criteriaChecks += self.checkRegistrationTime(userData.registrationTime, 30)
        criteriaChecks += self.checkArticleEditCountOrFlaggedEditCount(
            userData.flaggedRevsUserParams, userData.flaggedEditCount, 150, 50
        )
        criteriaChecks += self.checkSpacedEdits(userData.articleContribs, 7)
        criteriaChecks += self.checkMinimumEditedArticlePages(userData.flaggedRevsUserParams, 8)
        criteriaChecks += self.checkCustomSummaryEditCount(userData.flaggedRevsUserParams, 20)

        return criteriaChecks
