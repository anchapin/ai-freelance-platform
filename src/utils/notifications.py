"""
Telegram Notifications Module

Provides Telegram notification functionality for urgent alerts and human-in-the-loop requests.
Uses httpx for async HTTP requests to the Telegram Bot API.

Environment Variables:
    TELEGRAM_BOT_TOKEN: Telegram bot token
    TELEGRAM_CHAT_ID: Target chat ID for notifications

Usage:
    from src.utils.notifications import TelegramNotifier

    notifier = TelegramNotifier()
    notifier.send_urgent_message("System alert: High error rate detected")
    notifier.request_human_help("task-123", "Task failed after 3 retries")
"""

import asyncio
import os
import httpx
from typing import Optional

# Import logging module
from .logger import get_logger
from ..config import get_telegram_api_url

# Retry configuration for Telegram notifications
MAX_NOTIFICATION_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0
BACKOFF_MULTIPLIER = 2.0


class TelegramNotifier:
    """
    Telegram notification client for sending urgent messages and human help requests.

    Uses the Telegram Bot API to send messages to a configured chat.
    Includes retry logic with exponential backoff for reliability.
    """

    def __init__(self):
        """Initialize the Telegram notifier with credentials from environment variables."""
        self.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        self.logger = get_logger(__name__)

        # Check if credentials are configured
        if not self.bot_token or not self.chat_id:
            self.logger.warning(
                "Telegram credentials not configured. "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables."
            )
        else:
            self.logger.info(
                f"TelegramNotifier initialized for chat_id: {self.chat_id}"
            )

    def _get_api_url(self, method: str) -> str:
        """Get the full API URL for a given Telegram Bot API method."""
        api_url = get_telegram_api_url()
        return f"{api_url}/bot{self.bot_token}/{method}"

    async def _send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Send a message via Telegram API with retry and exponential backoff.

        Args:
            text: Message text to send
            parse_mode: Parse mode for formatting (Markdown or HTML)

        Returns:
            True if message was sent successfully, False otherwise
        """
        if not self.bot_token or not self.chat_id:
            self.logger.warning(
                "Telegram credentials not configured, skipping notification"
            )
            return False

        url = self._get_api_url("sendMessage")
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": parse_mode}

        last_error = None
        backoff = INITIAL_BACKOFF_SECONDS

        for attempt in range(1, MAX_NOTIFICATION_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    result = response.json()

                    if result.get("ok"):
                        self.logger.info("Telegram message sent successfully")
                        return True
                    else:
                        last_error = result.get("description", "Unknown API error")
                        self.logger.error(f"Telegram API error: {last_error}")

            except httpx.HTTPError as e:
                last_error = str(e)
                self.logger.error(
                    f"HTTP error sending Telegram message (attempt {attempt}/{MAX_NOTIFICATION_RETRIES}): {e}"
                )
            except Exception as e:
                last_error = str(e)
                self.logger.error(
                    f"Error sending Telegram message (attempt {attempt}/{MAX_NOTIFICATION_RETRIES}): {e}"
                )

            if attempt < MAX_NOTIFICATION_RETRIES:
                self.logger.info(f"Retrying Telegram notification in {backoff:.1f}s...")
                await asyncio.sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER

        self.logger.error(
            f"Failed to send Telegram notification after {MAX_NOTIFICATION_RETRIES} attempts. "
            f"Last error: {last_error}"
        )
        return False

    async def send_urgent_message(self, message: str) -> bool:
        """
        Send an urgent message notification via Telegram.

        Formats the message with an urgent emoji prefix and sends it.

        Args:
            message: The urgent message to send

        Returns:
            True if message was sent successfully, False otherwise
        """
        formatted_message = f"🚨 *URGENT ALERT*\n\n{message}"
        return await self._send_message(formatted_message)

    async def request_human_help(
        self,
        task_id: str,
        context: str,
        amount_paid: Optional[int] = None,
        domain: Optional[str] = None,
        client_email: Optional[str] = None,
    ) -> bool:
        """
        Request human assistance for an escalated task.

        Sends a formatted message with task details to alert human reviewers.

        Args:
            task_id: The ID of the task requiring human attention
            context: Additional context about why human help is needed
            amount_paid: Amount paid for the task in cents (optional)
            domain: The domain of the task (optional)
            client_email: Client email for contact (optional)

        Returns:
            True if message was sent successfully, False otherwise
        """
        # Format amount if provided
        amount_str = ""
        if amount_paid is not None:
            amount_dollars = amount_paid / 100
            amount_str = f"${amount_dollars:.2f}"

        # Build the formatted message
        message_parts = [
            "🔴 *HUMAN ASSISTANCE REQUIRED*",
            "",
            f"*Task ID:* `{task_id}`",
        ]

        if domain:
            message_parts.append(f"*Domain:* {domain}")

        if amount_str:
            message_parts.append(f"*Amount Paid:* {amount_str}")

        if client_email:
            message_parts.append(f"*Client Email:* {client_email}")

        message_parts.extend(
            [
                "",
                "*Context:*",
                context[:500],  # Limit context length
            ]
        )

        formatted_message = "\n".join(message_parts)

        self.logger.info(f"Requesting human help for task {task_id}")
        return await self._send_message(formatted_message)


# Module-level instance for convenience
# Initialize lazily when needed
_notifier: Optional[TelegramNotifier] = None


def get_notifier() -> TelegramNotifier:
    """
    Get the singleton TelegramNotifier instance.

    Returns:
        The TelegramNotifier instance
    """
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier
