"""
Email Approval Dashboard - FastAPI Web-UI für Email-Submissions

Ermöglicht manuelle Review und Genehmigung von Email-Einreichungen.
Zeigt: Sender, Subject, Body, Anhänge (Galerie), Screening-Score, Buttons
"""

from __future__ import annotations

import asyncio
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse

from database import db

logger = logging.getLogger(__name__)

# Router für Email-Approvals
router = APIRouter(prefix="/api/emails", tags=["email-submissions"])


async def _kick_email_conversion_pipeline() -> None:
    """Nach Web-Freigabe: Mail→Event + erste Telegram-Freigabe wie nach Telegram-Batch."""
    try:
        from main import (
            notify_telegram_first_round_for_new_events,
            process_approved_email_submissions,
        )

        converted = await process_approved_email_submissions(
            manual_revision_after_convert=True
        )
        await notify_telegram_first_round_for_new_events(converted)
    except Exception:
        logger.exception("Email-Konvertierung nach Dashboard-Freigabe fehlgeschlagen")


@router.get("/pending", response_model=List[dict])
async def get_pending_emails():
    """
    Hole alle unbearbeiteten Email-Submissions.

    Returns:
        Liste von Emails mit allen Metadaten
    """
    if not db.conn:
        db.connect()

    pending = db.get_pending_email_submissions()
    logger.info(f"📧 Dashboard: {len(pending)} pending emails")
    return pending


@router.get("/pending/count")
async def get_pending_count():
    """Schnelle Count-Query für Badge/Notification"""
    if not db.conn:
        db.connect()

    pending = db.get_pending_email_submissions()
    return {"count": len(pending), "status": "ok"}


@router.post("/{email_id}/approve")
async def approve_email(email_id: int, approved_by: str = "web-dashboard"):
    """
    Genehmige eine Email-Submission.

    Args:
        email_id: ID der Email
        approved_by: Wer hat genehmigt (default: web-dashboard)
    """
    if not db.conn:
        db.connect()

    try:
        db.set_email_approval(email_id, approved=True, approved_by=approved_by)
        logger.info(f"✅ Email {email_id} freigegeben via Dashboard")
        asyncio.create_task(_kick_email_conversion_pipeline())
        return {"status": "approved", "email_id": email_id}
    except Exception as e:
        logger.error(f"❌ Fehler bei Email-Approval: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{email_id}/reject")
async def reject_email(email_id: int, approved_by: str = "web-dashboard"):
    """
    Lehne eine Email-Submission ab.

    Args:
        email_id: ID der Email
        approved_by: Wer hat abgelehnt
    """
    if not db.conn:
        db.connect()

    try:
        db.set_email_approval(email_id, approved=False, approved_by=approved_by)
        logger.info(f"❌ Email {email_id} abgelehnt via Dashboard")
        return {"status": "rejected", "email_id": email_id}
    except Exception as e:
        logger.error(f"❌ Fehler bei Email-Rejection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_class=HTMLResponse)
async def dashboard_html():
    """
    Rendert die Email-Approval Dashboard HTML-Page.
    Einfache, responsive UI mit Bildgalerie und Approve/Reject Buttons.
    """
    return """
    <!DOCTYPE html>
    <html lang="de">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Email Approval Dashboard</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }

            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #f5f5f5;
                padding: 20px;
            }

            .container {
                max-width: 1200px;
                margin: 0 auto;
            }

            header {
                background: white;
                padding: 20px;
                border-radius: 8px;
                margin-bottom: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }

            h1 {
                font-size: 28px;
                margin-bottom: 10px;
                color: #333;
            }

            .status {
                font-size: 14px;
                color: #666;
            }

            .pending-count {
                display: inline-block;
                background: #ff6b6b;
                color: white;
                padding: 5px 12px;
                border-radius: 20px;
                font-weight: bold;
                margin-left: 10px;
            }

            .pending-count.zero {
                background: #51cf66;
            }

            .email-list {
                display: grid;
                gap: 20px;
            }

            .email-card {
                background: white;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                transition: transform 0.2s, box-shadow 0.2s;
            }

            .email-card:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            }

            .email-card.pending {
                border-left: 4px solid #ff6b6b;
            }

            .email-card.approved {
                border-left: 4px solid #51cf66;
                opacity: 0.6;
            }

            .email-card.rejected {
                border-left: 4px solid #868e96;
                opacity: 0.6;
            }

            .email-header {
                margin-bottom: 15px;
                padding-bottom: 15px;
                border-bottom: 1px solid #eee;
            }

            .email-from {
                font-size: 14px;
                color: #666;
                margin-bottom: 5px;
            }

            .email-subject {
                font-size: 18px;
                font-weight: 600;
                color: #333;
            }

            .email-meta {
                display: flex;
                gap: 20px;
                margin-top: 10px;
                font-size: 13px;
                color: #888;
            }

            .score {
                display: inline-block;
                background: #e7f5ff;
                padding: 4px 10px;
                border-radius: 4px;
                font-weight: 500;
            }

            .email-body {
                margin-bottom: 15px;
                line-height: 1.6;
                color: #555;
                white-space: pre-wrap;
                word-wrap: break-word;
                max-height: 300px;
                overflow: auto;
            }

            .attachments {
                margin-bottom: 15px;
                padding: 15px;
                background: #f9f9f9;
                border-radius: 6px;
            }

            .attachments-title {
                font-size: 13px;
                font-weight: 600;
                color: #333;
                margin-bottom: 10px;
            }

            .gallery {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
                gap: 10px;
            }

            .gallery-item {
                position: relative;
                background: #e9ecef;
                border-radius: 6px;
                overflow: hidden;
                aspect-ratio: 1;
                cursor: pointer;
            }

            .gallery-item img {
                width: 100%;
                height: 100%;
                object-fit: cover;
            }

            .gallery-item::after {
                content: attr(data-filename);
                position: absolute;
                bottom: 0;
                left: 0;
                right: 0;
                background: rgba(0,0,0,0.7);
                color: white;
                padding: 5px;
                font-size: 11px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }

            .file-item {
                padding: 10px;
                background: white;
                border-radius: 4px;
                font-size: 13px;
                border: 1px solid #ddd;
            }

            .filters {
                font-size: 12px;
                color: #666;
                margin-top: 10px;
                padding: 10px;
                background: #f0f0f0;
                border-radius: 4px;
            }

            .badge {
                display: inline-block;
                background: #e7f5ff;
                color: #0066cc;
                padding: 3px 8px;
                border-radius: 3px;
                font-size: 12px;
                margin-right: 5px;
                margin-bottom: 5px;
            }

            .actions {
                display: flex;
                gap: 10px;
                padding-top: 15px;
                border-top: 1px solid #eee;
            }

            button {
                flex: 1;
                padding: 10px 20px;
                border: none;
                border-radius: 6px;
                font-weight: 600;
                cursor: pointer;
                font-size: 14px;
                transition: all 0.2s;
            }

            .btn-approve {
                background: #51cf66;
                color: white;
            }

            .btn-approve:hover {
                background: #40c057;
            }

            .btn-reject {
                background: #ff6b6b;
                color: white;
            }

            .btn-reject:hover {
                background: #fa5252;
            }

            button:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }

            .loading {
                text-align: center;
                padding: 40px;
                color: #666;
            }

            .error {
                background: #ffe0e0;
                color: #c41e3a;
                padding: 15px;
                border-radius: 6px;
                margin-bottom: 20px;
            }

            .empty {
                text-align: center;
                padding: 40px;
                color: #999;
            }

            .empty-icon {
                font-size: 48px;
                margin-bottom: 10px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>📧 Email-Approval Dashboard</h1>
                <p class="status">
                    Verwalte Event-Einreichungen per Email
                    <span class="pending-count" id="badge">…</span>
                </p>
            </header>

            <div id="error-container"></div>
            <div id="email-list" class="email-list">
                <div class="loading">⏳ Lade Emails…</div>
            </div>
        </div>

        <script>
        async function loadEmails() {
            try {
                const response = await fetch('/api/emails/pending');
                if (!response.ok) throw new Error('Fehler beim Laden');
                const emails = await response.json();

                // Update badge
                const badge = document.getElementById('badge');
                badge.textContent = emails.length;
                badge.classList.toggle('zero', emails.length === 0);

                // Render emails
                const container = document.getElementById('email-list');
                if (emails.length === 0) {
                    container.innerHTML = `
                        <div class="empty">
                            <div class="empty-icon">✅</div>
                            <p>Keine ausstehenden Emails!</p>
                        </div>
                    `;
                    return;
                }

                container.innerHTML = emails.map(email => `
                    <div class="email-card pending" id="email-${email.id}">
                        <div class="email-header">
                            <div class="email-from">📤 ${escapeHtml(email.sender_email)}</div>
                            <div class="email-subject">${escapeHtml(email.subject)}</div>
                            <div class="email-meta">
                                <span>📅 ${new Date(email.created_at).toLocaleString('de-DE')}</span>
                                <span class="score">Score: ${(email.screening_score * 100).toFixed(0)}%</span>
                            </div>
                        </div>

                        <div class="email-body">${escapeHtml(email.body_text || '')}</div>

                        ${renderAttachments(email)}
                        ${renderFilters(email.matched_filters)}

                        <div class="actions">
                            <button class="btn-approve" onclick="approveEmail(${email.id})">
                                ✅ Freigeben
                            </button>
                            <button class="btn-reject" onclick="rejectEmail(${email.id})">
                                ❌ Ablehnen
                            </button>
                        </div>
                    </div>
                `).join('');

            } catch (error) {
                const container = document.getElementById('email-list');
                container.innerHTML = `<div class="error">❌ Fehler: ${escapeHtml(error.message)}</div>`;
            }
        }

        function renderAttachments(email) {
            const attachments = email.attachment_urls || {};
            if (Object.keys(attachments).length === 0) return '';

            const items = Object.entries(attachments).map(([name, url]) => {
                const isImage = /\\.(jpg|jpeg|png|gif|webp)$/i.test(url);
                if (isImage) {
                    return `<div class="gallery-item" data-filename="${escapeHtml(name)}">
                        <img src="${escapeHtml(url)}" alt="${escapeHtml(name)}" loading="lazy">
                    </div>`;
                }
                return `<div class="file-item">📄 ${escapeHtml(name)}</div>`;
            });

            const hasImages = Object.entries(attachments).some(([_, url]) =>
                /\\.(jpg|jpeg|png|gif|webp)$/i.test(url)
            );

            return `
                <div class="attachments">
                    <div class="attachments-title">📎 Anhänge (${Object.keys(attachments).length})</div>
                    <div class="gallery">${items.join('')}</div>
                </div>
            `;
        }

        function renderFilters(filters) {
            if (!filters || Object.keys(filters).length === 0) return '';

            let badges = '';
            if (filters.sender) badges += '<span class="badge">✓ Sender-Whitelist</span>';
            if (filters.keywords) {
                badges += '<span class="badge">✓ Keywords: ' + filters.keywords.join(', ') + '</span>';
            }
            if (filters.attachments) {
                badges += '<span class="badge">✓ ' + filters.attachments + ' Anhang(e)</span>';
            }

            return `<div class="filters">${badges}</div>`;
        }

        async function approveEmail(emailId) {
            if (!confirm('Email freigeben?')) return;
            try {
                const response = await fetch(`/api/emails/${emailId}/approve`, { method: 'POST' });
                if (!response.ok) throw new Error('Fehler');
                document.getElementById(`email-${emailId}`).classList.add('approved');
                document.getElementById(`email-${emailId}`).querySelector('.actions').innerHTML =
                    '<div style="padding:10px;color:#51cf66;text-align:center;">✅ Freigegeben</div>';
                loadEmails(); // Reload badge
            } catch (error) {
                alert('Fehler: ' + error.message);
            }
        }

        async function rejectEmail(emailId) {
            if (!confirm('Email ablehnen?')) return;
            try {
                const response = await fetch(`/api/emails/${emailId}/reject`, { method: 'POST' });
                if (!response.ok) throw new Error('Fehler');
                document.getElementById(`email-${emailId}`).classList.add('rejected');
                document.getElementById(`email-${emailId}`).querySelector('.actions').innerHTML =
                    '<div style="padding:10px;color:#868e96;text-align:center;">❌ Abgelehnt</div>';
                loadEmails(); // Reload badge
            } catch (error) {
                alert('Fehler: ' + error.message);
            }
        }

        function escapeHtml(text) {
            const map = {
                '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
            };
            return text.replace(/[&<>"']/g, m => map[m]);
        }

        // Load on page load und refresh every 30s
        loadEmails();
        setInterval(loadEmails, 30000);
        </script>
    </body>
    </html>
    """


# INTEGRATION IN BESTEHENDER FASTAPI APP
# Verwende in web/main.py (oder wo der FastAPI-Server ist):
# from web.email_approval_dashboard import router as email_router
# app.include_router(email_router)
