from __future__ import annotations

import io
import json
import logging
import os
import shutil
from collections import OrderedDict
from homeassistant.core import HomeAssistant

import jinja2
import yaml
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.yaml import loader

from custom_components.lovelace_minimalist_ui.base import LmuBase

from .base import LmuBase
from .const import DOMAIN
from .const import VERSION

_LOGGER: logging.Logger = logging.getLogger(__name__)


def fromjson(value):
    return json.loads(value)


jinja = jinja2.Environment(loader=jinja2.FileSystemLoader("/"))

jinja.filters["fromjson"] = fromjson

lovelace_minimalist_ui_config = {}
lovelace_minimalist_ui_global = {}

LANGUAGES = {
    "English": "EN",
    "German": "DE",
    "Spanish": "ES",
    "French": "FR",
    "Italian": "IT",
    "Swedish": "SE",
    "Dutch": "NL",
}

def load_yamll(fname, secrets=None, args={}):
    try:
        process_yaml = False
        with open(fname, encoding="utf-8") as f:
            if f.readline().lower().startswith(("# lovelace_minimalist_ui")):
                process_yaml = True
        if process_yaml:
            _LOGGER.warning("PARSING JINJA TEMPLATE")
            stream = io.StringIO(
                jinja.get_template(fname).render(
                    {
                        **args,
                        "_lmu_config": lovelace_minimalist_ui_config,
                        "_lmu_global": lovelace_minimalist_ui_global,
                    }
                )
            )
            stream.name = fname
            return (
                loader.yaml.load(
                    stream,
                    Loader=lambda _stream: loader.SafeLineLoader(_stream, secrets),
                )
                or OrderedDict()
            )
        else:
            with open(fname, encoding="utf-8") as config_file:
                return (
                    loader.yaml.load(
                        config_file,
                        Loader=lambda stream: loader.SafeLineLoader(stream, secrets),
                    )
                    or OrderedDict()
                )
    except loader.yaml.YAMLError as exc:
        _LOGGER.error(str(exc))
        raise HomeAssistantError(exc)
    except UnicodeDecodeError as exc:
        _LOGGER.error("Unable to read file %s: %s", fname, exc)
        raise HomeAssistantError(exc)


def _include_yaml(ldr, node):
    args = {}
    if isinstance(node.value, str):
        fn = node.value
    else:
        fn, args, *_ = ldr.construct_sequence(node)
    fname = os.path.abspath(os.path.join(os.path.dirname(ldr.name), fn))
    try:
        return loader._add_reference(
            load_yamll(fname, ldr.secrets, args=args), ldr, node
        )
    except FileNotFoundError as exc:
        _LOGGER.error("Unable to include file %s: %s", fname, exc)
        raise HomeAssistantError(exc)


loader.load_yaml = load_yamll
loader.SafeLineLoader.add_constructor("!include", _include_yaml)


def compose_node(self, parent, index):
    if self.check_event(yaml.events.AliasEvent):
        event = self.get_event()
        anchor = event.anchor
        if anchor not in self.anchors:
            raise yaml.composer.ComposerError(
                None, None, "found undefined alias %r" % anchor, event.start_mark
            )
        return self.anchors[anchor]
    event = self.peek_event()
    anchor = event.anchor
    self.descend_resolver(parent, index)
    if self.check_event(yaml.events.ScalarEvent):
        node = self.compose_scalar_node(anchor)
    elif self.check_event(yaml.events.SequenceStartEvent):
        node = self.compose_sequence_node(anchor)
    elif self.check_event(yaml.events.MappingStartEvent):
        node = self.compose_mapping_node(anchor)
    self.ascend_resolver()
    return node


yaml.composer.Composer.compose_node = compose_node

#TODO: Maybe move all of this to .base.py so functions can be called
def process_yaml(hass: HomeAssistant, lmu: LmuBase):
    _LOGGER.debug("Checking dependencies")
    if not os.path.exists(hass.config.path("custom_components/browser_mod")):
        _LOGGER.error('HACS Integration repo "browser mod" is not installed!')


    if not lmu.configuration.include_other_cards:
        depenceny_resource_paths = [
            "button-card",
            "light-entity-card",
            "lovelace-card-mod",
            "mini-graph-card",
            "mini-media-player",
            "my-cards",
        ]
        for p in depenceny_resource_paths:
            if not os.path.exists(hass.config.path(f"www/community/{p}")):
                _LOGGER.error(f'HACS Frontend repo "{p}" is not installed, See Integration Configuration.')

    _LOGGER.warning("Start of function to process all yaml files!")

    # Create config dir
    os.makedirs(hass.config.path(f"{DOMAIN}/configs"), exist_ok=True)
    os.makedirs(hass.config.path(f"{DOMAIN}/custom_cards"), exist_ok=True)

    if os.path.exists(hass.config.path(f"{DOMAIN}/configs")):
        # Create combined cards dir
        combined_cards_dir = hass.config.path(
            f"custom_components/{DOMAIN}/__minimalist_ui__/button-cards-templates"
        )
        os.makedirs(combined_cards_dir, exist_ok=True)

        # Main config
        for fname in loader._find_files(
            hass.config.path(f"{DOMAIN}/configs"), "*.yaml"
        ):
            loaded_yaml = load_yamll(fname)
            if isinstance(loaded_yaml, dict):
                lovelace_minimalist_ui_config.update(loaded_yaml)

        # Translations
        language = LANGUAGES[lmu.configuration.language]

        # Non needed yet
        # translations = load_yamll(hass.config.path(f"custom_components/{DOMAIN}/lovelace/translations/{language}.yaml"))

        # Copy chosen language file over to config dir
        shutil.copy2(
            hass.config.path(
                f"custom_components/{DOMAIN}/lovelace/translations/{language}.yaml"
            ),
            hass.config.path(f"{combined_cards_dir}/language.yaml"),
        )
        # Copy over cards from integration
        shutil.copytree(
            hass.config.path(
                f"custom_components/{DOMAIN}/lovelace/button-cards-templates"
            ),
            hass.config.path(f"{combined_cards_dir}"),
            dirs_exist_ok=True,
        )
        shutil.copytree(
            hass.config.path(f"{DOMAIN}/custom_cards"),
            hass.config.path(f"{combined_cards_dir}/custom_cards"),
            dirs_exist_ok=True,
        )

        # Load Themes
        themes = OrderedDict()
        for fname in loader._find_files(
            hass.config.path(f"custom_components/{DOMAIN}/lovelace/themefiles"),
            "*.yaml",
        ):
            loaded_yaml = load_yamll(fname)
            if isinstance(loaded_yaml, dict):
                themes.update(loaded_yaml)
                theme_name = next(iter(loaded_yaml))

                os.makedirs(hass.config.path(f"themes/{theme_name}"), exist_ok=True)
                shutil.copy2(
                    fname, hass.config.path(f"themes/{theme_name}/{theme_name}.yaml")
                )

        theme = lmu.configuration.theme

        if os.path.exists(hass.config.path(f"custom_components/{DOMAIN}/.installed")):
            installed = "true"
        else:
            installed = "false"

        lovelace_minimalist_ui_global.update(
            [
                ("version", VERSION),
                ("theme", lmu.configuration.theme),
                ("themes", json.dumps(themes)),
                ("installed", installed),
            ]
        )

        hass.bus.async_fire("lovelace_minimalist_ui_reload")

    async def handle_reload(call):
        _LOGGER.debug("Reload Lovelace Minimalist UI Configuration")

        reload_configuration(hass)

    # Register servcie lovelace_minimalist_ui.reload
    hass.services.async_register(DOMAIN, "reload", handle_reload)

    async def handle_installed(call):
        _LOGGER.debug("Handle installed for Lovelace Minimalist UI")

        path = hass.config.path(f"custom_components/{DOMAIN}/.installed")

        if not os.path.exists(path):
            _LOGGER.debug("Create .installed file")
            open(path, "w").close()

        reload_configuration(hass)

    hass.services.async_register(DOMAIN, "installed", handle_installed)


def reload_configuration(hass):
    if os.path.exists(hass.config.path(f"{DOMAIN}/configs")):
        # Main config
        # No config generated yet at the start of process_yaml()
        config_new = OrderedDict()
        for fname in loader._find_files(
            hass.config.path(f"{DOMAIN}/configs/"), "*.yaml"
        ):
            _LOGGER.warning(f"Loading file: {fname}")
            loaded_yaml = load_yamll(fname)
            if isinstance(loaded_yaml, dict):
                config_new.update(loaded_yaml)

        lovelace_minimalist_ui_config.update(config_new)

        if os.path.exists(hass.config.path(f"custom_components/{DOMAIN}/.installed")):
            installed = "true"
        else:
            installed = "false"

        lovelace_minimalist_ui_global.update(
            [
                ("installed", installed),
            ]
        )

    hass.bus.async_fire("lovelace_minimalist_ui_reload")
