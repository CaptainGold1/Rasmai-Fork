from typing import Optional
import asyncio
import discord
import logging

from rasmai.engine import analysis
from rasmai.bot.state.cache import ANALYSIS_TTL, CachedAnalysis, cache_get
from rasmai.bot.core import private_only
from rasmai.bot.ui.views import OwnerOnlyView
from rasmai.scraping.scraper import SessionRejected
from rasmai.security import public_reason
from rasmai.bot.ui.login import send_login_card
from rasmai.storage.db import get_connected_account
from rasmai.bot.builders.results.embeds import (
    FOCUS_LABELS, SESSION_DEFAULT, build_analyze, build_new, build_plan, build_profile, build_session,
)
from rasmai.bot.builders.results.loading import ensure_target_play_counts, load_analysis, note_read_age
from rasmai.bot.builders.traits import build_traits

logger = logging.getLogger(__name__)


OUTPUT_LABELS = {"both": "Image + text", "image": "Image only", "embed": "Text only"}


# a shade under Discord's fifteen-minute interaction token, so the edit that greys the buttons out still lands
VIEW_TIMEOUT = min(ANALYSIS_TTL.total_seconds(), 14 * 60)


NOT_LINKED_INTRO = "**No maimai account linked yet.** Connect one first; it takes about a minute, and the card below walks you through it."


def failure_text(failure: str, error: Exception) -> str:
    """What a failed command says: the plain reason, and `/login` only when the session really is the problem.

    :param failure: The command's own sentence, such as "Something went wrong building your route."
    :type failure: str
    :param error: What went wrong.
    :type error: Exception
    :rtype: str
    """
    if isinstance(error, SessionRejected):
        return f"{failure} Your maimai session has expired: run `/login` to link again."
    return f"{failure}\n-# {public_reason(error)}"


async def ensure_linked(interaction: discord.Interaction) -> bool:
    """Whether the person has a linked account; when not, answer with the login card (ephemeral) and say so.

    :param interaction: The Discord interaction the command arrived on.
    :type interaction: discord.Interaction
    :rtype: bool
    """
    if await asyncio.to_thread(get_connected_account, str(interaction.user.id)):
        return True
    await send_login_card(interaction, "intl", intro=NOT_LINKED_INTRO)
    return False


# the levels the /new dropdown offers; with the six tiers and "any level" that is 24 options, under Discord's 25
NEW_LEVELS = ("7+", "8", "8+", "9", "9+", "10", "10+", "11", "11+", "12", "12+", "13", "13+", "14", "14+", "15")


class ResultsView(OwnerOnlyView):
    """Switch between the four views of one analysis without scraping again."""

    MODES = (("analyze", "Analyze"), ("plan", "Plan"), ("session", "Session"), ("new", "New charts"), ("profile", "Profile"), ("traits", "Traits"))

    def __init__(self, owner_id: int, mode: str, *, target: Optional[int] = None, stretch: bool = False,
                 page: int = 0, difficulty: Optional[str] = None, output: str = "both", challenge: str = "balanced",
                 min_level: Optional[str] = None, credits: int = SESSION_DEFAULT, focus: Optional[str] = None,
                 level: Optional[str] = None):
        super().__init__(owner_id, timeout=VIEW_TIMEOUT)
        self.min_level = min_level
        self.level = level
        self.credits = max(1, min(20, credits))
        self.focus = focus if focus in FOCUS_LABELS else None
        self.output = output if output in OUTPUT_LABELS else "both"
        self.challenge = challenge if challenge in analysis.CHALLENGES else "balanced"
        self.mode = mode
        self.target = target
        self.stretch = stretch
        self.page = page
        self.difficulty = difficulty
        self.message: Optional[discord.Message] = None

        for key, label in self.MODES:
            button = discord.ui.Button(
                label=label, row=0 if key != "traits" else 4,      # five per row: traits sits beside Refresh
                style=discord.ButtonStyle.primary if key == mode else discord.ButtonStyle.secondary,
                disabled=key == mode,
            )
            button.callback = self._switcher(key)
            self.add_item(button)
        refresh = discord.ui.Button(label="Refresh", row=4, style=discord.ButtonStyle.success)
        refresh.callback = self._refresh
        self.add_item(refresh)
        if mode == "session":
            fewer = discord.ui.Button(label="- 1 credit", row=1, style=discord.ButtonStyle.secondary, disabled=self.credits <= 1)
            fewer.callback = self._credits(-1)
            self.add_item(fewer)
            self.add_item(discord.ui.Button(label=f"{self.credits} credit{'s' if self.credits != 1 else ''}", row=1,
                                            style=discord.ButtonStyle.primary, disabled=True))
            more = discord.ui.Button(label="+ 1 credit", row=1, style=discord.ButtonStyle.secondary, disabled=self.credits >= 20)
            more.callback = self._credits(1)
            self.add_item(more)
            three = discord.ui.Button(label="+ 3", row=1, style=discord.ButtonStyle.secondary, disabled=self.credits >= 18)
            three.callback = self._credits(3)
            self.add_item(three)
        if mode not in ("profile", "traits"):
            targets = discord.ui.Select(
                placeholder=f"Targets: {analysis.challenge_for(self.challenge).label}", row=2, min_values=1, max_values=1,
                options=[
                    discord.SelectOption(label=mode_.label, value=key, default=key == self.challenge,
                                         description={"easy": "the surest step, about a coin flip", "balanced": "best expected gain, one in four",
                                                      "hard": "a stretch, about one in six",
                                                      "extreme": "the biggest gain on the board, about one in ten"}.get(key, ""))
                    for key, mode_ in analysis.CHALLENGES.items()
                ],
            )
            targets.callback = self._pick_challenge(targets)
            self.add_item(targets)

        if mode in ("plan", "new"):
            prev_button = discord.ui.Button(label="Prev", row=1 if mode == "plan" else 4, style=discord.ButtonStyle.secondary)
            prev_button.callback = self._pager(-1)
            self.add_item(prev_button)
            next_button = discord.ui.Button(label="Next", row=1 if mode == "plan" else 4, style=discord.ButtonStyle.secondary)
            next_button.callback = self._pager(1)
            self.add_item(next_button)
        if mode == "plan":
            toggle = discord.ui.Button(
                label="Grind targets" if stretch else "Stretch targets", row=1,
                style=discord.ButtonStyle.success if stretch else discord.ButtonStyle.danger,
            )
            toggle.callback = self._toggle_stretch
            self.add_item(toggle)
        if mode == "analyze":
            # hold the picks to one level; a single constant or a range is typed on the command itself
            options = [discord.SelectOption(label="Any level", value="lv:any", default=level is None, description="everything your scores reach")]
            options += [discord.SelectOption(label=f"Level {lv}", value=f"lv:{lv}", default=(lv == level), description="only this level")
                        for lv in reversed(NEW_LEVELS)]
            shown_scope = analysis.describe_span(level) if level else "any level"
            level_select = discord.ui.Select(placeholder=f"Picks: {shown_scope}", row=1, min_values=1, max_values=1, options=options[:25])
            level_select.callback = self._pick_level(level_select)
            self.add_item(level_select)
        if mode == "new":
            # one dropdown carries both filters: the difficulty tiers, then the levels; either half keeps the other as it is
            tiers = (("Expert and up", "any"), ("Master", "master"), ("Re:Master", "remaster"), ("Expert", "expert"),
                     ("Advanced", "advanced"), ("Basic", "basic"))
            tier_label = dict(tiers).get("any") if not difficulty else next((lb for lb, v in tiers if v == difficulty), difficulty)
            # the menu holds two filters but Discord allows one pre-selected option, so the level is
            # marked when one is chosen and the tier otherwise; the placeholder carries both either way
            options = [discord.SelectOption(label=label, value=value, default=(level is None and value == (difficulty or "any")),
                                            description="difficulty")
                       for label, value in tiers]
            options.append(discord.SelectOption(label="Any level", value="lv:any", description="the range your scores suggest"))
            options += [discord.SelectOption(label=f"Level {lv}", value=f"lv:{lv}", default=(lv == level), description="only this level")
                        for lv in reversed(NEW_LEVELS)]
            shown = options[:25]
            for extra in [option for option in shown if option.default][1:]:
                extra.default = False          # one default, whatever a later edit adds to the menu
            select = discord.ui.Select(placeholder=f"{tier_label} · level {level or 'any'}", row=1, min_values=1, max_values=1, options=shown)
            select.callback = self._pick_difficulty(select)
            self.add_item(select)
            focus = discord.ui.Select(
                placeholder="Focus: " + (FOCUS_LABELS[self.focus] if self.focus else "none"), row=3, min_values=1, max_values=1,
                options=[
                    discord.SelectOption(label="No focus", value="none", default=self.focus is None),
                    discord.SelectOption(label="Where you lose points", value="weak", default=self.focus == "weak",
                                         description="charts with the traits you score below your curve on"),
                    discord.SelectOption(label="Where you shine", value="strong", default=self.focus == "strong",
                                         description="charts with the traits you score above your curve on"),
                ],
            )
            focus.callback = self._pick_focus(focus)
            self.add_item(focus)

    def _credits(self, delta: int):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            cached = await self._cached(interaction)
            if cached:
                await show_results(interaction, cached, "session", target=self.target, stretch=self.stretch, page=0,
                                   difficulty=self.difficulty, min_level=self.min_level, level=self.level, credits=self.credits + delta,
                                   focus=self.focus, output=self.output, challenge=self.challenge)
        return callback

    def _pick_focus(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            cached = await self._cached(interaction)
            if cached:
                chosen = select.values[0]
                await show_results(interaction, cached, "new", target=self.target, stretch=self.stretch, page=0,
                                   difficulty=self.difficulty, min_level=self.min_level, level=self.level, credits=self.credits,
                                   focus=None if chosen == "none" else chosen, output=self.output, challenge=self.challenge)
        return callback

    async def _cached(self, interaction: discord.Interaction) -> Optional[CachedAnalysis]:
        cached = cache_get(str(self.owner_id))
        if cached is None:
            await interaction.followup.send("Those results have expired - run the command again for fresh ones.", ephemeral=True)
        return cached

    def _switcher(self, mode: str):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            cached = await self._cached(interaction)
            if cached:
                await show_results(interaction, cached, mode, target=self.target, stretch=self.stretch,
                                   page=0, difficulty=self.difficulty, min_level=self.min_level, level=self.level, credits=self.credits, focus=self.focus, output=self.output, challenge=self.challenge)
        return callback

    def _pager(self, delta: int):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            cached = await self._cached(interaction)
            if cached:
                await show_results(interaction, cached, self.mode, target=self.target, stretch=self.stretch,
                                   page=max(0, self.page + delta), difficulty=self.difficulty, min_level=self.min_level, level=self.level, credits=self.credits, focus=self.focus, output=self.output, challenge=self.challenge)
        return callback

    async def _toggle_stretch(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        cached = await self._cached(interaction)
        if cached:
            await show_results(interaction, cached, "plan", target=self.target, stretch=not self.stretch,
                               page=0, difficulty=self.difficulty, min_level=self.min_level, level=self.level, credits=self.credits, focus=self.focus, output=self.output, challenge=self.challenge)

    def _pick_difficulty(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            cached = await self._cached(interaction)
            if cached:
                chosen = select.values[0]
                difficulty, level = self.difficulty, self.level
                if chosen.startswith("lv:"):
                    level = None if chosen == "lv:any" else chosen[3:]
                else:
                    difficulty = None if chosen == "any" else chosen
                await show_results(interaction, cached, "new", target=self.target, stretch=self.stretch,
                                   page=0, difficulty=difficulty, min_level=self.min_level, level=level, credits=self.credits, focus=self.focus, output=self.output, challenge=self.challenge)
        return callback

    def _pick_level(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            cached = await self._cached(interaction)
            if cached:
                chosen = select.values[0]
                level = None if chosen == "lv:any" else chosen[3:]
                await show_results(interaction, cached, "analyze", target=self.target, stretch=self.stretch,
                                   page=0, difficulty=self.difficulty, min_level=self.min_level, level=level, credits=self.credits, focus=self.focus, output=self.output, challenge=self.challenge)
        return callback

    def _pick_challenge(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            cached = await self._cached(interaction)
            if cached:
                await show_results(interaction, cached, self.mode, target=self.target, stretch=self.stretch,
                                   page=0, difficulty=self.difficulty, min_level=self.min_level, level=self.level, credits=self.credits, focus=self.focus, output=self.output, challenge=select.values[0])
        return callback


    async def _refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            cached = await load_analysis(interaction, force=True)
        except Exception as error:
            logger.exception("refresh failed")
            await interaction.edit_original_response(content=failure_text("Couldn't refresh your scores.", error),
                                                     embed=None, attachments=[], view=None)
            return
        if cached:
            await show_results(interaction, cached, self.mode, target=self.target, stretch=self.stretch,
                               page=self.page, difficulty=self.difficulty, min_level=self.min_level, level=self.level, credits=self.credits, focus=self.focus, output=self.output, challenge=self.challenge)


async def show_results(interaction: discord.Interaction, cached: CachedAnalysis, mode: str, *,
                       target: Optional[int] = None, stretch: bool = False, page: int = 0,
                       difficulty: Optional[str] = None, output: str = "both", challenge: str = "balanced",
                       min_level: Optional[str] = None, credits: int = SESSION_DEFAULT, focus: Optional[str] = None,
                       level: Optional[str] = None) -> None:
    if mode not in ("profile", "traits"):
        await ensure_target_play_counts(interaction, cached, challenge)
    if mode == "traits":
        embed, files, _view = await build_traits(cached)
    elif mode == "plan":
        embed, files, page = await build_plan(cached, target, stretch, page, challenge, difficulty, min_level)
    elif mode == "session":
        embed, files = await build_session(cached, credits, challenge, difficulty)
    elif mode == "new":
        embed, files, page = await build_new(cached, difficulty, challenge, focus, level, page)
    elif mode == "profile":
        embed, files = await build_profile(cached)
    else:
        embed, files = await build_analyze(cached, challenge, level)
    note_read_age(embed, cached)
    image_files = [f for f in files if f.filename != "avatar.png"]
    if output == "image" and not image_files:
        output = "both"          # nothing rendered, so text is all there is
    view = ResultsView(interaction.user.id, mode, target=target, stretch=stretch, page=page,
                       difficulty=difficulty, output=output, challenge=challenge, min_level=min_level,
                       credits=credits, focus=focus, level=level)
    if output == "image":
        # the picture stands alone: buttons only travel with the text
        await interaction.edit_original_response(content=None, embed=None, attachments=image_files, view=None)
    elif output == "embed":
        avatar_only = [f for f in files if f.filename == "avatar.png"]
        await interaction.edit_original_response(content=None, embed=embed, attachments=avatar_only, view=view)
    else:
        await interaction.edit_original_response(content=None, embed=embed, attachments=files, view=view)
    try:
        view.message = await interaction.original_response()
    except discord.HTTPException:
        pass


async def run_view_command(interaction: discord.Interaction, mode: str, failure: str, **state) -> None:
    await interaction.response.defer(ephemeral=private_only(interaction))
    if not await ensure_linked(interaction):
        return
    force = bool(state.pop("force", False))
    try:
        cached = await load_analysis(interaction, force=force)
        if cached is None:
            return
        await show_results(interaction, cached, mode, **state)
    except Exception as error:
        logger.exception(f"{mode} command failed")
        try:
            await interaction.edit_original_response(content=failure_text(failure, error), embed=None, attachments=[], view=None)
        except discord.HTTPException:
            pass


async def run_simple_command(interaction: discord.Interaction, failure: str, build, *, ephemeral: bool = False) -> None:
    """Defer, make sure the analysis is loaded, then send whatever `build(cached)` returns.

    `build` is an async callable returning (embed, files, view); the view may be None.

    :param interaction: The Discord interaction the command arrived on.
    :type interaction: discord.Interaction

    :param build: Builds the reply.
    """
    await interaction.response.defer(ephemeral=ephemeral or private_only(interaction))
    if not await ensure_linked(interaction):
        return
    try:
        cached = await load_analysis(interaction)
        if cached is None:
            return
        embed, files, view = await build(cached)
        note_read_age(embed, cached)
        await interaction.edit_original_response(content=None, embed=embed, attachments=files or [], view=view)
        if view is not None and hasattr(view, "message"):
            try:
                view.message = await interaction.original_response()
            except discord.HTTPException:
                pass
    except Exception as error:
        logger.exception("command failed")
        try:
            await interaction.edit_original_response(content=failure_text(failure, error), embed=None, attachments=[], view=None)
        except discord.HTTPException:
            pass
