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

import os
import httpx
from typing import Optional

# Import logging module
from .logger import get_logger


class TelegramNotifier:
    """
    Telegram notification client for sending urgent messages and human help requests.
    
    Uses the Telegram Bot API to send messages to a configured chat.
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
            self.logger.info(f"TelegramNotifier initialized for chat_id: {self.chat_id}")
    
    def _get_api_url(self, method: str) -> str:
        """Get the full API URL for a given Telegram Bot API method."""
        return f"https://api.telegram.org/bot{self.bot_token}/{method}"
    
    async def _send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Send a message via Telegram API.
        
        Args:
            text: Message text to send
            parse_mode: Parse mode for formatting (Markdown or HTML)
            
        Returns:
            True if message was sent successfully, False otherwise
        """
        if not self.bot_token or not self.chat_id:
            self.logger.warning("Telegram credentials not configured, skipping notification")
            return False
        
        url = self._get_api_url("sendMessage")
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        
        try:
            with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                
                if result.get("ok"):
                    self.logger.info("Telegram message sent successfully")
                    return True
                else:
                    self.logger.error(f"Telegram API error: {result.get('description')}")
                    return False
                    
        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error sending Telegram message: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Error sending Telegram message: {e}")
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
        client_email: Optional[str] = None
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
        
        message_parts.extend([
            "",
            "*Context:*",
            context[:500]  # Limit context length
        ])
        
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
