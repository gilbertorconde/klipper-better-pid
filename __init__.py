from klippy.configfile import ConfigWrapper
from .better_pid import BetterPID


def load_config_prefix(config: ConfigWrapper):
    return BetterPID(config)

