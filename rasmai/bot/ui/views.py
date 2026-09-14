from typing import Any, Awaitable, Callable, Optional
import logging
import discord

from rasmai.bot.state.cache import cache_get, forget_analysis
from rasmai.config import WALKTHROUGH_DIR, get_public_base_url
from rasmai.storage.db import delete_connected_account, get_connected_account
from rasmai.security import LOGIN_CODE_TTL, public_reason

logger = logging.getLogger(__name__)


class OwnerOnlyView(discord.ui.View):
    """Components answer only to the user who ran the command."""

    def __init__(self, owner_id: int, *, timeout: Optional[float]):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.message: Optional[discord.Message] = None

    async def on_timeout(self) -> None:
        """Grey the components out once they stop answering, so a dead button never looks live."""
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Those buttons belong to someone else - run the command to get your own.", ephemeral=True
            )
            return False
        return True


class Expired(Exception):
    """The analysis behind a message is no longer held; the command has to be run again."""


class PagedView(OwnerOnlyView):
    """Prev and Next under a list that spans pages; `draw(page)` builds the page asked for.

    The buttons only appear when there is more than one page, so a subclass can add its
    own components either way."""

    def __init__(self, owner_id: int, page: int, pages: int, draw: Callable[[int], Awaitable[Any]], timeout: float = 600):
        super().__init__(owner_id, timeout=timeout)
        self.page, self.pages, self.draw = page, pages, draw
        if pages > 1:
            prev_button = discord.ui.Button(label="Prev", row=0, style=discord.ButtonStyle.secondary, disabled=page <= 0)
            prev_button.callback = self._mover(-1)
            self.add_item(prev_button)
            self.add_item(discord.ui.Button(label=f"page {page + 1} of {pages}", row=0, style=discord.ButtonStyle.secondary, disabled=True))
            next_button = discord.ui.Button(label="Next", row=0, style=discord.ButtonStyle.secondary, disabled=page >= pages - 1)
            next_button.callback = self._mover(1)
            self.add_item(next_button)

    def _mover(self, delta: int):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            try:
                embed, files, view = await self.draw(max(0, min(self.page + delta, self.pages - 1)))
            except Expired:
                await interaction.followup.send("Those results have expired - run the command again.", ephemeral=True)
                return
            except Exception as error:
                logger.exception("page turn failed")
                await interaction.followup.send(f"Couldn't turn the page: {public_reason(error)}", ephemeral=True)
                return
            await interaction.edit_original_response(embed=embed, attachments=files, view=view)
            if view is not None:
                view.message = self.message
        return callback


def from_cache(owner_id: int, build: Callable[..., Awaitable[Any]]) -> Callable[[int], Awaitable[Any]]:
    """A page drawer over the owner's analysis, fetched again at every turn: ``build(cached, page)``.

    :param owner_id: The Discord user the components answer to.
    :type owner_id: int
    :param build: Builds the reply for one page.
    """
    async def draw(page: int):
        cached = cache_get(str(owner_id))
        if cached is None:
            raise Expired()
        return await build(cached, page)
    return draw


class LoginView(OwnerOnlyView):
    def __init__(self, owner_id: int, connect_url: str):
        super().__init__(owner_id, timeout=LOGIN_CODE_TTL.total_seconds())
        self.add_item(discord.ui.Button(label="1 · Sign in at my-aime", url="https://my-aime.net/en/"))
        self.add_item(discord.ui.Button(label="2 · Start setup", url=connect_url))
        check = discord.ui.Button(label="Check connection", style=discord.ButtonStyle.success)
        check.callback = self._check
        self.add_item(check)
        # the same steps as a recording, played in Discord rather than sending anyone to a browser
        for label, clip in (("Show me: computer", "desktop"), ("Show me: iPhone", "ios-safari")):
            watch = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=1)
            watch.callback = self._walkthrough(clip)
            self.add_item(watch)

    def _walkthrough(self, clip: str):
        """A button that answers with one walkthrough recording, only to the person who pressed it.

        :param clip: The recording's file stem.
        :type clip: str
        :rtype: Callable
        """
        async def callback(interaction: discord.Interaction) -> None:
            path = WALKTHROUGH_DIR / f"{clip}.mp4"
            wording = "on a computer" if clip == "desktop" else "on an iPhone, in Safari"
            if not path.is_file():
                await interaction.response.send_message(
                    f"The recording is not on this server. The same walkthrough is at {get_public_base_url()}/link/",
                    ephemeral=True)
                return
            await interaction.response.send_message(
                f"Linking {wording}, start to finish. No sound, about a minute.",
                file=discord.File(str(path), filename=f"rasmai-linking-{clip}.mp4"), ephemeral=True)
        return callback

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(content="This link has expired. Run `/login` for a new one.", embed=None, view=self)
            except discord.HTTPException:
                pass

    def finished(self) -> "LoginView":
        """The view once the link landed: nothing left to press.

        :rtype: 'LoginView'
        """
        self.clear_items()
        self.stop()
        return self

    async def _check(self, interaction: discord.Interaction) -> None:
        account = get_connected_account(str(self.owner_id))
        if account and account.get("token"):
            profile = account.get("officialProfile") or {}
            who = profile.get("name") or "your maimai account"
            await interaction.response.send_message(
                f"Connected as **{who}** ({str(account.get('region', 'intl')).upper()}). Try `/analyze`.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Not connected yet. Finish the steps on the setup page, then check again.", ephemeral=True
            )


class LogoutView(OwnerOnlyView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id, timeout=120)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(content="Nothing changed. Run `/logout` again if you still want to disconnect.", view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Disconnect", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        delete_connected_account(str(self.owner_id))
        forget_analysis(str(self.owner_id))
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Disconnected. Your session key and cached data are gone.", view=self)

    @discord.ui.button(label="Keep it", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Kept. Nothing changed.", view=self)
