"""
Playwright-based bet executor: places bets on Tonybet automatically.
Requires an active logged-in session from the scraper.
"""
import asyncio
import re
from typing import Optional

from playwright.async_api import async_playwright, Page

from .analyzer import BetAnalysis
from .config import config


class BetExecutor:

    async def _find_and_click_odds(self, page: Page, analysis: BetAnalysis) -> bool:
        """
        Searches for the event, opens the market and clicks the correct odds button.
        Returns True if the bet slip was opened successfully.
        """
        # Search for the event by name
        search = page.locator("input[type='search'], input[placeholder*='search' i], input[placeholder*='buscar' i]")
        if await search.count() > 0:
            await search.first.fill(analysis.event)
            await page.wait_for_timeout(1500)

        # Try to find the event link on the page
        event_link = page.get_by_text(re.compile(re.escape(analysis.event[:20]), re.I))
        if await event_link.count() == 0:
            # Fallback: navigate directly to prematch and look for the event
            await page.goto(f"{config.tonybet_url}/en/prematch", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            event_link = page.get_by_text(re.compile(re.escape(analysis.event[:20]), re.I))

        if await event_link.count() == 0:
            print(f"    ✗ Evento no encontrado en la página: {analysis.event}")
            return False

        await event_link.first.click()
        await page.wait_for_timeout(2000)

        # Find the specific odds button for this selection
        odds_str = str(analysis.odds)
        selection_area = page.get_by_text(re.compile(re.escape(analysis.selection[:15]), re.I))

        if await selection_area.count() > 0:
            # Click the odds button near this selection
            odds_btn = page.get_by_text(re.compile(re.escape(odds_str[:4])))
            if await odds_btn.count() > 0:
                await odds_btn.first.click()
                await page.wait_for_timeout(1000)
                return True

        print(f"    ✗ No se encontró el botón de cuota para {analysis.selection} @ {analysis.odds}")
        return False

    async def _fill_stake_and_confirm(self, page: Page, stake: float, dry_run: bool) -> bool:
        """
        Fills in the stake in the bet slip and confirms (or simulates in dry_run mode).
        """
        # Find stake input in bet slip
        stake_input = page.locator(
            "input[type='number'][class*='stake' i], "
            "input[class*='amount' i], "
            "input[placeholder*='stake' i], "
            "input[placeholder*='importe' i]"
        )

        if await stake_input.count() == 0:
            # Generic number input in bet slip area
            stake_input = page.locator(".betslip input[type='number'], [class*='bet-slip'] input")

        if await stake_input.count() == 0:
            print("    ✗ No se encontró el campo de importe en el cupón de apuesta")
            return False

        await stake_input.first.triple_click()
        await stake_input.first.fill(str(stake))
        await page.wait_for_timeout(500)

        if dry_run:
            print(f"    [SIMULACIÓN] Apuesta de {stake}€ lista para confirmar (no se ha colocado)")
            return True

        # Confirm button
        confirm_btn = page.get_by_role(
            "button",
            name=re.compile(r"place.?bet|confirmar|apostar|bet.?now", re.I)
        )
        if await confirm_btn.count() == 0:
            print("    ✗ No se encontró el botón de confirmar apuesta")
            return False

        await confirm_btn.first.click()
        await page.wait_for_timeout(2000)
        return True

    async def place_bets(
        self,
        bets: list[BetAnalysis],
        dry_run: bool = True,
    ) -> list[BetAnalysis]:
        """
        Places all bets in the list.
        `dry_run=True` fills the slip but does NOT click confirm — safe for testing.
        Returns the list of successfully placed bets.
        """
        if not bets:
            return []

        mode = "SIMULACIÓN" if dry_run else "REAL"
        print(f"\n{'='*50}")
        print(f"EJECUTANDO APUESTAS [{mode}] — {len(bets)} apuesta(s)")
        print("=" * 50)

        placed: list[BetAnalysis] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=False,  # Always visible when placing real bets
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="es-ES",
            )
            page = await context.new_page()

            # Log in
            from .scraper import TonybetScraper
            scraper = TonybetScraper()
            await scraper._login(page)

            for bet in bets:
                print(f"\n  → {bet.event} | {bet.market} | {bet.selection} @ {bet.odds} — {bet.recommended_stake}€")
                try:
                    opened = await self._find_and_click_odds(page, bet)
                    if not opened:
                        continue
                    success = await self._fill_stake_and_confirm(page, bet.recommended_stake, dry_run)
                    if success:
                        placed.append(bet)
                        status = "✓ Simulada" if dry_run else "✓ Colocada"
                        print(f"    {status}")
                    await page.wait_for_timeout(1500)
                except Exception as exc:
                    print(f"    ✗ Error: {exc}")

            await browser.close()

        return placed
