"""
Notification Service — handles alerts (e.g., email notification for escalations).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("operdai.notifications")


async def send_escalation_notification(
    client_name: str,
    lead_name: str,
    reason: str,
    draft_content: str,
    recipient_email: str,
) -> bool:
    """
    Sends an email alert to the agency operator when a lead escalates.
    In development/testing, it logs the alert details.
    In production, it can use an SMTP server or transaction provider (SendGrid/Mailgun).
    """
    subject = f"⚠️ Escalation Alert: {lead_name} needs human review ({client_name})"
    body = (
        f"Hi Operator,\n\n"
        f"A lead from {client_name} requires human review:\n"
        f"- Lead Name: {lead_name}\n"
        f"- Reason for Escalation: {reason}\n\n"
        f"AI Proposed Draft:\n"
        f"\" {draft_content} \"\n\n"
        f"Please log into your dashboard to approve, reject, or edit this message."
    )

    logger.warning(
        f"--- OUTBOUND EMAIL NOTIFICATION ---\n"
        f"To: {recipient_email}\n"
        f"Subject: {subject}\n"
        f"Body:\n{body}\n"
        f"------------------------------------"
    )

    # In production, integrate with a real provider:
    # try:
    #     import resend
    #     resend.api_key = settings.resend_api_key
    #     resend.Emails.send({
    #         "from": "OperdAI Alerts <alerts@operdai.com>",
    #         "to": recipient_email,
    #         "subject": subject,
    #         "text": body,
    #     })
    # except Exception as e:
    #     logger.error(f"Failed to send email notification: {e}")
    #     return False

    return True
