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
    min_prob_threshold: float = float(os.getenv("MIN_PROB_THRESHOLD", "0.75"))  # 75% min prob
    kelly_fraction: float = float(os.getenv("KELLY_FRACTION", "0.25"))        # Quarter-Kelly (safer)

    # The Odds API (fuente principal de datos — https://the-odds-api.com/)
    odds_api_key: str = field(default_factory=lambda: os.getenv("ODDS_API_KEY", ""))
    # Máximo de requests por ejecución (tier gratuito: 500/mes → 8/ejecución con 2/día)
    odds_api_max_requests: int = int(os.getenv("ODDS_API_MAX_REQUESTS", "8"))

    # Playwright settings (fallback si no hay ODDS_API_KEY)
    headless: bool = os.getenv("HEADLESS", "true").lower() == "true"
    timeout_ms: int = int(os.getenv("TIMEOUT_MS", "30000"))

    def validate(self):
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY no está configurado")
        # Data source: need either The Odds API key OR Tonybet credentials
        has_odds_api = bool(self.odds_api_key)
        has_tonybet  = bool(self.tonybet_username and self.tonybet_password)
        if not has_odds_api and not has_tonybet:
            raise ValueError(
                "No hay fuente de datos configurada. "
                "Configura ODDS_API_KEY (https://the-odds-api.com) "
                "o TONYBET_USERNAME + TONYBET_PASSWORD"
            )


config = Config()
