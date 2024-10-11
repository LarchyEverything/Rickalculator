import asyncio
import difflib
import json
import logging
import io
from datetime import datetime, timedelta
from typing import Optional, Union

import discord
from discord.ext import commands, tasks
from discord.ext.commands import Context
from discord import app_commands, Button, ButtonStyle

from file_processing import FileHandler
from match_class import Match
from player_in_match import PlayerInMatch
from views.votes_view import VotesView
from config.config import token, variables
from config.config import test_token, test_variables
from config.emojis import default_color_emojis, kill_emoji, emergency_emoji, report_emoji, done_emoji, ranks_emojis, top_emojis, extra_emojis, voted_emoji, cancel_link, imp_win_link, crew_win_link

from rapidfuzz import fuzz, process
import pandas as pd
import matplotlib.pyplot as plt
import os
import aiohttp

class DiscordBot(commands.Bot):
    def __init__(self, command_prefix='!', token = None, variables = None, **options):
        # init loggers"
        logging.getLogger("discord").setLevel(logging.INFO)
        logging.getLogger("websockets").setLevel(logging.INFO)
        logging.getLogger("asyncio").setLevel(logging.INFO)
        logging.getLogger("matplotlib").setLevel(logging.INFO)
        logging.basicConfig(level=logging.INFO, encoding='utf-8', format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler("DiscordBot.log", encoding='utf-8'),logging.StreamHandler()])
        self.logger = logging.getLogger('Discord_Bot')

        # init guild variables
        try:
            self.matches_path = variables['matches_path']
            self.channels = variables['ranked_channels']
            self.guild_id = variables['guild_id']
            self.match_logs = variables['match_logs_channel']
            self.bot_commands = variables['bot_commands_channel']
            self.moderator_role = variables['moderator_role_id']
            self.staff_role = variables['staff_role_id']
            self.cancels_channel = variables['cancels_channel']
            self.admin_logs_channel = variables['admin_logs_channel']
            self.ranked_chat_channel = variables['ranked_chat']
            self.season_name : str = variables['season_name'] 
            self.blocked_role_id = variables['blocked_role_id']  
            self.ranked_access_role_id = variables['ranked_access_role_id'] 
        except Exception as e:
            self.logger.error(e)
    
        #init local variables
        self.ratio = 80
        self.fuzz_rapid = False
        self.auto_mute = True
        self.games_in_progress = []
        self.version = "v1.2.2"

        #init subclasses
        self.file_handler = FileHandler(self.matches_path, self.season_name)
        self.leaderboard = self.file_handler.leaderboard

        #check for unprocessed matches
        self.logger.info(f"Loading all match files from{self.matches_path}")
        match = self.file_handler.process_unprocessed_matches()
        if match:
            self.logger.info("Leaderboard has been updated")
            self.leaderboard.load_leaderboard()
        else:
            self.logger.info("Leaderboard is already up to date")

        #init bot
        self.token = token
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.voice_states = True
        super().__init__(command_prefix=command_prefix, intents=intents, help_command=None, **options)
        self.guild : discord.Guild

        self.add_commands()
        self.add_events()
        
        self.logger.info(f'Imported match files from {self.matches_path}')
        self.logger.info(f'Imported Database location from {self.season_name.replace(" ", "_")}_leaderboard.csv')
        self.logger.info(f'Guild ID is {self.guild_id}')


    def add_commands(self):
        @self.hybrid_command(name="stats", description = "Display Stats of yourself or a player")
        @app_commands.describe(player="Player name or @Player")
        async def stats(ctx: Context, player: Optional[str] = None):
            role_ranges = {
                "Iron": (None, 850, "https://i.ibb.co/KNQNBdN/Iron.png"),
                "Bronze": (850, 950, "https://i.ibb.co/BznPYmC/bronze.png"),
                "Silver": (950, 1050, "https://i.ibb.co/PTHxR8S/silver.png"),
                "Gold": (1050, 1150, "https://i.ibb.co/H7pZMvW/Gold.png"),
                "Platinum": (1150, 1250, "https://i.ibb.co/C96H6ZV/plat.png"),
                "Diamond": (1250, 1350, "https://i.ibb.co/f40p0Y5/diamond.png"),
                "Master": (1350, 1450, "https://i.ibb.co/mHvMQPx/master.png"),
                "Warrior": (1450, None, "https://i.ibb.co/RYjj8yC/warrior.png")
            }
            if ctx.channel.id != self.bot_commands and self.staff_role not in [role.id for role in ctx.author.roles]:
                await ctx.send(f"Please use https://discord.com/channels/{self.guild_id}/{self.bot_commands}", delete_after=5)
                await ctx.message.delete(delay=1)
                return

            thumbnail = self.guild.icon.url
            if player is None:
                player_name = ctx.author.display_name
                player_row = self.leaderboard.get_player_by_discord(ctx.author.id)
                thumbnail = ctx.author.avatar.url
            elif player.startswith("<@"):
                player_id = player.strip('<@!>')
                player_row = self.leaderboard.get_player_by_discord(player_id)
                member = self.guild.get_member(int(player_id))
                player_name = member.display_name
                thumbnail = member.avatar.url
            else:
                player_name = player
                player_row = self.leaderboard.get_player_row(player_name)
                if player_row is None:
                    await ctx.send(f"Player {player_name} not found.")
                    return
                        
            if player_row is None:
                await ctx.send(f"Player {player_name} not found.")
                return
            
            player_mmr = self.leaderboard.get_player_mmr(player_row)
            embed_url = ""
            player_role = None
            for role, (lower_bound, upper_bound, url) in role_ranges.items():
                if (lower_bound is None or player_mmr >= lower_bound) and (upper_bound is None or player_mmr <= upper_bound):
                    embed_url = url
                    player_role = role
                    break

            rank_emoji=ranks_emojis.get(player_role, "")
            ace_emoji=ranks_emojis.get("Ace" if self.leaderboard.get_player_ranking(player_row)==1 else "", "") 
            sherlock_emoji=ranks_emojis.get("Sherlock" if self.leaderboard.is_player_sherlock(player_name) else "", "") 
            jack_emoji=ranks_emojis.get("Jack" if self.leaderboard.is_player_jack_the_ripper(player_name) else "", "") 
            
            embed = discord.Embed(title=f"{rank_emoji}Player {player_name} Stats{rank_emoji}", color=discord.Color.purple())
            embed.set_thumbnail(url=thumbnail)

            general_stats = (
                f"- **Rank:** {self.leaderboard.get_player_ranking(player_row)}\n"
                f"- **MMR:** {self.leaderboard.get_player_mmr(player_row)}\n"
                f"- **Games Played:** {int(player_row['Total Number Of Games Played'])}\n"
                f"- **Games Won:** {int(player_row['Number Of Games Won'])}\n"
                f"- **Win Rate:** {round(self.leaderboard.get_player_win_rate(player_row), 1)}%"
            )
            
            crew_stats = (
                f"- **MMR:** {self.leaderboard.get_player_crew_mmr(player_row)}\n"
                f"- **Games Played:** {int(player_row['Number Of Crewmate Games Played'])}\n"
                f"- **Games Won:** {int(player_row['Number Of Crewmate Games Won'])}\n"
                f"- **WinRate:** {round(self.leaderboard.get_player_crew_win_rate(player_row), 1)}%\n"
                f"- **WinStreak:** {int(player_row['Crewmate Win Streak'])}\n"
                f"- **Best WinStreak:** {int(player_row['Best Crewmate Win Streak'])}\n"
                f"- **Survivability:** {player_row['Survivability (Crewmate)']}"
            )

            imp_stats = (
                f"- **MMR:** {self.leaderboard.get_player_imp_mmr(player_row)}\n"
                f"- **Games Played:** {int(player_row['Number Of Impostor Games Played'])}\n"
                f"- **Games Won:** {int(player_row['Number Of Impostor Games Won'])}\n"
                f"- **WinRate:** {round(self.leaderboard.get_player_imp_win_rate(player_row), 1)}%\n"
                f"- **Win Streak:** {int(player_row['Impostor Win Streak'])}\n"
                f"- **Best Win Streak:** {int(player_row['Best Impostor Win Streak'])}\n"
                f"- **Survivability:** {player_row['Survivability (Impostor)']}"
            )
            
            voting_stats = (
                f"- **Voting Accuracy:** {round(self.leaderboard.get_player_voting_accuracy(player_row) * 100, 1)}%\n"
                f"- **Voted :x: on Critical:** {int(player_row['Voted Wrong on Crit'])}\n"
                f"- **Voted :white_check_mark: on Crit & Lost:** {int(player_row['Voted Right on Crit but Lost'])}"
            )

            embed.add_field(name=f"{ace_emoji}__**General Stats**__{ace_emoji}", value=general_stats, inline=False)
            embed.add_field(name=f"{sherlock_emoji}__**Crewmate Stats**__{sherlock_emoji}", value=crew_stats, inline=True)
            embed.add_field(name=f"{jack_emoji}__**Impostor Stats**__{jack_emoji}", value=imp_stats, inline=True)
            embed.add_field(name="__**Voting Stats**__", value=voting_stats, inline=False)
            embed.set_image(url=embed_url)
            embed.set_footer(text=f"{self.season_name} Data - Bot Programmed by Aiden | Version: {self.version}", icon_url=self.user.avatar.url)
            await ctx.channel.send(embed=embed)
            self.logger.info(f'Sent stats of {player_name} to Channel {ctx.channel.name}')


        @self.hybrid_command(name="lb", description = "Display Leaderboard of the top players")
        @app_commands.describe(length = "length of the leaderboard")
        @app_commands.describe(type = "[crew/imp/None]")
        async def lb(ctx:Context, length: Optional[int] = None, type: Optional[str] = None):
            if ctx.channel.id != self.bot_commands and self.staff_role not in [role.id for role in ctx.author.roles]:
                await ctx.send(f"Please use https://discord.com/channels/{self.guild_id}/{self.bot_commands}", delete_after=5)
                await ctx.message.delete(delay=1)
                return
            players_per_field = 20

            if type:
                if type.startswith('imp'):
                    top_players = self.leaderboard.top_players_by_impostor_mmr(length or 10)  
                    title = f"{length or 10} Top Impostors"
                    color = discord.Color.red()

                elif type.startswith('crew'):
                    top_players = self.leaderboard.top_players_by_crewmate_mmr(length or 10)
                    title = f"{length or 10} Top Crewmates"
                    color = discord.Color.green()

            else:
                top_players = self.leaderboard.top_players_by_mmr(length or 10)
                title = f"{length or 10} Top Players Overall"
                color = discord.Color.blue()


            embed = discord.Embed(title=title, color=color)
            embed.set_thumbnail(url=self.guild.icon.url)

            chunks = [top_players[i:i + players_per_field] for i in range(0, len(top_players), players_per_field)]

            for i, chunk in enumerate(chunks):
                leaderboard_text = ""
                for index, row in chunk.iterrows():
                    rank = top_emojis[index] if index < len(top_emojis) else f"**{index + 1}.**"
                    leaderboard_text += f"- {rank} **{row['Player Name']}**\n"
                    leaderboard_text += f"MMR: {row.iloc[1]}\n"
                embed.add_field(name=f"", value=leaderboard_text, inline=False)

            embed.set_footer(text=f"{self.season_name} Data - Bot Programmed by Aiden | Version: {self.version}", icon_url=self.user.avatar.url)
            await ctx.send(embed=embed)
            self.logger.info(f'Sent stats of {length or 10} {title} to Channel {ctx.channel.name}')


        @self.hybrid_command(name="graph_mmr", description = "Graph MMR change of yourself or a player")
        @app_commands.describe(player = "Player name or @Player")
        async def graph_mmr(ctx:Context, player: Optional[str]):
            if ctx.channel.id != self.bot_commands and self.staff_role not in [role.id for role in ctx.author.roles]:
                await ctx.send(f"Please use https://discord.com/channels/{self.guild_id}/{self.bot_commands}",delete_after=5)
                await ctx.message.delete(delay=1)
                return
            member = None
            player_name = None 
            player_row = None

            if player is None:  # If no argument is provided
                member = ctx.author
                discord_id = ctx.author.id
                player_name = ctx.author.display_name
                player_row = self.leaderboard.get_player_by_discord(discord_id)
                
            elif player.startswith('<@'):  # If a mention is provided
                try:
                    mentioned_id = int(player[2:-1])
                    member = ctx.guild.get_member(mentioned_id)
                    player_name = member.display_name
                    player_row = self.leaderboard.get_player_by_discord(mentioned_id)
                    
                except Exception as e:
                    self.logger.error(e, mentioned_id)
                    await ctx.send(f"Invalid mention provided: {player}")
                    return
                
            else:  # If a display name is provided
                player_name = player
                player_row = self.leaderboard.get_player_row(player_name)
                if player_row is None:
                    player_row = self.leaderboard.get_player_row_lookslike(player_name)
                    if player_row is None:
                            await ctx.channel.send(f"Player {player_name} not found.")
                            return
                discord_id = self.leaderboard.get_player_discord(player_row)
                    
            if player_row is None:
                player_row = self.leaderboard.get_player_row(player_name)
                if player_row is None:
                    player_row = self.leaderboard.get_player_row_lookslike(player_name)
                    if player_row is None:
                        await ctx.channel.send(f"Player {player_name} not found.")
                        return
            player_name = player_row['Player Name']

            mmr_changes, crew_changes, imp_changes = self.file_handler.events_leaderboard.fetch_mmr_changes(player_name)

            impostor_mmr = 1000
            crew_mmr = 1000
            total_mmr = 1000
            impostor_mmrs = [impostor_mmr]
            crew_mmrs = [crew_mmr]
            total_mmrs = [total_mmr]
            for i in range(len(mmr_changes)):
                impostor_mmr += imp_changes[i]
                crew_mmr += crew_changes[i]
                total_mmr += mmr_changes[i]
                impostor_mmrs.append(impostor_mmr)
                crew_mmrs.append(crew_mmr)
                total_mmrs.append(total_mmr)
            plt.plot(impostor_mmrs, color='red', label='Impostor MMR')
            plt.plot(crew_mmrs, color='blue', label='Crew MMR')
            plt.plot(total_mmrs, color='purple', label='Total MMR')
            plt.xlabel(player_name)
            plt.ylabel('MMR')
            plt.title('MMR Changes Over Time')
            plt.legend()
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            await ctx.send(file=discord.File(buf, filename='mmr_changes.png'))
            plt.clf()
            self.logger.info(f"Sent MMR Graph for player {player_name} in channel {ctx.channel.name}")


        @self.hybrid_command(name="link", description="Link a player or yourself to the bot")
        @app_commands.describe(player="Player name in game")
        @app_commands.describe(discord="Discord mention @Player")
        async def link(ctx: Context, player: str, discord: Optional[discord.Member] = None):
            if not player:
                await ctx.send("Please provide a player name.")
                return

            player_row = self.leaderboard.get_player_row(player)
            player_discord = self.leaderboard.get_player_discord(player_row)

            if discord is None:
                discord_id = ctx.author.id
            else:
                discord_id = discord.id

            if player_discord:
                await ctx.send(f"{player} is already linked to <@{int(player_discord)}>.")
                return

            if player_row is None:
                await ctx.send(f"Player {player} not found in the database.")
                return

            if self.leaderboard.add_player_discord(player, discord_id):
                await ctx.send(f"Linked {player} to <@{discord_id}> in the leaderboard.")
            else:
                await ctx.send("Failed to link the player. Please try again later.")


        @self.hybrid_command(name="unlink", description="Unlink a player from the bot")
        @app_commands.describe(player="Player name in game or @mention")
        async def unlink(ctx: Context, player: str):
            if self.staff_role not in [role.id for role in ctx.author.roles]:
                await ctx.channel.send("You don't have permission to unlink players.")
                return

            if player.startswith('<@'):  # unlinking a mention
                discord_id = int(player[2:-1])
                player_row = self.leaderboard.get_player_by_discord(discord_id)
                if player_row is not None:
                    self.leaderboard.delete_player_discord(player_row['Player Name'])
                    await ctx.send(f"Unlinked {player_row['Player Name']} from <@{discord_id}>")
                else:
                    await ctx.send(f"{player} is not linked to any account")

            else:  # unlinking a player name
                player_row = self.leaderboard.get_player_row(player)
                if player_row is not None:
                    discord_id = self.leaderboard.get_player_discord(player_row)
                    if discord_id is not None:
                        self.leaderboard.delete_player_discord(player)
                        await ctx.send(f"Unlinked {player} from <@{discord_id}>")
                    else:
                        await ctx.send(f"Player {player} is not linked to any account")
                else:
                    await ctx.send(f"Player {player} not found in the database.")
        
        
        @self.hybrid_command(name="change_match", description="Change a match outcome")
        @app_commands.describe(match_id="Match ID")
        @app_commands.describe(result="Result (cancel/crew/imp)")
        @app_commands.describe(reason="Reason for changing a match result")
        async def change_match(ctx: Context, match_id: int, result: str, reason:Optional[str] = None):
            if self.staff_role not in [role.id for role in ctx.author.roles]:
                await ctx.send("You don't have permission to use this command.")
                return

            if match_id is None:
                await ctx.send("Please specify a valid match ID.")
                return

            if result is None or result.lower() not in ['cancel', 'crew', 'imp']:
                await ctx.send("Please specify a valid result: 'cancel', 'crew', or 'imp'.")
                return

            match_info = self.file_handler.match_info_by_id(match_id)
            if match_info is None:
                await ctx.send(f"Cannot find match with ID: {match_id}")
                return

            changed_match, output = self.file_handler.change_match_result(match_id=match_id, new_result=result)

            if changed_match != False:
                mentions = ""
                player:PlayerInMatch
                for player in changed_match.players:
                    try:
                        member = self.guild.get_member(int(player.discord))
                        mentions += f"{member.mention} "
                    except:
                        self.logger.warning(f"Player {player.name} has a wrong discord ID {player.discord}")

                await ctx.send(f"Match {match_id} changed to {result}! {mentions} {reason}")
                await self.get_channel(self.cancels_channel).send(f"Member {ctx.author.display_name} {output}! {mentions} {reason}")
            else:
                await ctx.send(output)


        @self.hybrid_command(name="update_lb", description="Update any unprocessed matches")
        async def update_lb(ctx:Context):
            if self.staff_role not in [role.id for role in ctx.author.roles]:
                await ctx.send("You don't have permission to use this command.")
                return
            member = ctx.author
            match = self.file_handler.process_unprocessed_matches()
            if match:
                ctx.send(f"{member.mention} Updated the Leaderboard!")
            else:
                ctx.send(f"Leaderboard is up to date.")

                
        @self.hybrid_command(name="m", description="Mute all players but yourself in a Voice Channel")
        async def m(ctx: Context):
            if not any(role.id in [self.moderator_role, self.staff_role] for role in ctx.author.roles):
                await ctx.send("You don't have permission to use this command.", delete_after=3)
                return
            
            await ctx.message.delete(delay=1)
            member = ctx.author
            voice_state = member.voice  # Get the voice state of the member
            
            if voice_state is None or voice_state.channel is None:
                await ctx.send("You need to be in a voice channel to use this command.", delete_after=5)
                return
            
            channel = voice_state.channel
            tasks = []
            for vc_member in channel.members:
                if vc_member != member:
                    tasks.append(vc_member.edit(mute=True, deafen=False))
            
            try:
                await asyncio.gather(*tasks)
                await ctx.send(f"Muted all other members in {channel.name}.", delete_after=5)
            except discord.Forbidden:
                await ctx.send("I don't have permission to mute members in this channel.", delete_after=5)
            except Exception as e:
                await ctx.send(f"An error occurred: {str(e)}", delete_after=5)
                self.logger.error(f"Error in m command: {str(e)}")

        @self.hybrid_command(name="um", description="Unmute all players in a Voice Channel")
        async def um(ctx: Context):
            if not any(role.id in [self.moderator_role, self.staff_role] for role in ctx.author.roles):
                await ctx.send("You don't have permission to use this command.", delete_after=3)
                return
            
            await ctx.message.delete(delay=1)
            member = ctx.author
            voice_state = member.voice  # Get the voice state of the member
            
            if voice_state is None or voice_state.channel is None:
                await ctx.send("You need to be in a voice channel to use this command.", delete_after=5)
                return
            
            channel = voice_state.channel
            tasks = []
            for vc_member in channel.members:
                tasks.append(vc_member.edit(mute=False, deafen=False))
            
            try:
                await asyncio.gather(*tasks)
                await ctx.send(f"Unmuted all members in {channel.name}.", delete_after=5)
            except discord.Forbidden:
                await ctx.send("I don't have permission to unmute members in this channel.", delete_after=5)
            except Exception as e:
                await ctx.send(f"An error occurred: {str(e)}", delete_after=5)
                self.logger.error(f"Error in um command: {str(e)}")


        @self.hybrid_command(name="automute", description="Toggle automute from the server side")
        @app_commands.describe(toggle="On/Off")
        async def automute(ctx:Context, toggle : str):
            if self.staff_role not in [role.id for role in ctx.author.roles]:
                await ctx.channel.send("You don't have permission to turn off automute.")
                return
            
            if toggle.lower() == "on":
                await ctx.channel.send("Automute is turned ON from the server side!")
                self.logger.info("Automute has been turned ON")
                await self.get_channel(self.admin_logs_channel).send(f"{ctx.author.mention} turned Automute ON")

                self.auto_mute = True

            elif toggle.lower() == "off":
                await ctx.channel.send("Automute is turned OFF from the server side!")
                self.logger.info("Automute has been turned OFF")
                await self.get_channel(self.admin_logs_channel).send(f"{ctx.author.mention} turned Automute OFF")
                self.auto_mute = False

            else:
                await ctx.channel.send("Please use !automute On or !automute Off to toggle serve-side automute")


        @self.hybrid_command(name="change_k", description="Change the MMR multiplier (default is 32)")
        @app_commands.describe(k="K multiplier")
        async def change_k(ctx:Context, k:int):
            if self.staff_role not in [role.id for role in ctx.author.roles]:
                await ctx.send("You don't have permission to use this command.", delete_after=3)
                return
            await ctx.message.delete(delay=1)
            k_file_path = self.file_handler.k_file_name

            if not os.path.exists(k_file_path):
                await ctx.send(f"Error: The file {k_file_path} does not exist.", delete_after=5)
                return
            
            try:
                with open(k_file_path, 'r') as file:
                    current_value = json.load(file)
            except json.JSONDecodeError:
                await ctx.send(f"Error: The file {k_file_path} contains invalid data.", delete_after=5)
                return

            with open(k_file_path, 'w') as file:
                json.dump(k, file)
            await ctx.send(f"The MMR multiplier has been changed from {current_value} to {k}.", delete_after=5)
            log_channel = self.get_channel(self.admin_logs_channel)  
            if log_channel:
                await log_channel.send(f"MMR multiplier changed by {ctx.author.mention} to {k}.")



        @self.hybrid_command(name="rules", description="Displays the rules for calculating MMR in this bot")
        async def rules(ctx:Context):
            embed = discord.Embed(title="Among Us Game Info", color=discord.Color.blurple())
            embed.add_field(name="Impostors", value="""
        If the impostor is **ejected** on **8, 9, 10** __THEN__ they will **lose 15%** performance.
        The other impostor who is a **solo** impostor will **gain 15%** performance.
        If an impostor got a crewmate __voted out__ in a meeting they will **gain 10%** for every crewmate voted out.
        For every kill you do as a **solo** impostor, you will **gain 7%** performance.
        If you win as a solo Impostor, you will **gain 20%** performance.
        """, inline=False)
            embed.add_field(name="Crewmates", value="""
        If the crewmate voted wrong on **__crit__(3, 4) players alive** or **(5, 6, 7) players alive with 2 imps** __THEN__ they will **LOSE 30%** performance.
        If the crewmate votes out an impostor they will **gain 10%** performance.
        If the crewmate votes correct on crit but loses then they will **gain 20%** performance.
        """, inline=False)
            embed.add_field(name="Winning Percentage", value="The percentage of winning is calculated by a logaritmic regression machine learning module trained on pre-season data.",inline=False)
            embed.add_field(name="MMR Gained", value="Your MMR gain will be your team's winning percentage * your performance * K(32)",inline=False)
            embed.set_footer(text=f"Bot Programmed by Aiden | Version: {self.version}", icon_url=self.user.avatar.url)
            await ctx.send(embed=embed)
            self.logger.info(f'Sent game info to Channel {ctx.channel}')

        
        @self.hybrid_command(name="mmr_change", description="Change MMR of a Player")
        @app_commands.describe(player="Player name or @player")
        @app_commands.describe(value="Value to add/subtract (-10/10)")
        @app_commands.describe(change_type="Crew/Imp/None")
        async def mmr_change(ctx: Context, player: str, value: float, change_type: Optional[str] = None, reason : str = None):
            if self.staff_role not in [role.id for role in ctx.author.roles]:
                await ctx.send("You don't have permission to change a player's MMR.")
                return

            if not player or value is None:
                await ctx.send("Please provide a player name and the value argument.")
                return

            change_type = change_type.lower() if change_type else None
            if change_type and not change_type.startswith(("crew", "imp")):
                await ctx.send("Invalid change_type. It must start with 'crew', 'imp', or None.")
                return
            
            if player.startswith('<@'):  # unlinking a mention
                discord_id = int(player[2:-1])
                player_row = self.leaderboard.get_player_by_discord(discord_id)
            else:
                player_row = self.leaderboard.get_player_row(player)

            if player_row is None:
                await ctx.send(f"Player {player} not found.")
                return

            try:
                mmr_change_value = float(value)
            except ValueError:
                await ctx.send("Please input a correct MMR change value.")
                return

            mmr_change_text = ""
            if change_type and change_type.startswith("crew"):
                self.file_handler.leaderboard.mmr_change_crew(player_row, mmr_change_value)
                mmr_change_text = "Crew "
            elif change_type and change_type.startswith("imp"):
                self.file_handler.leaderboard.mmr_change_imp(player_row, mmr_change_value)
                mmr_change_text = "Impostor "
            else:
                self.file_handler.leaderboard.mmr_change(player_row, mmr_change_value)

            if mmr_change_value > 0:
                await ctx.send(f"Added {mmr_change_value} {mmr_change_text} MMR to Player {player}")
                await self.get_channel(self.admin_logs_channel).send(f"{ctx.author.mention} Added {mmr_change_value} {mmr_change_text}MMR to Player {player} because {reason}")
            elif mmr_change_value < 0:
                await ctx.send(f"Subtracted {-mmr_change_value} {mmr_change_text} MMR from Player {player}")
                await self.get_channel(self.admin_logs_channel).send(f"{ctx.author.mention} Subtracted {mmr_change_value} {mmr_change_text}MMR to Player {player} because {reason}")


        @self.hybrid_command(name="name_change", description="Change the name of a player in all matches and leaderboard")
        @app_commands.describe(old_name="Player old name (this name is case sensitive)")
        @app_commands.describe(new_name="Player new name")
        async def name_change(ctx: Context, old_name : str, new_name : str):
            if not any(role.id == self.staff_role for role in ctx.author.roles):
                await ctx.send("You don't have permission to change a player's name.")
                return
            found_old_player = self.leaderboard.get_player_row(old_name)
            if found_old_player is not None and not found_old_player.empty:
                self.file_handler.change_player_name(old_name, new_name)
                await ctx.send(f'Changed player name from "{old_name}" to "{new_name}"')
                await self.get_channel(self.admin_logs_channel).send(f'Changed player name from "{old_name}" to "{new_name}"')
            else:
                await ctx.send(f"I can not find player {old_name}, please make sure the player is in the leaderboard")


        @self.hybrid_command(name="rank_block", description="Rank block a player for a duration of time")
        @app_commands.describe(player="@Player")
        @app_commands.describe(duration="Duration [30m/12h/5d..]")
        @app_commands.describe(reason="Reason for the rankblock")
        async def rank_block(ctx: Context, player: discord.Member, duration: str, reason: str):
            # Check if the user has the staff role
            if not any(role.id == int(self.staff_role) for role in ctx.author.roles):
                await ctx.send("You don't have permission to rankblock a player.")
                return
            def calculate_unblock_time(duration_str):
                num = int(''.join(filter(str.isdigit, duration_str)))
                if 'm' in duration_str:
                    return datetime.now() + timedelta(minutes=num)
                elif 'h' in duration_str:
                    return datetime.now() + timedelta(hours=num)
                elif 'd' in duration_str:
                    return datetime.now() + timedelta(days=num)
                else:
                    return None

            now = datetime.now()
            unblock_time = calculate_unblock_time(duration)
            if not unblock_time:
                await ctx.send("Invalid duration format.")
                return
            data = {'Player ID': [player.id],
                    'Player Name': [player.name],
                    'Blocked At': [now.strftime("%Y-%m-%d %H:%M:%S")],
                    'Unblock Time': [unblock_time.strftime("%Y-%m-%d %H:%M:%S")],
                    'Reason': [reason]}
            df = pd.DataFrame(data)
            df.to_csv('rank_blocks.csv', mode='a', index=False, header=not os.path.exists('rank_blocks.csv'))

            blocked_role = ctx.guild.get_role(self.blocked_role_id)
            access_role = ctx.guild.get_role(self.ranked_access_role_id)
            await player.add_roles(blocked_role, reason=reason)
            await player.remove_roles(access_role, reason=reason)
            await ctx.send(f"Player {player.display_name} was rankblocked for {duration}{' because ' + reason if reason else ''}")


        @self.hybrid_command(name="unblock", help="Unblock a player manually")
        @app_commands.describe(player="@Player")
        @app_commands.describe(reason="Reason for the unblock")
        async def unblock(ctx: Context, player: discord.Member, reason: str):
            if not any(role.id == int(self.staff_role) for role in ctx.author.roles):
                await ctx.send("You don't have permission to unblock a player.")
                return

            blocked_role = ctx.guild.get_role(self.blocked_role_id)
            access_role = ctx.guild.get_role(self.ranked_access_role_id)
            await player.remove_roles(blocked_role, reason=reason)
            await player.add_roles(access_role, reason=reason)

            if os.path.exists('rank_blocks.csv'):
                df = pd.read_csv('rank_blocks.csv')
                df = df[df['Player ID'] != player.id]
                df.to_csv('rank_blocks.csv', index=False)
                await ctx.send(f"{player.mention} has been unblocked{' because ' + reason if reason else ''}")

            else:    
                await ctx.send(f"No one is ranked blocked, failed to unblock {player.display_name}")
            

        @self.hybrid_command(name="replay_match", description="Display match details of all the players in match")
        @app_commands.describe(match_id="Match ID")
        async def replay_match(ctx:Context, match_id : int):
            if not any(role.id == int(self.staff_role) for role in ctx.author.roles):
                await ctx.send("You don't have permission to redisplay an embed.")
                return
            if match_id == None: 
                return
            match_file = self.file_handler.find_matchfile_by_id(int(match_id))
            match = self.file_handler.match_from_file(match_file)
            end_embed = self.end_game_embed(match)
            events_embed = self.events_embed(match)
            view = VotesView(embed=events_embed)
            await ctx.send(embed=end_embed, view=view)
            await ctx.send(f"`{match.match_details()}`")
            self.logger.info(f"{ctx.author.display_name} Recieved Match {int(match_id)} Info")


        @self.hybrid_command(name="help", description="Display help for using the bot")
        async def help(ctx:Context):
            embed = discord.Embed(title="Among Us Bot Commands", color=discord.Color.gold())
            embed.add_field(name="**stats** [none/player/@mention]", value="Display stats of a player.", inline=False)
            embed.add_field(name="**lb** [none/number]", value="Display the leaderboard for top Players.", inline=False)
            embed.add_field(name="**lb imp** [none/number]", value="Display the leaderboard for top Impostors.", inline=False)
            embed.add_field(name="**lb crew** [none/number]", value="Display the leaderboardfor top Crewmates.", inline=False)
            embed.add_field(name="**graph_mmr** [none/player/@mention]", value="Display MMR Graph of a player.", inline=False)
            embed.add_field(name="**match_info** [match_id]", value="Display match info from the given ID", inline=False)
            embed.add_field(name="**rules**", value="Explains how the bot calculates MMR", inline=False)
            embed.add_field(name="**mmr_change** [player/@mention] [value] [Crew/Imp/None]", value="add or subtract mmr from the player", inline=False)
            embed.add_field(name="**name_change** [old_name]**__,__** [new_name]", value="change a player name(COMMA SEPERATOR , )", inline=False)
            embed.add_field(name="**automute** [on/off]", value="Turn on/off server-side automute.", inline=False)
            embed.add_field(name="**link** [player] [none/@mention]", value="Link a Discord user to a player name.", inline=False)
            embed.add_field(name="**unlink** [player/@mention]", value="Unlink a Discord user from a player name.", inline=False)
            embed.add_field(name="**change_match** [match_id] [cancel/crew/imp]", value="Change match result.", inline=False)
            embed.add_field(name="**m**", value="Mute everyone in your VC.", inline=False)
            embed.add_field(name="**um**", value="Unmute everyone in your VC.", inline=False)
            embed.set_footer(text=f"Bot Programmed by Aiden | Version: {self.version}", icon_url=self.user.avatar.url)
            await ctx.send(embed=embed)
            self.logger.info(f'Sent help command to Channel {ctx.channel}')


        # @self.hybrid_command(name="process", description="process")
        # @app_commands.describe(match_id="matchid")
        # async def process(ctx: Context, match_id):
        #     # match_file = self.file_handler.find_matchfile_by_id(match_id)
        #     self.file_handler.process_match_by_id(match_id)
        
        
    def add_events(self):
        @self.event
        async def on_ready():
            self.logger.info(f'{self.user} has connected to Discord!')
            self.guild = self.get_guild(self.guild_id)
            await self.get_members_in_channel()
            await self.update_leaderboard_discords()
            await self.download_player_icons() 
            await self.tree.sync()
            self.check_unblocks.start()
            
            self.logger.info(f'Ranked Among Us Bot has started!')
        

        @self.event
        async def on_voice_state_update(member:discord.Member, before:discord.VoiceState, after:discord.VoiceState):
            voice_channel_ids = [channel['voice_channel_id'] for channel in self.channels.values()]
            if (before.channel != after.channel) and \
                    ((before.channel and before.channel.id in voice_channel_ids) or (after.channel and after.channel.id in voice_channel_ids)):
                for channel in self.channels.values():
                    if before.channel and before.channel.id == channel['voice_channel_id']:
                        if member in channel['members']:
                            channel['members'].remove(member)
                            self.logger.info(f'{member.display_name} left {before.channel.name}')
                    elif after.channel and after.channel.id == channel['voice_channel_id']:
                        if member not in channel['members']:
                            channel['members'].append(member)
                            self.logger.info(f'{member.display_name} joined {after.channel.name}')
    

    async def download_player_icons(self):
        icons_dir = 'player_icons'
        os.makedirs(icons_dir, exist_ok=True)
        async with aiohttp.ClientSession() as session:
            tasks = []
            for _, row in self.leaderboard.leaderboard.iterrows():
                discord_id = row.get('Player Discord')
                if discord_id and discord_id != 0:
                    member = self.guild.get_member(int(discord_id))
                    if member and member.avatar:
                        icon_url = member.avatar.replace(size=64).url  # Small size for leaderboard
                        filename = os.path.join(icons_dir, f"{discord_id}.png")
                        tasks.append(self.download_icon(session, icon_url, filename))
            await asyncio.gather(*tasks)
        self.logger.info(f"Downloaded icons for {len(tasks)} players")


    async def download_icon(self, session, url, filename):
        async with session.get(url) as response:
            if response.status == 200:
                with open(filename, 'wb') as f:
                    f.write(await response.read())
                self.logger.debug(f"Downloaded icon: {filename}")
            else:
                self.logger.warning(f"Failed to download icon from {url}")


    @tasks.loop(minutes=1)
    async def check_unblocks(self):
        df = pd.read_csv('rank_blocks.csv')
        now = datetime.now()
        for index, row in df.iterrows():
            unblock_time = datetime.strptime(row['Unblock Time'], "%Y-%m-%d %H:%M:%S")
            if now >= unblock_time:
                member = self.guild.get_member(int(row['Player ID']))
                if member:
                    blocked_role = self.guild.get_role(self.blocked_role_id)
                    normal_role = self.guild.get_role(self.ranked_access_role_id)
                    await member.remove_roles(blocked_role, reason="Unblocking - Time Expired")
                    await member.add_roles(normal_role, reason="Unblocking - Time Expired")
                df = df.drop(index)
        df.to_csv('rank_blocks.csv', index=False)


    async def get_members_in_channel(self):
        for channel in self.channels.values():
            voice_channel = self.get_channel(channel['voice_channel_id'])
            if voice_channel:
                members = voice_channel.members
                channel['members'] = [member for member in members]


    async def update_leaderboard_discords(self):
        await self.validate_and_update_existing_discords()
        await self.add_missing_discords()
        await self.match_and_add_discords()
        self.leaderboard.save()


    async def validate_and_update_existing_discords(self):
        valid_ids = {member.id for member in self.guild.members}
        mask = self.leaderboard.leaderboard['Player Discord'].notnull()
        discord_ids = self.leaderboard.leaderboard.loc[mask, 'Player Discord'].astype(int)

        invalid_discords = discord_ids[~discord_ids.isin(valid_ids) & (discord_ids != 0)]
        if not invalid_discords.empty:
            self.leaderboard.leaderboard.drop(invalid_discords.index, inplace=True)
            # Convert index to string before joining
            invalid_ids_str = ', '.join(map(str, invalid_discords.index))
            self.logger.info(f"Removed Discord IDs for players not found in the guild: {invalid_ids_str}")
        else:
            self.logger.info("All Discord IDs in the leaderboard are valid.")


    async def add_missing_discords(self):
        member_dict = {member.display_name: member.id for member in self.guild.members}
        missing_discords = self.leaderboard.leaderboard[self.leaderboard.leaderboard['Player Discord'].isnull()]
        for player_name in missing_discords['Player Name']:
            if player_name in member_dict:
                self.leaderboard.add_player_discord(player_name, member_dict[player_name])
                self.logger.info(f"Added {player_name} to leaderboard with Discord ID from guild.")


    async def match_and_add_discords(self):
        players_with_empty_discord = self.leaderboard.players_with_empty_discord()
        if players_with_empty_discord is None:
            return

        for index, row in players_with_empty_discord.iterrows():
            player_name = row['Player Name']  
            if isinstance(player_name, int):
                self.logger.error(f"Player name is an integer: {player_name}, which is unexpected.")
                continue  

            player_name_normalized = player_name.lower().replace(" ", "")
            best_match = None
            best_score = 0
            for member in self.guild.members:
                member_display_name = member.display_name.lower().replace(" ", "")
                match_score = fuzz.token_sort_ratio(player_name_normalized, member_display_name)
                if match_score > best_score and match_score >= 80:
                    best_match = member
                    best_score = match_score

            if best_match:
                self.leaderboard.add_player_discord(player_name, best_match.id)
                self.logger.info(f"Added {best_match.display_name} to {player_name} in leaderboard")
            else:
                self.logger.warning(f"Can't find a discord match for player {player_name} in {self.guild.name}")


    def start_game_embed(self, json_data) -> discord.Embed:
        players = json_data.get("Players", [])
        player_colors = json_data.get("PlayerColors", [])
        match_id = json_data.get("MatchID", "")
        game_code = json_data["GameCode"] 
        self.logger.info(f'Creating an embed for game start MatchId={match_id}')
        
        embed = discord.Embed(title=f"Ranked Match Started", description=f"Match ID: {match_id} - Code: {game_code}\n Players:", color=discord.Color.dark_purple())

        for player_name, player_color in zip(players, player_colors): 
            player_row = self.leaderboard.get_player_row(player_name)
            player_discord_id = self.leaderboard.get_player_discord(player_row)
            color_emoji = default_color_emojis.get(player_color, ":question:")
            value = color_emoji
            try:
                player_discord = self.guild.get_member(int(player_discord_id))
                value += f" {player_discord.mention}"
            except:
                value += f" @{player_name}"
            player_mmr = self.leaderboard.get_player_mmr(player_row)
            value += "\nMMR: " + f" {player_mmr if player_mmr else 'New Player'}"
            embed.add_field(name=player_name, value=value, inline=True)
        
        current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S %Z')
        embed.set_image(url='https://www.essentiallysports.com/stories/the-best-among-us-mods-news-esports-sheriff-doctor-minecraft/assets/24.jpeg')
        embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text=f"Match Started: {current_time} - Bot Programmed by Aiden", icon_url=self.guild.icon.url)
        return embed


    def end_game_embed(self, match: Match, json_data=None) -> discord.Embed:
        player:PlayerInMatch
        if json_data is None:
            json_data = json.loads('{"GameCode":"XDXDXD","PlayerColors":[1,2,3,4,5,6,7,8,9,10]}')

        player_colors = json_data.get("PlayerColors", [])
        game_code = json_data["GameCode"]
        match.set_player_colors_in_match(player_colors)
        self.logger.info(f'Creating an embed for game End MatchId={match.id}')


        if match.result.lower() == "impostors win":
            embed_color = discord.Color.red()
        elif match.result.lower() == "canceled":
            embed_color = discord.Color.orange()
        else:
            embed_color = discord.Color.green()
        embed = discord.Embed(title=f"Ranked Match Ended - {match.result}", 
                      description=f"Match ID: {match.id} Code: {game_code}\nPlayers:", color=embed_color)

        members_discord = [(member.display_name.lower().strip()[:10], member) for member in self.guild.members]
        name_to_member = {name: member for name, member in members_discord}

        for player in match.players:
            if player.discord == 0:
                try:
                    results = process.extractOne(player.name.lower().strip(), list(name_to_member.keys()))
                    if results:  
                        best_match, score = results  
                        if score > 80: 
                            matching_member = name_to_member.get(best_match)
                            if matching_member:
                                player.discord = matching_member  #
                except ValueError as e:
                    self.logger.error(f"Error processing player {player.name}: {e}")

        for player in match.get_players_by_team("impostor"):
            self.logger.info(f"processing impostor:{player.name}")
            value = "" 
            color_emoji = default_color_emojis.get(player.color, ":question:")
            
            value = color_emoji
            try:
                player_in_discord = self.guild.get_member(int(player.discord))
                value += f" {player_in_discord.mention}"
            except:
                self.logger.error(f"Can't find discord for player {player.name}, please link")
            value += "\nMMR: " + f" {round(player.current_mmr, 1) if player.current_mmr else 'New Player'}"
            value += f"\nImp MMR: {'+' if player.impostor_mmr_gain >= 0 else ''}{round(player.impostor_mmr_gain, 1)}"
            embed.add_field(name=f"{player.name} __**(Imp)**__", value=value, inline=True)

        embed.add_field(name=f"Imp Win rate: {round(match.imp_winning_percentage*100,2)}%\nCrew Win Rate: {round(match.crew_winning_percentage*100,2)}%", value=" ", inline=True) 

        for player in match.get_players_by_team("crewmate"):
            value = "" 
            self.logger.info(f"processing crewmate:{player.name}")
            color_emoji = default_color_emojis.get(player.color, ":question:")
            value = color_emoji
            try:
                player_in_discord = self.guild.get_member(int(player.discord))
                value += f" {player_in_discord.mention}"
            except:
                self.logger.error(f"Can't find discord for player {player.name}, please link")
            value += "\nMMR: " + f" {round(player.current_mmr, 1) if player.current_mmr else 'New Player'}"
            value += f"\nCrew MMR: {'+' if player.crewmate_mmr_gain >= 0 else ''}{round(player.crewmate_mmr_gain, 1)}"
            value += f"\nTasks: {player.tasks_complete}/10"
            embed.add_field(name=f"{player.name}", value=value, inline=True)

        current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S %Z')
        datetime.now().timestamp
        if match.result == "Impostors Win":
            embed.set_image(url=imp_win_link)
        elif match.result in ["Crewmates Win", "HumansByVote"]:
            embed.set_image(url=crew_win_link)
        else:
            embed.set_image(url=cancel_link)
            
        embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text=f"Match Started: {current_time} - Bot Programmed by Aiden", icon_url=self.guild.icon.url)
        return embed  


    def events_embed(self, match:Match) -> discord.Embed:
        player:PlayerInMatch
        for player in match.players:
            player.tasks_complete = 0
            if player.team == "impostor": 
                player.color +=100
        votes_embed = discord.Embed(title=f"Match ID: {match.id} - Events", description="")
        events_df = pd.read_json(os.path.join(self.matches_path, match.event_file_name), typ='series')
        
        meeting_count = 0
        meeting_end = False
        meeting_start = False

        events_embed = f"__**Round {meeting_count+1} Actions**__\n"
        for event in events_df:
            event_type = event.get('Event')
            for key in ['Name', 'Player', 'Target', 'Killer']:
                if key in event:
                    if event[key].endswith(" |"):
                        event[key] = event[key][:-2] 
                
            if event_type == "Task":
                player = match.get_player_by_name(event.get('Name'))
                player.finished_task()
                if player.tasks_complete == 10:
                    color_emoji = default_color_emojis.get(player.color, "?")
                    events_embed += f"{color_emoji} Tasks {done_emoji} {'Alive' if player.alive else 'Dead'}\n"

            elif event_type == "PlayerVote":
                player = match.get_player_by_name(event.get('Player'))
                target = match.get_player_by_name(event.get('Target'))
                player_emoji = default_color_emojis.get(player.color, "?")
                if target == None:
                    events_embed += f" {player_emoji} Skipped\n"
                else:
                    target_emoji = default_color_emojis.get(target.color, "?")
                    events_embed += f" {player_emoji} voted {target_emoji}\n"
                    
            elif event_type == "Death":
                player = match.get_player_by_name(event.get('Name'))
                killer = match.get_player_by_name(event.get('Killer'))
                player_emoji = default_color_emojis.get(player.color+200, "?")
                killer_emoji = default_color_emojis.get(killer.color, "?")
                events_embed += f" {killer_emoji} {kill_emoji} {player_emoji}\n"
                
            elif event_type == "BodyReport":
                player = match.get_player_by_name(event.get('Player'))
                dead_player = match.get_player_by_name(event.get('DeadPlayer'))
                player_emoji = default_color_emojis.get(player.color, "?")
                dead_emoji = default_color_emojis.get(dead_player.color+200, "?")
                events_embed += f" {player_emoji} {report_emoji} {dead_emoji}\n"
                meeting_start = True
                meeting_count+=1
                
            elif event_type == "MeetingStart":
                player = match.get_player_by_name(event.get('Player'))
                player_emoji = default_color_emojis.get(player.color, "?")
                events_embed += f" {player_emoji} {emergency_emoji} Meeting\n"
                meeting_start = True
                meeting_count+=1
                
            elif event_type == "Exiled":
                ejected_player = match.get_player_by_name(event.get('Player'))
                ejected_emoji = default_color_emojis.get(ejected_player.color, "?")
                events_embed += f"{ejected_emoji} __was **Ejected**__\n"
                meeting_end = True
                events_embed += f"Meeting End\n"
            
            elif event_type == "GameCancel":
                events_embed += f"__**Game {match.id} Canceled**__\n"
                
          
            elif event_type == "ManualGameEnd":
                events_embed += f"__**Manual End**__\n"
                break

            elif event_type == "Disconnect":
                disconnected_player = match.get_player_by_name(event.get('Name'))
                disconnected_emoji = default_color_emojis.get(disconnected_player.color, "?")
                events_embed += f"{disconnected_emoji}{'__** Disconnected Alive**__' if disconnected_player.alive else 'Disconnected Dead'}\n"
                
            elif event_type == "MeetingEnd":
                if (event.get("Result") == "Exiled"):
                    continue

                elif (event.get("Result") == "Tie"):
                    events_embed += f"__**Votes Tied**__\n"
                else:
                    events_embed += f"__**Skipped**__\n"
                meeting_end = True
                events_embed += f"Meeting End\n"

            if meeting_end == True:
                if len(events_embed) >= 1023:
                    self.logger.error(events_embed)
                votes_embed.add_field(name = "", value=events_embed, inline=True)
                events_embed = ""
                events_embed += f"__**Round {meeting_count+1} Actions**__\n"
                meeting_end = False 

            elif meeting_start == True:
                events_embed += f"__Meeting #{meeting_count}__\n"
                meeting_start = False

        
        events_embed += f"**Match {match.id} Ended**\n"
        events_embed += f"**{match.result}**"
        votes_embed.add_field(name = "", value=events_embed, inline=True)
        votes_embed.set_footer(text=f"Bot Programmed by Aiden | Version: {self.version}", icon_url=self.guild.icon.url)
        return votes_embed


    def find_most_matched_channel(self, json_data):
        players = json_data.get("Players", [])
        max_matches = 0
        most_matched_channel_name = None
        players = {player.lower().strip() for player in players} #normalize
        
        for channel_name, channel_data in self.channels.items():
            channel_members = channel_data['members']
            matches = 0
            for player in players:
                for member in channel_members:
                    # Compare cropped strings of player name and member display name
                    cropped_player_name = player[:min(len(player), len(member.display_name))]
                    cropped_member_name = member.display_name.lower().strip()[:min(len(player), len(member.display_name))]
                    similarity_ratio = fuzz.ratio(cropped_player_name, cropped_member_name)
                    if similarity_ratio >= self.ratio:  # Adjust threshold as needed
                        matches += 1
                        break  # Exit inner loop once a match is found
            if matches > max_matches:
                max_matches = matches
                most_matched_channel_name = channel_name
            if matches >= 4:
                return self.channels.get(most_matched_channel_name)
        return self.channels.get(most_matched_channel_name)


    async def add_players_discords(self, json_data, game_channel):
        players = json_data.get("Players", [])
        match_id = json_data.get("MatchID", "")
        self.logger.info(f'Adding discords from match={match_id} to the leaderboard if missing and creating new players')
        members_started_the_game = game_channel['members_in_match']

        for member in members_started_the_game:
            best_match = None
            best_similarity_ratio = 0
            for player in players:
                cropped_player_name = player.lower().strip()[:min(len(player), len(member.display_name.strip()))]
                cropped_member_name = member.display_name.lower().strip()[:min(len(player), len(member.display_name.strip()))]
                similarity_ratio = fuzz.ratio(cropped_player_name, cropped_member_name)
                if similarity_ratio >= self.ratio and similarity_ratio > best_similarity_ratio:
                    best_similarity_ratio = similarity_ratio
                    best_match = (player, member)
            if best_match is not None:
                self.logger.info(f"found {best_match[1].display_name}")
                player_name, member = best_match
                player_row = self.leaderboard.get_player_row(player_name)

                if player_row is None:
                    self.logger.info(f"Player {player_name} was not found in the leaderboard, creating a new player")
                    self.leaderboard.new_player(player_name)
                    self.leaderboard.add_player_discord(player_name, member.id)
                    self.leaderboard.save()

                if self.leaderboard.get_player_discord(player_row) is None:
                    self.logger.info(f"Player {player_name} has no discord in the leaderboard, adding discord {member.id}")
                    self.leaderboard.add_player_discord(player_name, member.id)
                    self.leaderboard.save()
            else:
                self.logger.error(f"Can't find a match a player for member {member.display_name}")


    async def handle_game_start(self, json_data):
        match_id = json_data.get("MatchID", "")
        game_code = json_data.get("GameCode", "")
        players = set(json_data.get("Players", []))
        game_channel = self.find_most_matched_channel(json_data)
        
        for game in self.games_in_progress:
            if game["GameVoiceChannelID"] == game_channel['voice_channel_id'] and game_code != game['GameCode']:
                logging.warning(f"Lobby {game_code} is not the real lobby, there's a game with similar players running already")
                return

        game = {"GameCode":game_code, "MatchID": match_id, "Players": players, "GameVoiceChannelID": game_channel['voice_channel_id']}
        self.games_in_progress.append(game)
        self.logger.info(f"Code:{game_code}, ID:{match_id}, Players:{players}, VC ID: {game_channel['voice_channel_id']} added to games in progress.")

        if game_channel:
            game_channel['members_in_match'] = game_channel.get('members')
            if self.auto_mute:
                await self.game_start_automute(game_channel)
            text_channel_id = game_channel['text_channel_id']
            await self.add_players_discords(json_data, game_channel)
            embed = self.start_game_embed(json_data)
            text_channel = self.get_channel(text_channel_id)
            if text_channel:
                await text_channel.send(embed=embed)
            else:
                self.logger.error(f"Text channel with ID {text_channel_id} not found.")
        else:
            self.logger.error(f"Could not find a matching game channel to the game not found.")


    async def game_start_automute(self, game_channel):
        voice_channel_id = game_channel['voice_channel_id']
        voice_channel = self.get_channel(voice_channel_id)
        if voice_channel is not None:
            tasks = []
            for member in voice_channel.members:
                tasks.append(member.edit(mute=True, deafen=True))
                self.logger.info(f"Deafened and Muted {member.display_name}")
            try:
                await asyncio.gather(*tasks)  # undeafen all players concurrently
            except:
                self.logger.warning("Some players left the VC on Game Start")
        else:
            self.logger.error(f"Voice channel with ID {voice_channel_id} not found.")


    async def handle_meeting_start(self, json_data):
        players = set(json_data.get("Players", []))
        game_code = json_data.get("GameCode", "")
        dead_players = set(json_data.get("DeadPlayers", []))
        alive_players = players - dead_players
        dead_players_normalized = {player.lower().replace(" ", "") for player in dead_players}
        alive_players_normalized = {player.lower().replace(" ", "") for player in alive_players}
        tasks = []
            
        game_channel = self.find_most_matched_channel(json_data)
        for game in self.games_in_progress:
            if game["GameVoiceChannelID"] == game_channel['voice_channel_id'] and game_code != game['GameCode']:
                logging.warning(f"Lobby {game_code} is not the real lobby, there's a game with similar players running already")
                return
            
        if game_channel:
            voice_channel_id = game_channel.get('voice_channel_id')
            text_channel_id = game_channel.get('text_channel_id')
            voice_channel = self.get_channel(voice_channel_id)
            text_channel = self.get_channel(text_channel_id)

            if voice_channel is not None:
                members_in_vc = {(member_in_vc.display_name.lower().replace(" ", ""), member_in_vc) for member_in_vc in voice_channel.members}
                remaining_members = []
                for element in members_in_vc:
                    match_found = False
                    display_name, member = element

                    best_match = difflib.get_close_matches(display_name, dead_players_normalized, cutoff=1.0)
                    if len(best_match) == 1:
                        tasks.append(member.edit(mute=True, deafen=False))
                        dead_players_normalized.remove(best_match[0])
                        self.logger.info(f"undeafened and muted {member.display_name}")
                        match_found = True 
                        continue

                    best_match = difflib.get_close_matches(display_name, alive_players_normalized, cutoff=1.0)
                    if len(best_match) == 1:
                        tasks.append(member.edit(mute=False, deafen=False))
                        alive_players_normalized.remove(best_match[0])
                        self.logger.info(f"undeafened and unmuted {member.display_name}")
                        match_found = True 

                    if not match_found:
                        remaining_members.append(element)

                remaining_members_final = []
                for element in remaining_members:
                    display_name, member = element
                    match_found = False

                    best_match = difflib.get_close_matches(display_name, dead_players_normalized, cutoff=0.9)
                    if len(best_match) == 1:
                        tasks.append(member.edit(mute=True, deafen=False))
                        dead_players_normalized.remove(best_match[0])
                        self.logger.info(f"deafened and unmuted {member.display_name}")
                        match_found = True
                    
                    best_match = difflib.get_close_matches(display_name, alive_players_normalized, cutoff=0.9)
                    if len(best_match) == 1:
                        tasks.append(member.edit(mute=False, deafen=False))
                        alive_players_normalized.remove(best_match[0])
                        self.logger.info(f"undeafened and unmuted {member.display_name}")
                        match_found = True

                    if not match_found:
                        remaining_members_final.append(element)

                for element in remaining_members_final:
                    display_name, member = element
                    match_found = False
                    best_match = difflib.get_close_matches(display_name, dead_players_normalized, cutoff=0.75)
                    if len(best_match) == 1:
                        tasks.append(member.edit(mute=True, deafen=False))
                        dead_players_normalized.remove(best_match[0])
                        self.logger.info(f"undeafened and muted {member.display_name}")
                        match_found = True
                    
                    best_match = difflib.get_close_matches(display_name, alive_players_normalized, cutoff=0.75)
                    if len(best_match) == 1:
                        tasks.append(member.edit(mute=False, deafen=False))
                        alive_players_normalized.remove(best_match[0])
                        self.logger.info(f"undeafened and unmuted {member.display_name}")
                        match_found = True

                    if not match_found:
                        self.logger.error(f"Could not perform automute on {member.display_name}")
                        await text_channel.send(f"Could not perform automute on {member.display_name}")
                try: 
                    await asyncio.gather(*tasks)
                except:
                    self.logger.warning("Some players left the VC on Meeting Start")
            else:
                self.logger.error(f"Voice channel with ID {voice_channel_id} not found.")
        else:
            self.logger.error("No suitable game channel found for the players.")


    async def handle_meeting_end(self, json_data):
        players = set(json_data.get("Players", []))
        impostors = set(json_data.get("Impostors", []))
        dead_players = set(json_data.get("DeadPlayers", []))
        game_code = json_data.get("GameCode", "")
        alive_players = players - dead_players
        dead_players_normalized = {player.lower().replace(" ", "") for player in dead_players}
        alive_players_normalized = {player.lower().replace(" ", "") for player in alive_players}
        game_channel = self.find_most_matched_channel(json_data)
            
        for game in self.games_in_progress:
            if game["GameVoiceChannelID"] == game_channel['voice_channel_id'] and game_code != game['GameCode']:
                logging.warning(f"Lobby {game_code} is not the real lobby, there's a game with similar players running already")
                return
            
        game_ended = impostors.issubset(dead_players)
        if game_ended:
            self.logger.info(f"Skipping MeetingEnd Automute because all impostors are dead.")
            return
        
        if game_channel:
            voice_channel_id = game_channel.get('voice_channel_id')
            text_channel_id = game_channel.get('text_channel_id')
            voice_channel = self.get_channel(voice_channel_id)
            text_channel = self.get_channel(text_channel_id)

            if voice_channel is not None:
                members_in_vc = {(member_in_vc.display_name.lower().replace(" ", ""), member_in_vc) for member_in_vc in voice_channel.members}
                remaining_members = []
                tasks = []
                for element in members_in_vc:
                    match_found = False
                    display_name, member = element

                    best_match = difflib.get_close_matches(display_name, dead_players_normalized, cutoff=1.0)
                    if len(best_match) == 1:
                        self.logger.info(f"undeafened and unmuted {member.display_name}")
                        tasks.append(member.edit(mute=False, deafen=False))
                        dead_players_normalized.remove(best_match[0])
                        match_found = True

                    best_match = difflib.get_close_matches(display_name, alive_players_normalized, cutoff=1.0)
                    if len(best_match) == 1:
                        tasks.append(member.edit(mute=True, deafen=True))
                        alive_players_normalized.remove(best_match[0])
                        self.logger.info(f"deafened and muted {member.display_name}")
                        match_found = True

                    if not match_found:
                        remaining_members.append(element)

                remaining_members_final = []
                for element in remaining_members:
                    display_name, member = element
                    match_found = False

                    best_match = difflib.get_close_matches(display_name, dead_players_normalized, cutoff=0.9)
                    if len(best_match) == 1:
                        tasks.append(member.edit(mute=False, deafen=False))
                        dead_players_normalized.remove(best_match[0])
                        self.logger.info(f"undeafened and unmuted {member.display_name}")
                        match_found = True
                    
                    best_match = difflib.get_close_matches(display_name, alive_players_normalized, cutoff=0.9)
                    if len(best_match) == 1:
                        tasks.append(member.edit(mute=True, deafen=True))
                        alive_players_normalized.remove(best_match[0])
                        self.logger.info(f"deafened and muted {member.display_name}")
                        match_found = True

                    if not match_found:
                        remaining_members_final.append(element)
                        
                for element in remaining_members_final:
                    display_name, member = element
                    match_found = False
                    best_match = difflib.get_close_matches(display_name, dead_players_normalized, cutoff=0.75)
                    if len(best_match) == 1:
                        tasks.append(member.edit(mute=False, deafen=False))
                        dead_players_normalized.remove(best_match[0])
                        self.logger.info(f"undeafened and muted {member.display_name}")
                        match_found = True
                    
                    best_match = difflib.get_close_matches(display_name, alive_players_normalized, cutoff=0.75)
                    if len(best_match) == 1:
                        tasks.append(member.edit(mute=True, deafen=True))
                        alive_players_normalized.remove(best_match[0])
                        self.logger.info(f"deafened and muted {member.display_name}")
                        match_found = True

                    if not match_found:
                        self.logger.error(f"Could not perform automute on {member.display_name}")
                        await text_channel.send(f"Could not perform automute on {member.display_name}")

                await asyncio.sleep(6) 
                try:
                    await asyncio.gather(*tasks)
                except:
                    self.logger.warning("Some players left the VC on Meeting End")
            else:
                self.logger.error(f"Voice channel with ID {voice_channel_id} not found.")
        else:
            self.logger.error(f"Could not find a matching game channel to the game not found.")


    async def game_end_automute(self, voice_channel, voice_channel_id):
        if voice_channel is not None:
            tasks = []
            for member in voice_channel.members:
                tasks.append(member.edit(mute=False, deafen=False))
            try:
                await asyncio.gather(*tasks)  # undeafen all players concurrently
            except:
                self.logger.warning("Some players left the VC on Game End")
        else:
            self.logger.error(f"Voice channel with ID {voice_channel_id} not found.")


    async def change_player_roles(self, members: list[discord.Member]):
        ranked_roles = [role for role in self.guild.roles if role.name.startswith("Ranked |")]
        special_roles = {
            "Ace": (self.leaderboard.is_player_ace, "https://i.ibb.co/syZmBKq/ACEGIF.gif"),
            "Sherlock": (self.leaderboard.is_player_sherlock, "https://i.ibb.co/XCg5Q46/SHERLOCKGIF.gif"),
            "Jack the Ripper": (self.leaderboard.is_player_jack_the_ripper, "https://i.ibb.co/3MvjnDc/JackGIF.gif")
        }
        role_ranges = {
            "Iron": (None, 850),
            "Bronze": (851, 950),
            "Silver": (951, 1050),
            "Gold": (1051, 1150),
            "Platinum": (1151, 1250),
            "Diamond": (1251, 1350),
            "Master": (1351, 1450),
            "Warrior": (1451, None)
        }

        # Handle special roles across all members who currently hold those roles
        for role_name, (check_function, image_url) in special_roles.items():
            special_role = discord.utils.get(self.guild.roles, name=role_name)
            if special_role:
                current_holders = special_role.members
                for member in current_holders:
                    player_row = self.leaderboard.get_player_by_discord(member.id)
                    has_role = check_function(player_row['Player Name'])
                    if not has_role:
                        await member.remove_roles(special_role)
                        self.logger.info(f"Removed {special_role.name} from {member.display_name}")

                # Check if any member in the members list now qualifies for the special roles
                for member in members:
                    player_row = self.leaderboard.get_player_by_discord(member.id)
                    qualifies_for_role = check_function(player_row['Player Name'])
                    if qualifies_for_role and special_role not in member.roles:
                        await member.add_roles(special_role)
                        self.logger.info(f"Added {special_role.name} to {member.display_name}")
                        embed = discord.Embed(
                            title=f"Congratulations {member.display_name}!",
                            description=f"{member.mention} You have been awarded the **{special_role.name}** role!",
                            color=discord.Color.green()
                        )
                        embed.set_image(url=image_url)
                        channel = self.guild.get_channel(self.ranked_chat_channel)
                        await channel.send(embed=embed)


        # Then, handle ranked roles for the provided members
        for member in members:
            player_row = self.leaderboard.get_player_by_discord(member.id)
            if player_row is not None:
                player_mmr = player_row['MMR']
                current_ranked_roles = [role for role in member.roles if role.name.startswith("Ranked |")]
                desired_role_name = None
                for rank, (lower, upper) in role_ranges.items():
                    if lower is None and player_mmr <= upper:
                        desired_role_name = f"Ranked | {rank}"
                        break
                    elif upper is None and player_mmr >= lower:
                        desired_role_name = f"Ranked | {rank}"
                        break
                    elif lower is not None and upper is not None and lower <= player_mmr <= upper:
                        desired_role_name = f"Ranked | {rank}"
                        break

                if desired_role_name:
                    desired_role = discord.utils.get(ranked_roles, name=desired_role_name)
                    if desired_role:
                        if desired_role not in current_ranked_roles:
                            await member.remove_roles(*current_ranked_roles)
                            self.logger.info(f"Removed {current_ranked_roles} from {member.display_name}")
                            await member.add_roles(desired_role)
                            self.logger.info(f"Added {desired_role} to {member.display_name}")


    async def handle_game_end(self, json_data):
        match_id = json_data.get("MatchID", "")
        game_code = json_data.get("GameCode", "")
        game_channel = self.find_most_matched_channel(json_data)
        voice_channel_id = game_channel['voice_channel_id']
        text_channel_id = game_channel['text_channel_id']
        voice_channel = self.get_channel(voice_channel_id)

        for game in self.games_in_progress:
            if game["GameVoiceChannelID"] == game_channel['voice_channel_id'] and game_code != game['GameCode']:
                logging.warning(f"Lobby {game_code} is not the real lobby, there's a game with similar players running already")
                return
            
            if game.get("GameCode") == game_code:
                match_id = game.get("MatchID")
                self.logger.info(f"Game {game} removed from games in progress.")
                self.games_in_progress.remove(game)

        if self.auto_mute:
            await self.game_end_automute(voice_channel, voice_channel_id)

        last_match = self.file_handler.process_match_by_id(match_id)
        for i in range(10):
            if last_match.result == "Unknown" or last_match.impostors_count != 2:
                await asyncio.sleep(1)
                last_match = self.file_handler.process_match_by_id(match_id)
                if i == 9:
                    self.logger.warning(f"Match {match_id} was not loaded correctly")
            else:
                break

        end_embed = self.end_game_embed(last_match, json_data)
        events_embed = self.events_embed(last_match)
        view = VotesView(embed=events_embed)

        await self.get_channel(text_channel_id).send(embed=end_embed, view=view)
        await self.get_channel(self.match_logs).send(embed=end_embed, view=view)

        await self.change_player_roles(game_channel['members_in_match'])

        game_channel['members_in_match'] = []
        

    async def handle_client(self, reader, writer):
        data = await reader.read(1024)
        message = data.decode('utf-8')
        self.logger.debug(f"Received: {message}") 

        try:
            json_data = json.loads(message)
            event_name = json_data.get("EventName")
            match_id = json_data.get("MatchID", "")
            game_code = json_data["GameCode"]

            if event_name == "GameStart":
                self.logger.info(f"Game ID:{match_id} Started. - Code({game_code})")
                await self.handle_game_start(json_data)

            elif event_name == "MeetingStart":
                self.logger.info(f"Game Code:{game_code} Meeting Started.")
                if self.auto_mute:
                    await self.handle_meeting_start(json_data) #this is automute

            elif event_name == "MeetingEnd":
                self.logger.info(f"Game Code:{game_code} Meeting Endded.")
                if self.auto_mute:
                    await self.handle_meeting_end(json_data) #this is automute

            elif event_name == "GameEnd":
                self.logger.info(f"Game ID:{match_id} Endded. - Code({game_code})")
                await self.handle_game_end(json_data)
                
            else:
                self.logger.info("Unsupported event:", event_name)

        except json.JSONDecodeError as e:
            self.logger.error("Error decoding JSON:", e)
        except Exception as e:
            self.logger.error("Error processing event:", e, message)
    
    
    async def start_server(self):
        server = await asyncio.start_server(self.handle_client, 'localhost', 5000)
        async with server:
            self.logger.info("Socket server is listening on localhost:5000...")
            await server.serve_forever()


    async def start_bot(self):
        await asyncio.gather(
            self.start_server(),
            super().start(self.token)
        )


if __name__ == "__main__":
    bot = DiscordBot(token=token, variables=variables)
    # bot = DiscordBot(token=test_token, variables=test_variables)
    asyncio.run(bot.start_bot())
