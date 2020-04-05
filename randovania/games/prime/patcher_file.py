import random
from random import Random
from typing import Dict, List, Iterator

import randovania
from randovania.game_description import data_reader
from randovania.game_description.area_location import AreaLocation
from randovania.game_description.assignment import GateAssignment, PickupTarget
from randovania.game_description.default_database import default_prime2_memo_data
from randovania.game_description.game_description import GameDescription
from randovania.game_description.game_patches import GamePatches
from randovania.game_description.item.item_category import ItemCategory
from randovania.game_description.node import TeleporterNode
from randovania.game_description.resources.pickup_entry import PickupEntry
from randovania.game_description.resources.pickup_index import PickupIndex
from randovania.game_description.resources.resource_database import ResourceDatabase
from randovania.game_description.resources.resource_info import ResourceGainTuple, ResourceGain, CurrentResources, \
    ResourceInfo
from randovania.game_description.resources.resource_type import ResourceType
from randovania.game_description.world_list import WorldList
from randovania.games.prime.patcher_file_lib import sky_temple_key_hint, item_hints
from randovania.generator.item_pool import pickup_creator, pool_creator
from randovania.interface_common.cosmetic_patches import CosmeticPatches
from randovania.interface_common.players_configuration import PlayersConfiguration
from randovania.layout.hint_configuration import HintConfiguration, SkyTempleKeyHintMode
from randovania.layout.layout_configuration import LayoutConfiguration, LayoutElevators
from randovania.layout.layout_description import LayoutDescription
from randovania.layout.patcher_configuration import PickupModelStyle, PickupModelDataSource

_TOTAL_PICKUP_COUNT = 119
_CUSTOM_NAMES_FOR_ELEVATORS = {
    # Great Temple
    408633584: "Temple Transport Emerald",
    2399252740: "Temple Transport Violet",
    2556480432: "Temple Transport Amber",

    # Temple Grounds to Great Temple
    1345979968: "Sanctuary Quadrant",
    1287880522: "Agon Quadrant",
    2918020398: "Torvus Quadrant",

    # Temple Grounds to Areas
    1660916974: "Agon Gate",
    2889020216: "Torvus Gate",
    3455543403: "Sanctuary Gate",

    # Agon
    1473133138: "Agon Entrance",
    2806956034: "Agon Portal Access",
    3331021649: "Agon Temple Access",

    # Torvus
    1868895730: "Torvus Entrance",
    3479543630: "Torvus Temple Access",
    3205424168: "Lower Torvus Access",

    # Sanctuary
    3528156989: "Sanctuary Entrance",
    900285955: "Sanctuary Spider side",
    3145160350: "Sanctuary Vault side",
}

_RESOURCE_NAME_TRANSLATION = {
    'Temporary Missile': 'Missile',
    'Temporary Power Bombs': 'Power Bomb',
}


def _resource_user_friendly_name(resource: ResourceInfo) -> str:
    """
    Gets a name that we should display to the user for the given resource.
    :param resource:
    :return:
    """
    return _RESOURCE_NAME_TRANSLATION.get(resource.long_name, resource.long_name)


def _create_spawn_point_field(patches: GamePatches,
                              resource_database: ResourceDatabase,
                              ) -> dict:
    capacities = [
        {
            "index": item.index,
            "amount": patches.starting_items.get(item, 0),
        }
        for item in resource_database.item
    ]

    return {
        "location": patches.starting_location.as_json,
        "amount": capacities,
        "capacity": capacities,
    }


def _get_jingle_index_for(category: ItemCategory) -> int:
    if category.is_key:
        return 2
    elif category.is_major_category and category != ItemCategory.ENERGY_TANK:
        return 1
    else:
        return 0


def _pickup_scan(pickup: PickupEntry) -> str:
    if pickup.item_category != ItemCategory.EXPANSION:
        if len(pickup.resources) > 1 and all(conditional.name is not None for conditional in pickup.resources):
            return "{}. Provides the following in order: {}".format(
                pickup.name, ", ".join(conditional.name for conditional in pickup.resources))
        else:
            return pickup.name

    return "{} that provides {}".format(
        pickup.name,
        " and ".join(
            "{} {}".format(quantity, _resource_user_friendly_name(resource))
            for resource, quantity in pickup.resources[-1].resources
        )
    )


def _create_pickup_resources_for(resources: ResourceGain):
    return [
        {
            "index": resource.index,
            "amount": quantity
        }
        for resource, quantity in resources
        if quantity > 0 and resource.resource_type == ResourceType.ITEM
    ]


def _get_single_hud_text(pickup_name: str,
                         memo_data: Dict[str, str],
                         resources: ResourceGainTuple,
                         ) -> str:
    return memo_data[pickup_name].format(**{
        _resource_user_friendly_name(resource): quantity
        for resource, quantity in resources
    })


def _get_all_hud_text(pickup: PickupEntry,
                      memo_data: Dict[str, str],
                      ) -> List[str]:
    return [
        _get_single_hud_text(conditional.name or pickup.name, memo_data, conditional.resources)
        for conditional in pickup.resources
    ]


def _calculate_hud_text(pickup: PickupEntry,
                        visual_pickup: PickupEntry,
                        model_style: PickupModelStyle,
                        memo_data: Dict[str, str],
                        ) -> List[str]:
    """
    Calculates what the hud_text for a pickup should be
    :param pickup:
    :param visual_pickup:
    :param model_style:
    :param memo_data:
    :return:
    """

    if model_style == PickupModelStyle.HIDE_ALL:
        hud_text = _get_all_hud_text(visual_pickup, memo_data)
        if len(hud_text) == len(pickup.resources):
            return hud_text
        else:
            return [hud_text[0]] * len(pickup.resources)

    else:
        return _get_all_hud_text(pickup, memo_data)


class PickupCreator:
    def create_pickup_data(self,
                           original_index: PickupIndex,
                           pickup_target: PickupTarget,
                           visual_pickup: PickupEntry,
                           model_style: PickupModelStyle,
                           scan_text: str) -> dict:
        raise NotImplementedError()

    def create_pickup(self,
                      original_index: PickupIndex,
                      pickup_target: PickupTarget,
                      visual_pickup: PickupEntry,
                      model_style: PickupModelStyle,
                      ) -> dict:
        model_pickup = pickup_target.pickup if model_style == PickupModelStyle.ALL_VISIBLE else visual_pickup

        if model_style in {PickupModelStyle.ALL_VISIBLE, PickupModelStyle.HIDE_MODEL}:
            scan_text = _pickup_scan(pickup_target.pickup)
        else:
            scan_text = visual_pickup.name

        # TODO: less improvised, really
        model_index = model_pickup.model_index
        if model_index == 22 and random.randint(0, 8192) == 0:
            # If placing a missile expansion model, replace with Dark Missile Trooper model with a 1/8192 chance
            model_index = 23

        result = {
            "pickup_index": original_index.index,
            **self.create_pickup_data(original_index, pickup_target, visual_pickup, model_style, scan_text),
            "model_index": model_index,
            "sound_index": 1 if model_pickup.item_category.is_key else 0,
            "jingle_index": _get_jingle_index_for(model_pickup.item_category),
        }
        return result


class PickupCreatorSolo(PickupCreator):
    def __init__(self, memo_data: Dict[str, str]):
        self.memo_data = memo_data

    def create_pickup_data(self,
                           original_index: PickupIndex,
                           pickup_target: PickupTarget,
                           visual_pickup: PickupEntry,
                           model_style: PickupModelStyle,
                           scan_text: str) -> dict:
        return {
            "resources": _create_pickup_resources_for(pickup_target.pickup.resources[0].resources),
            "conditional_resources": [
                {
                    "item": conditional.item.index,
                    "resources": _create_pickup_resources_for(conditional.resources),
                }
                for conditional in pickup_target.pickup.resources[1:]
            ],
            "convert": [
                {
                    "from_item": conversion.source.index,
                    "to_item": conversion.target.index,
                    "clear_source": conversion.clear_source,
                    "overwrite_target": conversion.overwrite_target,
                }
                for conversion in pickup_target.pickup.convert_resources
            ],
            "hud_text": _calculate_hud_text(pickup_target.pickup, visual_pickup, model_style, self.memo_data),
            "scan": scan_text,
        }


class PickupCreatorMulti(PickupCreator):
    def __init__(self, player_names: Dict[int, str]):
        self.player_names = player_names

    def create_pickup_data(self,
                           original_index: PickupIndex,
                           pickup_target: PickupTarget,
                           visual_pickup: PickupEntry,
                           model_style: PickupModelStyle,
                           scan_text: str) -> dict:
        resources = [
            {
                "index": 74,
                "amount": original_index.index + 1,
            },
        ]
        resources.extend(
            entry
            for entry in _create_pickup_resources_for(pickup_target.pickup.resources[0].resources)
            if entry["index"] == 47
        )

        return {
            "resources": resources,
            "conditional_resources": [],
            "convert": [],
            "hud_text": [f"{self.player_names[pickup_target.player]} acquired {pickup_target.pickup.name}!"],
            "scan": f"{self.player_names[pickup_target.player]}'s {scan_text}",
        }


def _get_visual_model(original_index: int,
                      pickup_list: List[PickupTarget],
                      data_source: PickupModelDataSource,
                      ) -> PickupEntry:
    if data_source == PickupModelDataSource.ETM:
        return pickup_creator.create_visual_etm()
    elif data_source == PickupModelDataSource.RANDOM:
        return pickup_list[original_index % len(pickup_list)].pickup
    elif data_source == PickupModelDataSource.LOCATION:
        raise NotImplementedError()
    else:
        raise ValueError(f"Unknown data_source: {data_source}")


def _create_pickup_list(patches: GamePatches,
                        useless_target: PickupTarget,
                        pickup_count: int,
                        rng: Random,
                        model_style: PickupModelStyle,
                        data_source: PickupModelDataSource,
                        creator: PickupCreator,
                        ) -> list:
    """
    Creates the patcher data for all pickups in the game
    :param patches:
    :param useless_target:
    :param pickup_count:
    :param rng:
    :param model_style:
    :param data_source:
    :param creator:
    :return:
    """
    pickup_assignment = patches.pickup_assignment

    pickup_list = list(pickup_assignment.values())
    rng.shuffle(pickup_list)

    pickups = [
        creator.create_pickup(PickupIndex(i),
                              pickup_assignment.get(PickupIndex(i), useless_target),
                              _get_visual_model(i, pickup_list, data_source),
                              model_style,
                              )
        for i in range(pickup_count)
    ]

    return pickups


def _elevator_area_name(world_list: WorldList,
                        area_location: AreaLocation,
                        ) -> str:
    if area_location.area_asset_id in _CUSTOM_NAMES_FOR_ELEVATORS:
        return _CUSTOM_NAMES_FOR_ELEVATORS[area_location.area_asset_id]

    else:
        world = world_list.world_by_area_location(area_location)
        area = world.area_by_asset_id(area_location.area_asset_id)
        return area.name


def _pretty_name_for_elevator(world_list: WorldList,
                              original_teleporter_node: TeleporterNode,
                              connection: AreaLocation,
                              ) -> str:
    """
    Calculates the name the room that contains this elevator should have
    :param world_list:
    :param original_teleporter_node:
    :param connection:
    :return:
    """
    if original_teleporter_node.keep_name_when_vanilla:
        if original_teleporter_node.default_connection == connection:
            return world_list.nodes_to_area(original_teleporter_node).name

    return "Transport to {}".format(_elevator_area_name(world_list, connection))


def _create_elevators_field(patches: GamePatches, game: GameDescription) -> list:
    """
    Creates the elevator entries in the patcher file
    :param patches:
    :param game:
    :return:
    """

    world_list = game.world_list
    nodes_by_teleporter_id = _get_nodes_by_teleporter_id(world_list)
    elevator_connection = patches.elevator_connection

    if len(elevator_connection) != len(nodes_by_teleporter_id):
        raise ValueError("Invalid elevator count. Expected {}, got {}.".format(
            len(nodes_by_teleporter_id), len(elevator_connection)
        ))

    elevators = [
        {
            "instance_id": instance_id,
            "origin_location": world_list.node_to_area_location(nodes_by_teleporter_id[instance_id]).as_json,
            "target_location": connection.as_json,
            "room_name": _pretty_name_for_elevator(world_list, nodes_by_teleporter_id[instance_id], connection)
        }
        for instance_id, connection in elevator_connection.items()
    ]

    return elevators


def _get_nodes_by_teleporter_id(world_list: WorldList) -> Dict[int, TeleporterNode]:
    nodes_by_teleporter_id = {
        node.teleporter_instance_id: node

        for node in world_list.all_nodes
        if isinstance(node, TeleporterNode) and node.editable
    }
    return nodes_by_teleporter_id


def _create_translator_gates_field(gate_assignment: GateAssignment) -> list:
    """
    Creates the translator gate entries in the patcher file
    :param gate_assignment:
    :return:
    """
    return [
        {
            "gate_index": gate.index,
            "translator_index": translator.index,
        }
        for gate, translator in gate_assignment.items()
    ]


def _apply_translator_gate_patches(specific_patches: dict, elevators: LayoutElevators) -> None:
    """

    :param specific_patches:
    :param elevators:
    :return:
    """
    specific_patches["always_up_gfmc_compound"] = True
    specific_patches["always_up_torvus_temple"] = True
    specific_patches["always_up_great_temple"] = elevators != LayoutElevators.VANILLA


def _create_elevator_scan_port_patches(world_list: WorldList, elevator_connection: Dict[int, AreaLocation],
                                       ) -> Iterator[dict]:
    nodes_by_teleporter_id = _get_nodes_by_teleporter_id(world_list)

    for teleporter_id, node in nodes_by_teleporter_id.items():
        if node.scan_asset_id is None:
            continue

        target_area_name = _elevator_area_name(world_list, elevator_connection[teleporter_id])
        yield {
            "asset_id": node.scan_asset_id,
            "strings": [f"Access to &push;&main-color=#FF3333;{target_area_name}&pop; granted.", ""],
        }


def _create_string_patches(hint_config: HintConfiguration,
                           game: GameDescription,
                           all_patches: Dict[int, GamePatches],
                           players_config: PlayersConfiguration,
                           rng: Random,
                           ) -> list:
    """

    :param hint_config:
    :param game:
    :param patches:
    :return:
    """
    patches = all_patches[players_config.player_index]
    string_patches = []

    # Location Hints
    string_patches.extend(
        item_hints.create_hints(patches, game.world_list, rng)
    )

    # Sky Temple Keys
    stk_mode = hint_config.sky_temple_keys
    if stk_mode == SkyTempleKeyHintMode.DISABLED:
        string_patches.extend(sky_temple_key_hint.hide_hints())
    else:
        string_patches.extend(sky_temple_key_hint.create_hints(all_patches, players_config, game.world_list,
                                                               stk_mode == SkyTempleKeyHintMode.HIDE_AREA))

    # Elevator Scans
    string_patches.extend(_create_elevator_scan_port_patches(game.world_list, patches.elevator_connection))

    return string_patches


def additional_starting_items(layout_configuration: LayoutConfiguration,
                              resource_database: ResourceDatabase,
                              starting_items: CurrentResources) -> List[str]:
    initial_items = pool_creator.calculate_pool_results(layout_configuration, resource_database)[2]

    return [
        "{}{}".format("{} ".format(quantity) if quantity > 1 else "", _resource_user_friendly_name(item))
        for item, quantity in starting_items.items()
        if 0 < quantity != initial_items.get(item, 0)
    ]


def _create_starting_popup(layout_configuration: LayoutConfiguration,
                           resource_database: ResourceDatabase,
                           starting_items: CurrentResources) -> list:
    extra_items = additional_starting_items(layout_configuration, resource_database, starting_items)
    if extra_items:
        return [
            "Extra starting items:",
            ", ".join(extra_items)
        ]
    else:
        return []


class _SimplifiedMemo(dict):
    def __missing__(self, key):
        return "{} acquired!".format(key)


def _simplified_memo_data() -> Dict[str, str]:
    result = _SimplifiedMemo()
    result["Temporary Power Bombs"] = "Power Bomb Expansion acquired, but the main Power Bomb is required to use it."
    result["Temporary Missile"] = "Missile Expansion acquired, but the Missile Launcher, is required to use it."
    return result


def create_patcher_file(description: LayoutDescription,
                        players_config: PlayersConfiguration,
                        cosmetic_patches: CosmeticPatches,
                        ) -> dict:
    """

    :param description:
    :param players_config:
    :param cosmetic_patches:
    :return:
    """
    preset = description.permalink.get_preset(players_config.player_index)
    patcher_config = preset.patcher_configuration
    layout = preset.layout_configuration
    patches = description.all_patches[players_config.player_index]
    rng = Random(description.permalink.as_str)

    game = data_reader.decode_data(layout.game_data)
    useless_target = PickupTarget(pickup_creator.create_useless_pickup(game.resource_database),
                                  players_config.player_index)

    result = {}
    _add_header_data_to_result(description, result)

    # Add Spawn Point
    result["spawn_point"] = _create_spawn_point_field(patches, game.resource_database)

    result["starting_popup"] = _create_starting_popup(layout, game.resource_database, patches.starting_items)

    # Add the pickups
    if description.permalink.player_count == 1:
        if cosmetic_patches.disable_hud_popup:
            memo_data = _simplified_memo_data()
        else:
            memo_data = default_prime2_memo_data()
        creator = PickupCreatorSolo(memo_data)
    else:
        creator = PickupCreatorMulti(players_config.player_names)

    result["pickups"] = _create_pickup_list(patches,
                                            useless_target, _TOTAL_PICKUP_COUNT,
                                            rng,
                                            patcher_config.pickup_model_style,
                                            patcher_config.pickup_model_data_source,
                                            creator=creator,
                                            )

    # Add the elevators
    result["elevators"] = _create_elevators_field(patches, game)

    # Add translators
    result["translator_gates"] = _create_translator_gates_field(patches.translator_gates)

    # Scan hints
    result["string_patches"] = _create_string_patches(layout.hints, game, description.all_patches, players_config, rng)

    # TODO: if we're starting at ship, needs to collect 9 sky temple keys and want item loss,
    # we should disable hive_chamber_b_post_state
    result["specific_patches"] = {
        "hive_chamber_b_post_state": True,
        "intro_in_post_state": True,
        "warp_to_start": patcher_config.warp_to_start,
        "speed_up_credits": cosmetic_patches.speed_up_credits,
        "disable_hud_popup": cosmetic_patches.disable_hud_popup,
        "pickup_map_icons": cosmetic_patches.pickup_markers,
        "full_map_at_start": cosmetic_patches.open_map,
        "dark_world_varia_suit_damage": patcher_config.varia_suit_damage,
        "dark_world_dark_suit_damage": patcher_config.dark_suit_damage,
    }

    _apply_translator_gate_patches(result["specific_patches"], layout.elevators)

    return result


def _add_header_data_to_result(description: LayoutDescription, result: dict) -> None:
    result["permalink"] = description.permalink.as_str
    result["seed_hash"] = f"- {description.shareable_word_hash} ({description.shareable_hash})"
    result["randovania_version"] = randovania.VERSION
