import os
import discord
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive
import random
import asyncio
import sqlite3
from datetime import datetime

# --- TOKEN ET INTENTS ---
token = os.environ['TOKEN_BOT_DISCORD']
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

duels = {}

# --- CONNEXION À LA BASE DE DONNÉES ---
conn = sqlite3.connect("dice_stats.db")
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS paris (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    joueur1_id INTEGER NOT NULL,
    joueur2_id INTEGER NOT NULL,
    montant INTEGER NOT NULL,
    gagnant_id INTEGER NOT NULL,
    date TIMESTAMP NOT NULL
)
""")
conn.commit()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)

async def lancer_les_des(interaction: discord.Interaction, duel_data, original_message):
    joueur1 = duel_data["joueur1"]
    joueur2 = duel_data["joueur2"]
    montant = duel_data["montant"]
    croupier = duel_data["croupier"]

    suspense = discord.Embed(title="🎲 Lancer des dés en cours...", description="Les dés sont jetés... 🎲", color=discord.Color.greyple())
    suspense.set_image(url="https://images.emojiterra.com/google/noto-emoji/animated-emoji/1f3b2.gif")
    await original_message.edit(embed=suspense)

    await asyncio.sleep(5)

    roll1 = random.randint(1, 6)
    roll2 = random.randint(1, 6)

    if roll1 > roll2:
        gagnant = joueur1
    elif roll2 > roll1:
        gagnant = joueur2
    else:
        gagnant = None

    result = discord.Embed(title="🎲 Résultat du Duel", color=discord.Color.green())
    result.add_field(name=f"🎲 {joueur1.display_name}", value=f"a lancé : **{roll1}**", inline=True)
    result.add_field(name=f"🎲 {joueur2.display_name}", value=f"a lancé : **{roll2}**", inline=True)
    result.add_field(name=" ", value="─" * 20, inline=False)
    result.add_field(name="💰 Montant misé", value=f"**{format(montant, ',').replace(',', ' ')}** kamas par joueur", inline=False)

    if gagnant:
        result.add_field(name="🏆 Gagnant", value=f"{gagnant.mention} remporte **{format(2 * montant, ',').replace(',', ' ')}** kamas !", inline=False)
    else:
        result.add_field(name="⚖️ Égalité", value="Aucun gagnant, vous récupérez vos mises", inline=False)

    await original_message.edit(embed=result, view=None)

    now = datetime.utcnow()
    try:
        if gagnant:
            c.execute("INSERT INTO paris (joueur1_id, joueur2_id, montant, gagnant_id, date) VALUES (?, ?, ?, ?, ?)",
                      (joueur1.id, joueur2.id, montant, gagnant.id, now))
            conn.commit()
    except Exception as e:
        print("Erreur base de données:", e)

    duels.pop(original_message.id, None)


class DuelView(discord.ui.View):
    def __init__(self, message_id, joueur1, montant):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.joueur1 = joueur1
        self.montant = montant
        self.joueur2 = None
        self.croupier = None

        # On crée le premier bouton pour rejoindre
        self.rejoindre_joueur_button = discord.ui.Button(label="🎲 Rejoindre le duel", style=discord.ButtonStyle.green, custom_id="rejoindre_joueur")
        self.rejoindre_joueur_button.callback = self.rejoindre_joueur
        self.add_item(self.rejoindre_joueur_button)

    async def update_view(self, interaction: discord.Interaction, embed: discord.Embed, content: str = None):
        """Met à jour l'embed et les boutons de la vue."""
        await interaction.response.edit_message(content=content, embed=embed, view=self, allowed_mentions=discord.AllowedMentions(roles=True))

    async def rejoindre_joueur(self, interaction: discord.Interaction):
        """Gère l'action du joueur2 rejoignant le duel."""
        self.joueur2 = interaction.user

        if self.joueur2.id == self.joueur1.id:
            await interaction.response.send_message("❌ Tu ne peux pas rejoindre ton propre duel.", ephemeral=True)
            return

        for data in duels.values():
            if data["joueur1"].id == self.joueur2.id or ("joueur2" in data and data["joueur2"] and data["joueur2"].id == self.joueur2.id):
                await interaction.response.send_message("❌ Tu participes déjà à un autre duel.", ephemeral=True)
                return

        duel_data = duels.get(self.message_id)
        if duel_data:
            duel_data["joueur2"] = self.joueur2

        # Désactive le bouton de rejoindre pour le joueur2 et ajoute le bouton pour le croupier
        self.rejoindre_joueur_button.disabled = True
        self.clear_items()
        
        self.rejoindre_croupier_button = discord.ui.Button(label="🤝 Rejoindre en tant que Croupier", style=discord.ButtonStyle.secondary, custom_id="rejoindre_croupier")
        self.rejoindre_croupier_button.callback = self.rejoindre_croupier
        self.add_item(self.rejoindre_croupier_button)

        embed = interaction.message.embeds[0]
        embed.title = f"🎲 Duel de Dés prêt à démarrer !"
        embed.description = f"{self.joueur1.mention} et {self.joueur2.mention} sont prêts pour un duel de **{self.montant:,.0f}** kamas."
        embed.set_footer(text="Un croupier est nécessaire pour lancer les dés.")

        role_croupier = discord.utils.get(interaction.guild.roles, name="croupier")
        content_ping = ""
        if role_croupier:
            content_ping = f"{role_croupier.mention} — Un nouveau duel est prêt ! Un croupier est attendu."
        
        await self.update_view(interaction, embed, content=content_ping)

    async def rejoindre_croupier(self, interaction: discord.Interaction):
        """Gère l'action du croupier rejoignant le duel."""
        role_croupier = discord.utils.get(interaction.guild.roles, name="croupier")

        if not role_croupier or role_croupier not in interaction.user.roles:
            await interaction.response.send_message("❌ Tu n'as pas le rôle de `croupier` pour rejoindre ce duel.", ephemeral=True)
            return

        if self.croupier:
            await interaction.response.send_message(f"❌ Un croupier ({self.croupier.mention}) a déjà rejoint le duel.", ephemeral=True)
            return

        self.croupier = interaction.user
        duel_data = duels.get(self.message_id)
        if duel_data:
            duel_data["croupier"] = self.croupier
        
        # Désactive le bouton du croupier et ajoute le bouton pour lancer le duel
        self.clear_items()
        
        self.lancer_des_button = discord.ui.Button(label="🎰 Lancer les dés !", style=discord.ButtonStyle.success, custom_id="lancer_des")
        self.lancer_des_button.callback = self.lancer_des
        self.add_item(self.lancer_des_button)

        embed = interaction.message.embeds[0]
        embed.title = f"🎲 Duel de Dés prêt !"
        embed.description = f"Le croupier {self.croupier.mention} est en place. Le duel peut commencer."
        embed.set_footer(text="Le croupier peut lancer les dés.")

        await self.update_view(interaction, embed, content=None)

    async def lancer_des(self, interaction: discord.Interaction):
        """Lance le duel de dés."""
        if interaction.user.id != self.croupier.id:
            await interaction.response.send_message("❌ Seul le croupier peut lancer les dés.", ephemeral=True)
            return

        await interaction.response.defer()
        
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)

        duel_data = duels.get(self.message_id)
        original_message = await interaction.channel.fetch_message(self.message_id)
        await lancer_les_des(interaction, duel_data, original_message)

# --- COMMANDES ---

@bot.tree.command(name="duel", description="Lancer un duel de dés avec un montant.")
@app_commands.describe(montant="Montant misé en kamas")
async def duel(interaction: discord.Interaction, montant: int):
    if not isinstance(interaction.channel, discord.TextChannel) or interaction.channel.name != "duel-dés":
        await interaction.response.send_message("❌ Cette commande ne peut être utilisée que dans le salon #duel-dés.", ephemeral=True)
        return

    if montant <= 0:
        await interaction.response.send_message("❌ Le montant doit être supérieur à 0.", ephemeral=True)
        return

    for duel_data in duels.values():
        if duel_data["joueur1"].id == interaction.user.id or (
            "joueur2" in duel_data and duel_data["joueur2"] and duel_data["joueur2"].id == interaction.user.id):
            await interaction.response.send_message(
                "❌ Tu participes déjà à un autre duel. Termine-le ou utilise `/quit` pour l'annuler.",
                ephemeral=True)
            return

    embed = discord.Embed(
        title="🎰 Nouveau Duel De Dés",
        description=f"**{interaction.user.mention}** lance un duel pour **{montant:,.0f}".replace(",", " ") + " kamas** 💰\n"
                      "Clique sur le bouton ci-dessous pour rejoindre !",
        color=discord.Color.gold()
    )

    view = DuelView(None, interaction.user, montant)

    await interaction.response.send_message(
        content="Un nouveau duel est prêt !",
        embed=embed,
        view=view,
        ephemeral=False,
        allowed_mentions=discord.AllowedMentions.none()
    )

    sent_message = await interaction.original_response()

    view.message_id = sent_message.id
    duels[sent_message.id] = {"joueur1": interaction.user, "montant": montant, "joueur2": None, "croupier": None}
    await sent_message.edit(view=view)


@bot.tree.command(name="quit", description="Annule le duel en cours que tu as lancé ou que tu as rejoint.")
async def quit_duel(interaction: discord.Interaction):
    duel_a_annuler_id = None
    is_joueur2 = False

    for message_id, duel_data in duels.items():
        if duel_data["joueur1"].id == interaction.user.id:
            duel_a_annuler_id = message_id
            break
        if "joueur2" in duel_data and duel_data["joueur2"] and duel_data["joueur2"].id == interaction.user.id:
            duel_a_annuler_id = message_id
            is_joueur2 = True
            break
    
    if duel_a_annuler_id is None:
        await interaction.response.send_message(
            "❌ Tu n'as aucun duel en attente à annuler ou à quitter.", ephemeral=True)
        return

    if not is_joueur2:
        duel_data = duels.pop(duel_a_annuler_id)
        try:
            message_initial = await interaction.channel.fetch_message(duel_a_annuler_id)
            embed_initial = message_initial.embeds[0]
            embed_initial.title = "❌ Duel annulé"
            embed_initial.description = f"Le duel de **{duel_data['joueur1'].display_name}** a été annulé."
            embed_initial.color = discord.Color.red()
            await message_initial.edit(embed=embed_initial, view=None, content="")
        except Exception:
            pass
        await interaction.response.send_message("✅ Ton duel a bien été annulé.", ephemeral=True)
    else:
        duel_data = duels.pop(duel_a_annuler_id)
        try:
            message_initial = await interaction.channel.fetch_message(duel_a_annuler_id)
            joueur1 = duel_data["joueur1"]
            montant = duel_data["montant"]

            new_embed = discord.Embed(
                title=f"🎰 Nouveau Duel De Dés",
                description=f"**{joueur1.mention}** lance un duel pour **{montant:,.0f}".replace(",", " ") + " kamas** 💰\n"
                              "Clique sur le bouton ci-dessous pour rejoindre !",
                color=discord.Color.gold()
            )

            new_view = DuelView(message_initial.id, joueur1, montant)

            await message_initial.edit(content="Un nouveau duel est prêt !", embed=new_embed, view=new_view, allowed_mentions=discord.AllowedMentions.none())
            duels[message_initial.id] = {"joueur1": joueur1, "montant": montant, "joueur2": None, "croupier": None}
            await interaction.response.send_message("✅ Tu as quitté le duel. Le créateur attend maintenant un autre joueur.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message("❌ Une erreur s'est produite lors de la mise à jour du duel.", ephemeral=True)

# --- STATS VIEWS AND COMMANDS ---
class StatsView(discord.ui.View):
    def __init__(self, ctx, entries, page=0):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.entries = entries
        self.page = page
        self.entries_per_page = 10
        self.max_page = (len(entries) - 1) // self.entries_per_page
        self.update_buttons()

    def update_buttons(self):
        self.first_page.disabled = self.page == 0
        self.prev_page.disabled = self.page == 0
        self.next_page.disabled = self.page == self.max_page
        self.last_page.disabled = self.page == self.max_page

    def get_embed(self):
        embed = discord.Embed(title="📊 Statistiques duel de dés", color=discord.Color.gold())
        start = self.page * self.entries_per_page
        end = start + self.entries_per_page
        slice_entries = self.entries[start:end]

        if not slice_entries:
            embed.description = "Aucune donnée à afficher."
            return embed

        description = ""
        for i, (user_id, mises, kamas_gagnes, victoires, winrate, total_paris) in enumerate(slice_entries):
            rank = self.page * self.entries_per_page + i + 1
            description += (
                f"**#{rank}** <@{user_id}> — "
                f"💰 **Misés** : **`{mises:,.0f}`".replace(",", " ") + " kamas** | "
                f"🏆 **Gagnés** : **`{kamas_gagnes:,.0f}`".replace(",", " ") + " kamas** | "
                f"**🎯 Winrate** : **`{winrate:.1f}%`** (**{victoires}**/**{total_paris}**)\n"
            )
            if i < len(slice_entries) - 1:
                description += "─" * 20 + "\n"

        embed.description = description
        embed.set_footer(text=f"Page {self.page + 1}/{self.max_page + 1}")
        return embed

    @discord.ui.button(label="⏮️", style=discord.ButtonStyle.secondary)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.max_page:
            self.page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.secondary)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = self.max_page
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

@bot.tree.command(name="statsall", description="Affiche les stats du duel de dés ")
async def statsall(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.TextChannel) or interaction.channel.name != "duel-dés":
        await interaction.response.send_message("❌ Cette commande ne peut être utilisée que dans le salon #duel-dés.", ephemeral=True)
        return

    c.execute("""
    SELECT joueur_id,
            SUM(montant) as total_mise,
            SUM(CASE WHEN gagnant_id = joueur_id THEN montant * 2 ELSE 0 END) as kamas_gagnes,
            SUM(CASE WHEN gagnant_id = joueur_id THEN 1 ELSE 0 END) as victoires,
            COUNT(*) as total_paris
    FROM (
        SELECT joueur1_id as joueur_id, montant, gagnant_id FROM paris
        UNION ALL
        SELECT joueur2_id as joueur_id, montant, gagnant_id FROM paris
    )
    GROUP BY joueur_id
    """)
    data = c.fetchall()

    stats = []
    for user_id, mises, kamas_gagnes, victoires, total_paris in data:
        winrate = (victoires / total_paris * 100) if total_paris > 0 else 0.0
        stats.append((user_id, mises, kamas_gagnes, victoires, winrate, total_paris))

    stats.sort(key=lambda x: x[2], reverse=True)

    if not stats:
        await interaction.response.send_message("Aucune donnée statistique disponible.", ephemeral=True)
        return

    view = StatsView(interaction, stats)
    await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=False)

@bot.tree.command(name="mystats", description="Affiche tes statistiques du duel de dés personnelles.")
async def mystats(interaction: discord.Interaction):
    user_id = interaction.user.id

    c.execute("""
    SELECT joueur_id,
            SUM(montant) as total_mise,
            SUM(CASE WHEN gagnant_id = joueur_id THEN montant * 2 ELSE 0 END) as kamas_gagnes,
            SUM(CASE WHEN gagnant_id = joueur_id THEN 1 ELSE 0 END) as victoires,
            COUNT(*) as total_paris
    FROM (
        SELECT joueur1_id as joueur_id, montant, gagnant_id FROM paris
        UNION ALL
        SELECT joueur2_id as joueur_id, montant, gagnant_id FROM paris
    )
    WHERE joueur_id = ?
    GROUP BY joueur_id
    """, (user_id,))
    
    stats_data = c.fetchone()

    if not stats_data:
        embed = discord.Embed(
            title="📊 Tes Statistiques duel de dés",
            description="❌ Tu n'as pas encore participé à un duel. Joue ton premier duel pour voir tes stats !",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    _, mises, kamas_gagnes, victoires, total_paris = stats_data
    winrate = (victoires / total_paris * 100) if total_paris > 0 else 0.0

    embed = discord.Embed(
        title=f"📊 Statistiques de {interaction.user.display_name}",
        description="Voici un résumé de tes performances au duel de dés.",
        color=discord.Color.gold()
    )

    embed.add_field(name="Total misé", value=f"**{mises:,.0f}".replace(",", " ") + " kamas**", inline=False)
    embed.add_field(name=" ", value="─" * 3, inline=False)
    embed.add_field(name="Total gagné", value=f"**{kamas_gagnes:,.0f}".replace(",", " ") + " kamas**", inline=False)
    embed.add_field(name=" ", value="─" * 20, inline=False)
    embed.add_field(name="Duels joués", value=f"**{total_paris}**", inline=True)
    embed.add_field(name=" ", value="─" * 3, inline=False)
    embed.add_field(name="Victoires", value=f"**{victoires}**", inline=True)
    embed.add_field(name=" ", value="─" * 3, inline=False)
    embed.add_field(name="Taux de victoire", value=f"**{winrate:.1f}%**", inline=False)

    embed.set_thumbnail(url=interaction.user.avatar.url if interaction.user.avatar else None)
    embed.set_footer(text="Bonne chance pour tes prochains duels !")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.event
async def on_ready():
    print(f"{bot.user} est prêt !")
    try:
        await bot.tree.sync()
        print("✅ Commandes synchronisées.")
    except Exception as e:
        print(f"Erreur : {e}")

keep_alive()
bot.run(token)
