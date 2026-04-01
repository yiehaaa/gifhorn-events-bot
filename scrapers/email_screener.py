"""
Email Screening & Filtering Engine

Filtert Gmail-Emails nach:
1. Sender-Whitelist (Regex-Patterns)
2. Keywords im Subject/Body
3. Attachments (count, type, size)

Scoring-System: 0.0-1.0 (Relevanz)
"""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EmailScreener:
    """Filter-Engine für Event-Submissions via Email"""

    def __init__(
        self,
        sender_patterns: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
        require_attachments: bool = True,
        min_attachment_size: int = 50_000,  # 50KB
        max_attachment_size: int = 10_000_000,  # 10MB
    ):
        """
        Args:
            sender_patterns: Liste von Regex-Patterns für Sender-Whitelist
                e.g., [".*@gifhorn.de", "info@.*\\.com"]
            keywords: Liste von Keywords zum Suchen in Subject/Body
                e.g., ["event", "plakat", "anmeldung", "veranstaltung"]
            require_attachments: Mindestens ein Anhang erforderlich?
            min_attachment_size: Minimale Dateigröße in Bytes
            max_attachment_size: Maximale Dateigröße in Bytes
        """
        self.sender_patterns = sender_patterns or []
        self.compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.sender_patterns]
        self.keywords = [kw.lower() for kw in (keywords or [])]
        self.require_attachments = require_attachments
        self.min_attachment_size = min_attachment_size
        self.max_attachment_size = max_attachment_size

    def filter_submissions(self, emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filtert Email-Liste und gibt nur relevante zurück.

        Args:
            emails: Liste von Emails (vom email_handler)
                    Format: {
                        "id": str,
                        "subject": str,
                        "sender": str,
                        "body": str,
                        "attachments": [{"filename": str, "size": int, "mime_type": str}]
                    }

        Returns:
            Liste von gefilterten Emails mit Score + matched_filters
        """
        screened = []

        for email in emails:
            score = self.rank_email(email)

            # Nur Emails mit Score >= 0.5 einbeziehen (brauchen mind. Anhang ODER Sender+Keywords)
            if score >= 0.5:
                filtered_info = self._get_matched_filters(email)
                email["screening_score"] = score
                email["matched_filters"] = filtered_info
                screened.append(email)

        # Sortiere nach Score (absteigend) für UI-Priorisierung
        screened.sort(key=lambda e: e.get("screening_score", 0), reverse=True)

        logger.info(f"📧 {len(emails)} Emails gefiltert → {len(screened)} relevant")
        return screened

    def rank_email(self, email: Dict[str, Any]) -> float:
        """
        Score eine Email nach Relevanz (0.0-1.0).

        Scoring:
        - Sender Whitelist Match: +0.5
        - Keywords im Subject/Body: +0.3
        - Valide Attachments: +0.2
        """
        score = 0.0
        sender = email.get("sender", "").lower()
        subject = email.get("subject", "").lower()
        body = email.get("body", "").lower()
        attachments = email.get("attachments", [])

        # 1. Sender-Check
        if self._check_sender(sender):
            score += 0.5
        elif not self.sender_patterns:
            # Wenn keine Whitelist definiert: neutral (+0.1)
            score += 0.1

        # 2. Keywords-Check
        keywords_found = self._check_keywords(subject, body)
        if keywords_found:
            score += 0.3

        # 3. Attachments-Check
        valid_attachments = self._validate_attachments(attachments)
        if valid_attachments:
            score += 0.2
        elif self.require_attachments:
            # Wenn Attachments required: reduziere Score um 50%
            score *= 0.5

        return min(score, 1.0)  # Cap at 1.0

    def _check_sender(self, sender: str) -> bool:
        """Überprüfe ob Sender in Whitelist passt"""
        if not self.compiled_patterns:
            return True  # Wenn keine Patterns: akzeptiere alle

        for pattern in self.compiled_patterns:
            if pattern.search(sender):
                return True
        return False

    def _check_keywords(self, subject: str, body: str) -> bool:
        """Überprüfe ob Keywords in Subject oder Body vorhanden"""
        if not self.keywords:
            return True  # Wenn keine Keywords: skip diesen Check

        combined = f"{subject} {body}".lower()
        return any(kw in combined for kw in self.keywords)

    def _validate_attachments(self, attachments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filtere Attachments nach:
        - MIME-Type (nur Bilder, PDFs, Dokumente)
        - Größe (min-max)

        Returns: Liste von validen Attachments
        """
        valid = []
        allowed_mimes = {
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

        for att in attachments:
            mime = att.get("mime_type", "").lower()
            size = att.get("size", 0)

            # Überprüfe MIME-Type
            if mime not in allowed_mimes:
                continue

            # Überprüfe Größe
            if size < self.min_attachment_size or size > self.max_attachment_size:
                continue

            valid.append(att)

        return valid

    def _get_matched_filters(self, email: Dict[str, Any]) -> Dict[str, Any]:
        """Sammle welche Filter diese Email matched"""
        sender = email.get("sender", "").lower()
        subject = email.get("subject", "").lower()
        body = email.get("body", "").lower()
        attachments = email.get("attachments", [])

        matched = {}

        # Sender
        if self._check_sender(sender):
            matched["sender"] = True

        # Keywords
        found_kws = []
        combined = f"{subject} {body}".lower()
        for kw in self.keywords:
            if kw in combined:
                found_kws.append(kw)
        if found_kws:
            matched["keywords"] = found_kws

        # Attachments
        valid_atts = self._validate_attachments(attachments)
        if valid_atts:
            matched["attachments"] = len(valid_atts)
            matched["attachment_filenames"] = [a.get("filename", "?") for a in valid_atts]

        return matched


# Globale Instanz (wird von config.py initialisiert)
email_screener: Optional[EmailScreener] = None
