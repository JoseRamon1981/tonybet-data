import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv(override=True)


@dataclass
class Config:
    # Tonybet credentials
    tonybet_url: str = "https://tonybet.com"
    tonybet_username: str = field(default_factory=lambda: os.getenv("TONYBET_USERNAME", ""))
    tonybet_password: str = field(default_factory=lambda: os.getenv("TONYBET_PASSWORD", ""))

    # Claude API
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    claude_model: str = "claude-sonnet-4-6"

    # Responsible gambling limits
    max_daily_stake: float = float(os.getenv("MAX_DAILY_STAKE", "50"))
    max_single_bet: float = float(os.getenv("MAX_SINGLE_BET", "10"))
    min_odds: float = float(os.getenv("MIN_ODDS", "1.01"))
    max_odds: float = float(os.getenv("MAX_ODDS", "10.0"))

    # Value betting thresholds
    min_ev_threshold: float = float(os.getenv("MIN_EV_THRESHOLD", "0.01"))   # 1% min EV
    kelly_fraction: float = float(os.getenv("KELLY_FRACTION", "0.25"))        # Quarter-Kelly (safer)

    # Playwright settings
    headless: bool = os.getenv("HEADLESS", "true").lower() == "true"
    timeout_ms: int = int(os.getenv("TIMEOUT_MS", "30000"))

    def validate(self):
        if not self.tonybet_username:
            raise ValueError("TONYBET_USERNAME no está configurado")
        if not self.tonybet_password:
            raise ValueError("TONYBET_PASSWORD no está configurado")
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY no está configurado")


config = Config()
