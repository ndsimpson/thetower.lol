from discord.ext.commands import Context, Paginator


class CogLoader:
    def __init__(self, bot):
        self.bot = bot

    async def list_modules(self, ctx: Context) -> None:
        """Lists all cogs and their status of loading."""
        cog_list = Paginator(prefix='', suffix='')
        cog_list.add_line('**✅ Succesfully loaded:**')
        for cog in self.bot.loaded_cogs:
            cog_list.add_line('- ' + cog)
        cog_list.add_line('**❌ Not loaded:**')
        for cog in self.bot.unloaded_cogs:
            cog_list.add_line('- ' + cog)
        for page in cog_list.pages:
            print(page)
            await ctx.send(page)

    async def load_cog(self, ctx: Context, cog: str) -> None:
        """Try and load the selected cog."""
        if cog not in self.bot.unloaded_cogs:
            await ctx.send('⚠ WARNING: Module appears not to be found in the available modules list. Will try loading anyway.')
        if cog in self.bot.loaded_cogs:
            return await ctx.send('Cog already loaded.')
        try:
            await self.bot.load_extension(f'cogs.{cog}')
        except Exception as e:
            await ctx.send('**💢 Could not load module: An exception was raised. For your convenience, the exception will be printed below:**')
            await ctx.send('```{}\n{}```'.format(type(e).__name__, e))
        else:
            self.bot.loaded_cogs.append(cog)
            try:
                self.bot.unloaded_cogs.remove(cog)
            except ValueError:
                pass
            await ctx.send('✅ Module succesfully loaded.')

    async def unload_cog(self, ctx: Context, cog: str) -> None:
        """Unload the selected cog."""
        if cog not in self.bot.loaded_cogs:
            return await ctx.send('💢 Module not loaded.')
        await self.bot.unload_extension(f'cogs.{cog}')
        self.bot.loaded_cogs.remove(cog)
        self.bot.unloaded_cogs.append(cog)
        await ctx.send('✅ Module succesfully unloaded.')

    async def reload_cog(self, ctx: Context, cog: str) -> None:
        """Reload the selected cog."""
        await self.unload_cog(ctx, cog)
        await self.load_cog(ctx, cog)
