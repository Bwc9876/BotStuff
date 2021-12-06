import asyncio
import os
import subprocess

import discord
import mctools.mclient
from discord.ext import commands
from dotenv import load_dotenv
from mcstatus.server import MinecraftServer
from mctools import RCONClient
from socket import gaierror

REMOVE_FORMATTER = mctools.mclient.BaseClient.REMOVE

load_dotenv("mc.env")


class MCServerError(Exception):
    """
        Exception that represents an error with the minecraft server
    """

    pass


class RCONFailedError(MCServerError):
    """
        Exception with RCON in the server
    """

    pass


class MCServerControl(commands.Cog, name="Minecraft"):
    """
        This cog provides commands for controlling a minecraft server

        :cvar SERVER_IP: The ip address of the server
        :type SERVER_IP: str
        :cvar PUBLIC_IP: The ip address of the server people use to connect
        :type PUBLIC_IP: str
        :cvar SERVER_PORT: The port of the server
        :type SERVER_PORT: int
        :cvar SERVER_RCON_PORT: The port to use for rcon
        :type SERVER_RCON_PORT: int
        :cvar SERVER_RCON_PASSWORD: The password to use for rcon
        :type SERVER_RCON_PASSWORD: str
        :cvar SERVER_WORKING_DIRECTORY: The working directory of the minecraft server
        :type SERVER_WORKING_DIRECTORY: str
        :cvar SERVER_EXEC_COMMAND: The command to use to start the server
        :type SERVER_EXEC_COMMAND: str
        :cvar SERVER_STOP_TIMEOUT: How long to wait before force-killing the server process
        :type SERVER_STOP_TIMEOUT: int
        :ivar bot: The discord bot to install this cog to
        :type bot: commands.Bot
        :ivar rcon: The Rcon connection object to use for remote execution of commands
        :type rcon: RCONClient
        :ivar query: The Query connection object to use for queries
        :type query: MinecraftServer
        :ivar server_proc: The process the server is running in
    """

    SERVER_IP = os.getenv("MC_SERVER_IP", "127.0.0.1")
    PUBLIC_IP = os.getenv("MC_PUBLIC_IP", "private")
    SERVER_PORT = os.getenv("MC_SERVER_PORT", 25565)
    SERVER_RCON_PORT = os.getenv("MC_RCON_PORT", 25575)
    SERVER_RCON_PASSWORD = os.getenv("MC_RCON_PASSWORD", "")
    SERVER_WORKING_DIRECTORY = os.getenv("MC_SERVER_WORKING_DIRECTORY", "./")
    SERVER_EXEC_COMMAND = os.getenv("MC_SERVER_EXEC_COMMAND", "./start.sh")
    SERVER_STOP_TIMEOUT = int(os.getenv("MC_SERVER_STOP_TIMEOUT", "5"))

    def __init__(self, bot):
        """
            Creates a new cog to install a bot to

            :param bot: The bot to install the cog to
            :type bot: commands.Bot
        """

        self.bot: commands.Bot = bot
        self.rcon = None
        self.query = MinecraftServer.lookup(f"{self.SERVER_IP}:{self.SERVER_PORT}")
        self.server_proc = None

    async def _init_rcon(self) -> None:
        """
            Initializes a rcon connection to the minecraft server
        """

        try:
            self.rcon = RCONClient(self.SERVER_IP, port=self.SERVER_RCON_PORT, format_method=REMOVE_FORMATTER)
            success = self.rcon.login(self.SERVER_RCON_PASSWORD)
            if not success:
                raise RCONFailedError("Invalid Authentication")
        except ConnectionError or gaierror:
            raise RCONFailedError("Server refused rcon, is rcon enabled?")

    async def _stop_rcon(self) -> None:
        """
            Closes the connection to the rcon server
        """

        self.rcon.stop()
        self.rcon = None

    def _online(self) -> bool:
        """
            Checks if the server is online

            :returns: Whether the server is online
            :rtype: bool
        """

        return self.server_proc is not None

    @commands.command(name="mc-start", description="Start the server")
    async def _start(self, ctx: commands.Context) -> None:
        """
            This command starts the minecraft server

            :param ctx: The context surrounding the command evocation
            :type ctx: commands.Context
        """

        if self._online() is False:
            self.server_proc = await asyncio.create_subprocess_shell(self.SERVER_EXEC_COMMAND,
                                                                     stdout=subprocess.PIPE,
                                                                     cwd=self.SERVER_WORKING_DIRECTORY)
            await ctx.send("Server starting up...")
        else:
            await ctx.send("Server already started!")

    @commands.command(name="mc-stop", description="Stop the server")
    async def _stop(self, ctx: commands.Context) -> None:
        """
            This command stops the server is its online

            :param ctx: The context surrounding the command evocation
            :type ctx: commands.Context
        """

        if self._online():
            await ctx.send("Stopping server...")
            await self._execute_mc_command("stop")
            await asyncio.sleep(self.SERVER_STOP_TIMEOUT)
            try:
                await self.server_proc.kill()
                await ctx.send("Server took too long to stop, force killing...")
            except ProcessLookupError:
                pass
            await ctx.send('Server stopped')
            self.server_proc = None
        else:
            await ctx.send("Server is not online")

    @commands.command(name="mc-info", description="Get the information of the minecraft server")
    async def _info(self, ctx: commands.Context) -> None:
        """
            This command gives information about the server in an embed

            :param ctx: The context surrounding the command evocation
            :type ctx: commands.Context
        """

        embed = discord.Embed()
        embed.title = "Server Status"
        embed.add_field(name="Address", value=f"{self.PUBLIC_IP}:{self.SERVER_PORT}", inline=False)
        try:
            stats = await self.query.async_status()
            embed.description = "Server is online"
            embed.colour = discord.Colour.green()
            embed.add_field(name="Version", value=stats.version.name, inline=False)
            embed.add_field(name="Ping", value=str(stats.latency) + " ms", inline=False)
            embed.add_field(name="Players", value=f"{stats.players.online} out of {stats.players.max}", inline=False)
            embed.set_thumbnail(url=f"https://eu.mc-api.net/v3/server/favicon/{self.PUBLIC_IP}:{self.SERVER_PORT}")
        except ConnectionError or gaierror:
            embed.description = f"Server is offline, run `{self.bot.command_prefix}mc-start` to start it"
            embed.colour = discord.Colour.red()
        await ctx.send(embed=embed)

    @commands.command(name="mc-players", description="Get the players on the server right now")
    async def _players(self, ctx: commands.Context) -> None:
        """
            This command gives a list of players on the server

            :param ctx: The context surrounding the command evocation
            :type ctx: commands.Context
        """

        if self._online():
            try:
                query = await self.query.async_query()
                names = '\n'.join(query.players.names)
                if len(names) > 0:
                    await ctx.send(f"{query.players.online} out of {query.players.max} online,\n```\n{names}\n```")
                else:
                    await ctx.send("No players online")
            except ConnectionError or TimeoutError or gaierror:
                await ctx.send("Server refused query, is query enabled?")
        else:
            await ctx.send("Server is not online")

    @commands.command(name="mc-join", description="Get the IP to join the server")
    async def _join(self, ctx: commands.Context) -> None:
        """
            This command provides the IP address and port you can use to join the server

            :param ctx: The context surrounding the command evocation
            :type ctx: commands.Context
        """

        await ctx.send(
            f"The server can be joined by typing `{self.PUBLIC_IP}:{self.SERVER_PORT}` as the server address")

    async def _execute_mc_command(self, command: str) -> str:
        """
            This function executes a command on the minecraft server via rcon

            :param command: The command to execute
            :type command: str
            :returns: What the server says in response to the command
            :rtype: str
        """

        await self._init_rcon()
        response = self.rcon.command(command)
        await self._stop_rcon()
        return response

    @commands.command(name="mc-exec", description="Execute a command on the server")
    async def _exec(self, ctx: commands.Context, *command: list[str]) -> None:
        """
            This command executes a command on the minecraft server

            :param ctx: The context surrounding the command evocation
            :type ctx: commands.Context
            :param command: The command to execute
            :type command: list[str]
        """

        if self._online():
            to_exec = ' '.join(command)
            try:
                response = await self._execute_mc_command(to_exec)
                if response != "":
                    await ctx.send(f"Server responded with the following:\n```\n{response}\n```")
            except RCONFailedError as error:
                await ctx.send(error.args[0])
        else:
            await ctx.send("Server is not online")
