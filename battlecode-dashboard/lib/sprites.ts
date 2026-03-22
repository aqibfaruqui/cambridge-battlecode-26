/**
 * Maps entity types and teams to their sprite image paths from the official cambc visualiser.
 *
 * Teams:  gold = Team A,  silver = Team B
 * Directional entities (gunner, sentinel, breach, splitter) have 8 compass variants.
 */

const TEAM_COLOR: Record<string, string> = { a: "gold", b: "silver" };

const DIR_ABBREV: Record<string, string> = {
  north: "n",
  northeast: "ne",
  east: "e",
  southeast: "se",
  south: "s",
  southwest: "sw",
  west: "w",
  northwest: "nw",
};

const DIRECTIONAL_TYPES = new Set(["gunner", "sentinel", "breach", "splitter"]);

const BUILDER_DIR_MAP: Record<string, string> = {
  north: "back",
  south: "front",
  east: "side",
  west: "side",
  northeast: "back",
  northwest: "back",
  southeast: "front",
  southwest: "front",
};

export function spritePath(type: string, team: string, direction?: string): string {
  const color = TEAM_COLOR[team] ?? "gold";
  const base = "/sprites";

  if (type === "core") return `${base}/base_${color}.png`;
  if (type === "harvester") return `${base}/harvester_${color}.png`;
  if (type === "foundry") return `${base}/foundry_${color}.png`;
  if (type === "conveyor") return `${base}/conveyor_${color}.png`;
  if (type === "armoured_conveyor") return `${base}/armoured_conveyor_${color}.png`;
  if (type === "bridge") return `${base}/bridge_${color}.png`;
  if (type === "barrier") return `${base}/barrier_${color}.png`;
  if (type === "road") return `${base}/road_${color}.png`;
  if (type === "marker") return `${base}/marker_${color}.png`;
  if (type === "launcher") return `${base}/launcher_${color}.png`;

  if (type === "builder_bot") {
    const pose = BUILDER_DIR_MAP[direction?.toLowerCase() ?? ""] ?? "front";
    return `${base}/builderbot_${pose}_${color}.png`;
  }

  if (DIRECTIONAL_TYPES.has(type)) {
    const dir = DIR_ABBREV[direction?.toLowerCase() ?? ""] ?? "n";
    return `${base}/${type}_${dir}_${color}.png`;
  }

  return `${base}/base_${color}.png`;
}

export function tilePath(tileType: string): string | null {
  if (tileType === "ore_titanium") return "/sprites/titanium_ore.png";
  if (tileType === "ore_axionite") return "/sprites/axionite_ore.png";
  if (tileType === "wall") return "/sprites/natural_wall.jpg";
  return null;
}

export function bgPath(): string {
  return "/sprites/bg.png";
}
