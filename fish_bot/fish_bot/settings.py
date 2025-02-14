from fish_bot import const

prefix = "$$"

memberlimit = None

monitored_roles = {
    const.top1_id,
    const.top10_id,
    const.top25_id,
    const.top50_id,
    const.top100_id,
    const.top200_id,
    const.top300_id,
    const.top400_id,
    const.top500_id,
    const.top600_id,
    const.top750_id,
    const.top800_id,
    const.top900_id,
    const.top1000_id,
    const.top1500_id,
    const.top2000_id,
}

restartable_services = {
    "discord_bot",
    "verification_bot",
    "tower-admin_site",
    "tower-hidden_site",
    "tower-public_site",
    "get_results",
    "get_results_live",
    "import_results"
}

COMMAND_CHANNEL_MAP = {
    "reload": {
        "channels": {
            const.helpers_channel_id: [const.id_pog, const.id_fishy],  # These users can use reload in helpers channel
            const.testing_channel_id: [const.id_pog],  # Only pog can use reload in testing channel
        },
        "default_users": [const.id_pog, const.id_fishy]  # These users can use reload in any allowed channel
    },
    "ServiceControl restart": {
        "channels": {
            const.helpers_channel_id: [const.id_pog, const.id_fishy],
        },
        "default_users": []
    }
}
