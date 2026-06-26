from bot.intelligence.channels import ChannelDirectory, ChannelInfo


def test_name_map_returns_id_to_name():
    d = ChannelDirectory([
        ChannelInfo(id="111", name="chambre-de-wally", type="text", purpose="sa chambre"),
        ChannelInfo(id="222", name="general", type="text", purpose="discussion"),
    ])
    assert d.name_map() == {"111": "chambre-de-wally", "222": "general"}
