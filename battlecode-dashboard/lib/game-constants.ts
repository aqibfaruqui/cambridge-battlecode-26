/**
 * Constants aligned with battlecode/docs/game_constants.md and overview.
 */

export const MAX_TURNS = 2000;
export const STACK_SIZE = 10;
export const STARTING_TITANIUM = 1000;
export const STARTING_AXIONITE = 0;

export const CORE_MAX_HP = 500;
export const BUILDER_BOT_SELF_DESTRUCT_DAMAGE = 20;

export const CORE_FOOTPRINT = 3;

/** Vision / attack r² from docs (turrets use same r² for vision and attack where noted) */
export const VISION_R2 = {
  core: 36,
  builder_bot: 20,
  gunner: 13,
  sentinel: 32,
  breach: 10,
  breach_attack: 5,
  launcher: 26,
} as const;

export const TURRET_TYPES = new Set([
  "gunner",
  "sentinel",
  "breach",
  "launcher",
]);

/** Approximate base titanium cost for spending estimates from build events */
export const BASE_TITANIUM_COST: Record<string, number> = {
  builder_bot: 10,
  conveyor: 3,
  splitter: 6,
  bridge: 10,
  armoured_conveyor: 10,
  harvester: 80,
  road: 1,
  barrier: 3,
  foundry: 120,
  gunner: 10,
  sentinel: 15,
  breach: 30,
  launcher: 20,
  marker: 0,
  core: 0,
};

export const BASE_AXIONITE_COST: Record<string, number> = {
  breach: 10,
  armoured_conveyor: 5,
};

export const BUILDING_TYPES = new Set([
  "core",
  "builder_bot",
  "conveyor",
  "splitter",
  "armoured_conveyor",
  "bridge",
  "harvester",
  "foundry",
  "road",
  "barrier",
  "marker",
  "gunner",
  "sentinel",
  "breach",
  "launcher",
]);
